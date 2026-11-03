#!/usr/bin/env python3
"""Installs the swarm harness into a repository, non-invasively. Coexists with the memory install (never replaces it).

Flow (always in this order):
  1. analyze  <repo>                      analyse the project: stack, test runners, existing agent/memory files, legacy configs,
                                          and PROPOSE the agents and the changes. Writes nothing.
  2. install  <repo> --scope repo|global  dry run by default (lists every file it would add/change). `--apply` writes.
                                          --scope is REQUIRED: without it exit code 3 and the question to ask the user:
                                          repo   = roles live in <repo>/.claude/agents (versioned with the project)
                                          global = roles live in ~/.claude/agents (shared by every repo on this Mac)
                                          Project knowledge (AGENTS.md, ARCHITECTURE.md, progress/, health script, CLAUDE.md block) is always per repo.
  3. --cleanup                            lists legacy configs; with --apply moves them to .agent-memory/legacy-backup/<stamp>/ (never deletes).
Rules: idempotent (2nd run = no changes); never overwrites or deletes a file it did not create; a foreign AGENTS.md is left
untouched and the protocol goes inline into CLAUDE.md; CLAUDE.md otherwise imports @AGENTS.md.
"""
from __future__ import annotations

import argparse, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "swarm"))
import miniyaml  # noqa: E402
from swarmlib import policy as pol  # noqa: E402

T = ROOT / "templates" / "harness"
BEGIN, END = "<!-- swarm-harness:begin -->", "<!-- swarm-harness:end -->"
OURS_MARK = "<!-- installed by swarm harness -->"
MANIFEST = ".agent-memory/harness-manifest.json"
ROLES = ("leader", "explorer", "implementer", "reviewer", "gitops")
SCOPE_QUESTION = ("ASK_SCOPE: install the agent roles globally (~/.claude/agents, shared by all your repos) or inside each repo "
                  "(.claude/agents, versioned with the project)? Re-run with --scope global|repo.")


def sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


# ---------------------------------------------------------------- analysis
SKIP_DIRS = {"node_modules", "dist", "build", "venv", "env", "site-packages", "__pycache__", "docs", "vendor"}
SAFE_DIR = re.compile(r"^[A-Za-z0-9_.-]+$")


def _runners_in(d: Path, rel: str) -> list[dict]:
    r = []

    def add(name: str, cmd: str):
        r.append({"name": name if not rel else f"{name}:{rel}", "cmd": cmd, "dir": rel})

    pj = d / "package.json"
    if pj.exists():
        try:
            meta = json.loads(pj.read_text())
        except json.JSONDecodeError:
            meta = {}
        scripts = meta.get("scripts", {})
        deps = {**meta.get("dependencies", {}), **meta.get("devDependencies", {})}
        if "test" in scripts and "no test specified" not in scripts["test"]:
            add("node", "npm test --silent")
        elif (d / "tsconfig.json").exists() and "typescript" in deps:
            add("typecheck", "npx tsc --noEmit")
    pyproj = d / "pyproject.toml"
    has_pytest = (d / "pytest.ini").exists() or (d / "tox.ini").exists() or (d / "setup.cfg").exists() \
        or (pyproj.exists() and "pytest" in pyproj.read_text(errors="ignore")) or bool(list(d.glob("tests/test_*.py"))[:1])
    if has_pytest:
        add("python", "poetry run pytest -q" if (d / "poetry.lock").exists() else "python3 -m pytest -q")
    if (d / "go.mod").exists():
        add("go", "go test ./...")
    if (d / "Cargo.toml").exists():
        add("rust", "cargo test --quiet")
    return r


def detect_runners(repo: Path) -> list[dict]:
    """Test runners and type checks in the root and in each immediate subdirectory (monorepos)."""
    r = _runners_in(repo, "")
    for sub in sorted(repo.iterdir()):
        if sub.is_dir() and not sub.name.startswith(".") and sub.name not in SKIP_DIRS and SAFE_DIR.match(sub.name):
            r += _runners_in(sub, sub.name)
    if (repo / "openspec").is_dir():
        r.append({"name": "openspec", "cmd": "openspec validate --all --strict", "dir": ""})
    return r


def detect_profiles(repo: Path) -> dict:
    out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/detect_project_type.py"), str(repo)], capture_output=True, text=True)
    kv = dict(re.findall(r"([A-Z]+)=(.*?)(?= [A-Z]+=|$)", out.stdout.strip()))
    known = {q.name for q in (ROOT / "profiles").iterdir() if q.is_dir()}
    layers = [x for x in (kv.get("PROFILES") or "generic").split(",") if x in known] or ["generic"]
    return {"profiles": layers, "confident": out.returncode == 0 and layers != ["generic"] or kv.get("PROFILES") == "generic",
            "ask": kv.get("ASK"), "options": (kv.get("OPTIONS") or "").split("|") if kv.get("OPTIONS") else []}


def owned(repo: Path, rel: str) -> bool:
    m = repo / MANIFEST
    return m.exists() and rel in json.loads(m.read_text()).get("files", {})


def legacy_candidates(repo: Path) -> list[dict]:
    out = []
    fl = repo / "featurelist.json"
    if fl.exists():
        try:
            gen = bool(json.loads(fl.read_text()).get("generated"))
        except json.JSONDecodeError:
            gen = False
        if not gen:
            out.append({"path": "featurelist.json", "why": "hand-written backlog; the new one is generated from OpenSpec changes"})
    for f in ("claude-progress.txt", "init.sh"):
        if (repo / f).exists() and not owned(repo, f):
            out.append({"path": f, "why": "old harness file superseded by progress/current.md and scripts/health.sh"})
    for p in sorted(repo.glob("exploration_*")):
        out.append({"path": p.name, "why": "old exploration notes (not indexed by the harness)"})
    ad = repo / ".claude" / "agents"
    if ad.is_dir():
        for p in sorted(ad.glob("*.md")):
            rel = f".claude/agents/{p.name}"
            if not owned(repo, rel):
                out.append({"path": rel, "why": "agent definition not created by this harness (may clash with roles); review, move only if obsolete"})
    return out


def analyze(repo: Path) -> dict:
    prof = detect_profiles(repo)
    agents = repo / "AGENTS.md"
    foreign_agents = agents.exists() and OURS_MARK not in agents.read_text() and not owned(repo, "AGENTS.md")
    p = pol.load()
    mem = (repo / ".agent-memory" / "project.yaml").exists()
    return {
        "repo": str(repo), "project_id": (miniyaml.load((repo / ".agent-memory/project.yaml").read_text()) or {}).get("project_id") if mem else None,
        "profiles": prof, "test_runners": detect_runners(repo), "memory_installed": mem,
        "openspec_initialized": (repo / "openspec").is_dir(), "foreign_agents_md": foreign_agents,
        "claude_md": (repo / "CLAUDE.md").exists(), "legacy": legacy_candidates(repo),
        "proposed_agents": {r: {"model": pol.model_for(p, r), "effort": p["roles"][r].get("effort"), "tools": p["roles"][r]["tools"],
                                "stack_rules_from": [x for x in prof["profiles"] if x != "generic"]} for r in ROLES},
        "proposed_changes": [
            "add ARCHITECTURE.md, progress/current.md, progress/history.md (if absent)",
            "generate scripts/health.sh from the detected test runners (if absent)",
            "CLAUDE.md: add the harness block" + (" INLINE (foreign AGENTS.md is not touched)" if foreign_agents else " importing @AGENTS.md"),
            "AGENTS.md: " + ("left untouched" if foreign_agents else "create (if absent)"),
            ".agent-memory/project.yaml: index ARCHITECTURE.md and progress/history.md, exclude progress/current.md and exploration_*" if mem else
            "memory not installed: run scripts/install_project.py first (the harness never replaces the memory contract)",
        ],
    }


# ---------------------------------------------------------------- planning of file actions
def health_script(runners: list[dict]) -> str:
    def line(r):
        if r.get("dir"):
            return f'run "{r["name"]}" bash -c \'cd {r["dir"]} && {r["cmd"]}\''
        return f'run "{r["name"]}" {r["cmd"]}'
    body = "\n".join(line(r) for r in runners) or 'echo "no test runner detected: add checks to scripts/health.sh"'
    return f"""#!/usr/bin/env bash
{OURS_MARK.replace('<!-- ', '# ').replace(' -->', '')}
# Project health gate: exits non-zero if ANY detected check fails. Edit freely (add checks); it is yours after creation.
cd "$(dirname "$0")/.." || exit 1
fail=0
run() {{ name="$1"; shift; echo "== $name"; "$@" || {{ echo "FAILED: $name"; fail=1; }}; }}
{body}
exit $fail
"""


def role_text(role: str, p: dict, profile_rules: str) -> str:
    t = (T / "roles" / f"{role}.md").read_text()
    tools = ", ".join(str(x) for x in p["roles"][role]["tools"])
    prof = ("\n## Project stack rules\n\n" + profile_rules.strip() + "\n") if profile_rules.strip() else ""
    return t.replace("__TOOLS__", tools).replace("__MODEL__", p["roles"][role]["model"]).replace("__PROFILE__", prof)


def claude_block(import_agents: bool) -> str:
    if import_agents:
        body = "Agent protocol: @AGENTS.md\n"
    else:
        body = (T / "agents-protocol.md").read_text().split("\n", 2)[2].strip() + "\n"
    return f"{BEGIN}\n## Swarm harness\n\n{body}{END}\n"


def plan(repo: Path, scope: str, cleanup: bool) -> list[dict]:
    a = analyze(repo)
    p = pol.load()
    lang = "en"
    rules = []
    for l in a["profiles"]["profiles"]:
        f = ROOT / "profiles" / l / f"rules.{lang}.md"
        if l != "generic" and f.exists():
            rules.append(f.read_text())
    prof_text = "\n\n".join(rules)
    acts: list[dict] = []

    def add(rel: str, content: str, base: Path | None = None, exe: bool = False):
        base = base or repo
        dest = base / rel
        key = rel if base == repo else f"~/{rel}"
        if dest.exists():
            cur = dest.read_text()
            if cur == content:
                return
            if base == repo and owned(repo, rel):
                acts.append({"op": "change", "path": rel, "dest": dest, "content": content, "own": key, "exe": exe}); return
            acts.append({"op": "skip", "path": rel, "dest": dest, "why": "exists and was not created by the harness (never overwritten)"}); return
        acts.append({"op": "add", "path": rel, "dest": dest, "content": content, "own": key, "exe": exe})

    if not a["foreign_agents_md"]:
        add("AGENTS.md", OURS_MARK + "\n" + (T / "agents-protocol.md").read_text())
    else:
        acts.append({"op": "skip", "path": "AGENTS.md", "dest": repo / "AGENTS.md", "why": "foreign file left untouched; protocol goes into CLAUDE.md"})
    add("ARCHITECTURE.md", (T / "ARCHITECTURE.md").read_text())
    add("progress/current.md", (T / "progress-current.md").read_text())
    add("progress/history.md", (T / "progress-history.md").read_text())
    add("scripts/health.sh", health_script(a["test_runners"]), exe=True)
    base = repo if scope == "repo" else Path.home()
    for r in ROLES:
        add(f".claude/agents/{r}.md", role_text(r, p, prof_text), base)
    # CLAUDE.md block (append once; update only inside our markers)
    cm = repo / "CLAUDE.md"
    block = claude_block(not a["foreign_agents_md"])
    cur = cm.read_text() if cm.exists() else "# CLAUDE.md\n"
    if BEGIN in cur:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", block, cur, flags=re.S)
    else:
        new = cur.rstrip("\n") + "\n\n" + block
    if new != (cm.read_text() if cm.exists() else None):
        acts.append({"op": "change" if cm.exists() else "add", "path": "CLAUDE.md", "dest": cm, "content": new, "own": None, "exe": False,
                     "note": "only the marked harness block is added/updated"})
    # project.yaml sources (memory coexistence)
    py = repo / ".agent-memory" / "project.yaml"
    if py.exists():
        txt = py.read_text()
        new = txt
        if "ARCHITECTURE.md" not in txt:
            new = re.sub(r"^(sources:\s*\n)", r"\1  - ARCHITECTURE.md\n  - progress/history.md\n", new, count=1, flags=re.M)
        if "progress/current.md" not in new:
            new = re.sub(r"^(exclude:\s*\n)", r"\1  - 'progress/current.md'\n  - 'exploration_*'\n", new, count=1, flags=re.M)
        if new != txt:
            acts.append({"op": "change", "path": ".agent-memory/project.yaml", "dest": py, "content": new, "own": None, "exe": False,
                         "note": "adds harness documents to the memory sources; dataset unchanged"})
    if cleanup:
        for c in a["legacy"]:
            acts.append({"op": "move", "path": c["path"], "dest": repo / c["path"], "why": c["why"]})
    return acts


def apply(repo: Path, acts: list[dict], scope: str) -> None:
    mf = repo / MANIFEST
    man = json.loads(mf.read_text()) if mf.exists() else {"version": 1, "files": {}}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for x in acts:
        if x["op"] in ("add", "change"):
            x["dest"].parent.mkdir(parents=True, exist_ok=True)
            x["dest"].write_text(x["content"], encoding="utf-8")
            if x.get("exe"):
                x["dest"].chmod(0o755)
            if x.get("own") and not x["own"].startswith("~/"):
                man["files"][x["own"]] = sha(x["content"])
        elif x["op"] == "move":
            bk = repo / ".agent-memory" / "legacy-backup" / stamp / x["path"]
            bk.parent.mkdir(parents=True, exist_ok=True)
            x["dest"].rename(bk)
    man["scope"] = scope
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analyze"); s.add_argument("repo", type=Path)
    i = sub.add_parser("install"); i.add_argument("repo", type=Path)
    i.add_argument("--scope", choices=("repo", "global")); i.add_argument("--apply", action="store_true"); i.add_argument("--cleanup", action="store_true")
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    if not (repo / ".git").exists():
        print(f"{repo} is not a git repository", file=sys.stderr); return 1
    if a.cmd == "analyze":
        print(json.dumps(analyze(repo), indent=2, default=str)); return 0
    if not a.scope:
        print(SCOPE_QUESTION, file=sys.stderr); return 3
    acts = plan(repo, a.scope, a.cleanup)
    if not [x for x in acts if x["op"] != "skip"]:
        for x in acts:
            print(f"  note: {x['path']} {x.get('why', '')}", file=sys.stderr)
        print("no changes"); return 0
    print(("APPLYING" if a.apply else "DRY RUN (nothing written; add --apply)") + f" — scope={a.scope}")
    for x in acts:
        extra = x.get("why") or x.get("note") or ""
        shown = f"~/{x['path']}" if (a.scope == "global" and x["path"].startswith(".claude/agents/")) else x["path"]
        print(f"  {x['op']:6s} {shown}" + (f"   ({extra})" if extra else ""))
    if a.apply:
        apply(repo, acts, a.scope)
        print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
