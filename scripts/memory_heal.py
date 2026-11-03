#!/usr/bin/env python3
"""Self-healing for the memory stack. Free checks and repairs first; anything that spends Claude quota is capped.

Usage: memory_heal.py run [--dry-run] | status | config | add-repo <path>

What it does on each run (nothing here calls a model unless diagnose.enabled is set):
  1. Infrastructure (free): restart an unhealthy/stopped stack container, the panel or the observer (never `down -v`).
  2. Swarm (free): mark runs stuck "running" for hours as failed; close leftover team tmux sessions.
  3. Sync debt (spends tokens, CAPPED): re-index pending/changed documents of each configured repo with
     `sync_markdown.py --apply --max-docs N`, only within the daily budget, the quota threshold, the attempts per item,
     and only from the default branch with no uncommitted changes to tracked files (nothing unmerged is indexed).
  4. Report-only: documents in memory without a registry entry (never deleted automatically).
  5. Optional (off by default): a once-a-day read-only diagnosis with the lightest model for problems that persist.
Config: ~/.config/agents_memory_system/heal.yaml (env MEMORY_HEAL_CONFIG). State and log: ~/.local/share/agents_memory_system/heal/.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import miniyaml  # noqa: E402

HOME = Path.home()
CONFIG = Path(os.environ.get("MEMORY_HEAL_CONFIG", HOME / ".config" / "agents_memory_system" / "heal.yaml"))
HEAL_DIR = Path(os.environ.get("MEMORY_HEAL_DIR", HOME / ".local" / "share" / "agents_memory_system" / "heal"))

DEFAULTS = {
    "interval_minutes": 60,
    "repos": [],
    "budget": {"max_syncs_per_day": 2, "max_docs_per_sync": 8, "min_hours_between_syncs": 6, "max_attempts_per_item": 3,
              "quota_pause_at": 0.7, "max_restarts_per_day": 3},
    "stuck_run_hours": 3,
    "diagnose": {"enabled": False, "model": "haiku", "max_per_day": 1},
    "notify": True,
}
HARD_CAPS = {"max_syncs_per_day": 6, "max_docs_per_sync": 20, "max_attempts_per_item": 5, "max_restarts_per_day": 6}
STACK = {  # container name -> compose service
    "agents_memory_system-agents_postgres-1": "agents_postgres",
    "agents_memory_system-agents_cognee_api-1": "agents_cognee_api",
    "agents_memory_system-agents_cognee_mcp-1": "agents_cognee_mcp",
    "agents_memory_system-agents_otel_collector-1": "agents_otel_collector",
}
PANEL_CONTAINER = "management_memory-mm_app-1"
PLAN_RE = re.compile(r"project=(?P<pid>[^:\s]+): (?P<body>.*)")


# ------------------------------------------------------------------ config
def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def dump_yaml(d: dict, indent: int = 0) -> str:
    """Minimal YAML writer (dicts, lists, scalars): readable by PyYAML and by the stdlib fallback parser."""
    pad, out = "  " * indent, []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:\n" + dump_yaml(v, indent + 1))
        elif isinstance(v, list):
            out.append(f"{pad}{k}:" + ("" if v else " []") + "\n" + "".join(f"{pad}  - {json.dumps(x) if isinstance(x, str) else x}\n" for x in v))
        else:
            out.append(f"{pad}{k}: {str(v).lower() if isinstance(v, bool) else v}\n")
    return "".join(out)


def load_config(path: Path = CONFIG) -> dict:
    user = {}
    if path.exists():
        user = miniyaml.load(path.read_text(encoding="utf-8")) or {}
    cfg = merge(DEFAULTS, user if isinstance(user, dict) else {})
    for k, cap in HARD_CAPS.items():          # budgets can be lowered by the user, never raised past the hard caps
        cfg["budget"][k] = max(0, min(int(cfg["budget"][k]), cap))
    cfg["budget"]["quota_pause_at"] = max(0.0, min(float(cfg["budget"]["quota_pause_at"]), 0.95))
    cfg["budget"]["min_hours_between_syncs"] = max(1.0, float(cfg["budget"]["min_hours_between_syncs"]))
    cfg["interval_minutes"] = max(15, int(cfg["interval_minutes"]))
    cfg["repos"] = [str(r) for r in (cfg.get("repos") or [])]
    return cfg


# ------------------------------------------------------------------ state
class State:
    def __init__(self, path: Path, now=time.time):
        self.path, self.now = path, now
        self.data = {"day": "", "syncs_today": 0, "last_sync_ts": 0, "restarts": {}, "attempts": {}, "alerts": {}, "diagnoses_today": 0}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text()))
            except json.JSONDecodeError:
                pass
        self.roll_day()

    def today(self) -> str:
        return dt.datetime.fromtimestamp(self.now()).strftime("%Y-%m-%d")

    def roll_day(self) -> None:
        if self.data["day"] != self.today():
            self.data.update(day=self.today(), syncs_today=0, restarts={}, attempts={}, alerts={}, diagnoses_today=0)

    def bump(self, bucket: str, key: str) -> int:
        self.data[bucket][key] = self.data[bucket].get(key, 0) + 1
        return self.data[bucket][key]

    def count(self, bucket: str, key: str) -> int:
        return int(self.data[bucket].get(key, 0))

    def first_alert(self, key: str) -> bool:
        if key in self.data["alerts"]:
            return False
        self.data["alerts"][key] = self.now()
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)


# ------------------------------------------------------------------ healer
def run_cmd(argv: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError as e:
        return 127, str(e)


class Healer:
    def __init__(self, cfg: dict, state: State, sh=run_cmd, dry_run: bool = False, log=None):
        self.cfg, self.state, self.sh, self.dry, self.events = cfg, state, sh, dry_run, []
        self.log = log or (lambda e: None)

    # -- reporting
    def event(self, kind: str, **kw) -> None:
        e = {"ts": int(self.state.now()), "event": kind, **kw}
        self.events.append(e)
        self.log(e)

    def alert(self, key: str, text: str) -> None:
        """One notification per problem per day (dedup); always in the log."""
        if self.state.first_alert(key):
            self.event("alert", key=key, text=text)
            if self.cfg["notify"] and not self.dry and sys.platform == "darwin":
                self.sh(["osascript", "-e", f'display notification "{text[:180]}" with title "Memory self-heal"'])

    # -- quota
    def quota(self) -> float | None:
        rc, out = self.sh(["docker", "exec", "-i", "agents_memory_system-agents_postgres-1", "psql", "-X", "-q", "-t", "-A", "-U", "swarm_writer", "-d", "agents_memory",
                           "-c", "select coalesce(max(quota_utilization),-1) from swarm.runs where created_at > now() - interval '5 hours'"])
        try:
            v = float(out.strip().splitlines()[-1])
            return None if rc != 0 or v < 0 else v
        except (ValueError, IndexError):
            return None

    def quota_ok(self) -> tuple[bool, float | None]:
        q = self.quota()
        return (q is None or q < self.cfg["budget"]["quota_pause_at"]), q

    # -- 1. infrastructure (free)
    def check_infra(self) -> None:
        rc, out = self.sh(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"])
        if rc != 0:
            self.alert("docker-down", "Docker is not responding: start Docker Desktop")
            return
        status = dict(l.split("|", 1) for l in out.splitlines() if "|" in l)
        bad = []
        for name, service in STACK.items():
            st = status.get(name, "missing")
            if not st.startswith("Up") or "unhealthy" in st:
                bad.append((name, service, ["scripts/dc.sh", "up", "-d", service]))
        st = status.get(PANEL_CONTAINER, "missing")
        if not st.startswith("Up") or "unhealthy" in st:
            bad.append((PANEL_CONTAINER, "panel", ["docker", "compose", "-f", str(ROOT / "panel" / "compose.yaml"), "up", "-d", "mm_app"]))
        for name, service, cmd in bad:
            n = self.state.bump("restarts", name)
            if n > self.cfg["budget"]["max_restarts_per_day"]:
                self.alert(f"restart-loop:{name}", f"{service} keeps failing; stopped restarting it today")
                continue
            self.event("restart", component=service, dry=self.dry)
            if not self.dry:
                self.sh(([str(ROOT / cmd[0])] + cmd[1:]) if cmd[0].startswith("scripts/") else cmd, timeout=300)
        rc, _ = self.sh(["curl", "-s", "-m", "4", "http://127.0.0.1:8017/health"])
        if rc != 0:
            n = self.state.bump("restarts", "observer")
            if n > self.cfg["budget"]["max_restarts_per_day"]:
                self.alert("restart-loop:observer", "the observer keeps failing; stopped restarting it today")
            else:
                self.event("restart", component="observer", dry=self.dry)
                if not self.dry:
                    self.sh([str(ROOT / "scripts" / "observer.sh"), "start"], timeout=120)

    # -- 2. swarm (free)
    def check_swarm(self) -> None:
        hours = int(self.cfg["stuck_run_hours"])
        sql = (f"update swarm.runs set state='failed', ended_at=now(), summary='marked failed by memory_heal (no activity for {hours} h)' "
               f"where state in ('running','queued') and coalesce(started_at, created_at) < now() - interval '{hours} hours' returning id")
        if not self.dry:
            rc, out = self.sh(["docker", "exec", "-i", "agents_memory_system-agents_postgres-1", "psql", "-X", "-q", "-t", "-A", "-U", "swarm_writer", "-d", "agents_memory", "-c", sql])
            ids = [l.strip() for l in out.splitlines() if l.strip().isdigit()] if rc == 0 else []
            if ids:
                self.event("stuck_runs_closed", runs=ids)
        rc, out = self.sh(["tmux", "list-sessions", "-F", "#{session_name} #{session_created}"])
        if rc == 0:
            for line in out.splitlines():
                name, _, created = line.partition(" ")
                if name.startswith("swarm-team-") and created.isdigit() and self.state.now() - int(created) > hours * 3600:
                    self.event("team_session_closed", session=name, dry=self.dry)
                    if not self.dry:
                        self.sh(["tmux", "kill-session", "-t", name])

    # -- 3. sync debt (spends tokens, capped)
    def default_branch(self, repo: Path) -> str:
        rc, out = self.sh(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo)
        if rc == 0 and "/" in out.strip():
            return out.strip().split("/", 1)[1]
        for b in ("main", "master"):
            if self.sh(["git", "rev-parse", "--verify", b], cwd=repo)[0] == 0:
                return b
        return "main"

    def pending(self, repo: Path) -> tuple[str, dict, list[str]]:
        rc, out = self.sh([sys.executable, "-I", str(ROOT / "scripts" / "sync_markdown.py"), str(repo)], timeout=300)
        pid, counts, items = repo.name, {}, []
        for line in out.splitlines():
            m = PLAN_RE.match(line)
            if m:
                pid = m.group("pid")
                counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", m.group("body"))}
            m2 = re.match(r"\s+\[(new|changed|retry|deleted)\] (.+)", line)
            if m2:
                items.append(m2.group(2).strip())
        return pid, counts, items

    def check_sync(self, repo_path: str) -> None:
        repo, b = Path(repo_path).expanduser(), self.cfg["budget"]
        if not (repo / ".agent-memory" / "project.yaml").exists():
            self.event("skip", repo=repo.name, reason="no .agent-memory/project.yaml")
            return
        pid, counts, items = self.pending(repo)
        debt = counts.get("new", 0) + counts.get("changed", 0) + counts.get("retry", 0)
        if debt == 0 and not counts.get("deleted"):
            self.event("sync_ok", project=pid)
            return
        reason = self.sync_blockers(repo, pid, items)
        if reason:
            self.event("sync_skipped", project=pid, pending=debt, reason=reason)
            if "attempts" in reason or "uncommitted" in reason:
                self.alert(f"sync-blocked:{pid}", f"{pid}: {debt} document(s) pending, not syncing: {reason}")
            return
        self.event("sync_start", project=pid, pending=debt, max_docs=b["max_docs_per_sync"], dry=self.dry)
        if self.dry:
            return
        self.state.data["syncs_today"] += 1
        self.state.data["last_sync_ts"] = self.state.now()
        rc, out = self.sh([sys.executable, "-I", str(ROOT / "scripts" / "sync_markdown.py"), str(repo), "--apply", "--max-docs", str(b["max_docs_per_sync"])], timeout=3600)
        done = set(re.findall(r"^\s+indexed\s+(\S+)", out, flags=re.M))
        for it in items[: b["max_docs_per_sync"]]:
            if it not in done:
                self.state.bump("attempts", f"{pid}:{it}")
        self.event("sync_done", project=pid, indexed=len(done), rc=rc, errors=len(re.findall(r"ERROR|UNVERIFIED|crashed|FAILED", out)))
        self.save_after_sync(pid, items, done)

    def save_after_sync(self, pid: str, items: list[str], done: set) -> None:
        left = [i for i in items if i not in done]
        if left and all(self.state.count("attempts", f"{pid}:{i}") >= self.cfg["budget"]["max_attempts_per_item"] for i in left):
            self.alert(f"persistent:{pid}", f"{pid}: {len(left)} document(s) keep failing to index; see the heal log")

    def sync_blockers(self, repo: Path, pid: str, items: list[str]) -> str:
        b, s = self.cfg["budget"], self.state
        if s.data["syncs_today"] >= b["max_syncs_per_day"]:
            return f"daily sync budget used ({s.data['syncs_today']}/{b['max_syncs_per_day']})"
        since = (s.now() - s.data["last_sync_ts"]) / 3600
        if s.data["last_sync_ts"] and since < b["min_hours_between_syncs"]:
            return f"last sync {since:.1f} h ago (minimum {b['min_hours_between_syncs']} h)"
        ok, q = self.quota_ok()
        if not ok:
            return f"subscription quota at {q:.0%} (pause at {b['quota_pause_at']:.0%})"
        cur = self.sh(["git", "branch", "--show-current"], cwd=repo)[1].strip()
        base = self.default_branch(repo)
        if cur != base:
            return f"checkout is on '{cur}', not '{base}' (only merged state is indexed)"
        if self.sh(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo)[1].strip():
            return "uncommitted changes to tracked files (commit or discard them: only merged state is indexed)"
        if items and all(s.count("attempts", f"{pid}:{i}") >= b["max_attempts_per_item"] for i in items):
            return f"every pending item reached {b['max_attempts_per_item']} attempts today"
        if self.sh(["curl", "-s", "-m", "4", "http://127.0.0.1:8017/health"])[0] != 0:
            return "observer is not responding"
        return ""

    # -- 4. report only
    def check_findings(self) -> None:
        rc, out = self.sh(["curl", "-s", "-m", "10", "-H", "Host: 127.0.0.1", "http://127.0.0.1:45876/api/kb"])
        try:
            kb = json.loads(out)
        except json.JSONDecodeError:
            return
        for d in kb.get("datasets", []):
            for f in d.get("flags", []):
                if f.get("code") == "orphans":
                    self.alert(f"orphans:{d.get('name')}", f"{d.get('name')}: {f.get('text')} (not deleted automatically)")

    # -- 5. optional diagnosis (off by default)
    def maybe_diagnose(self) -> None:
        dg = self.cfg["diagnose"]
        if not dg["enabled"] or self.dry:
            return
        persistent = [k for k in self.state.data["alerts"] if k.startswith(("persistent:", "restart-loop:"))]
        if not persistent or self.state.data["diagnoses_today"] >= int(dg["max_per_day"]):
            return
        ok, _ = self.quota_ok()
        if not ok:
            return
        logf = HEAL_DIR / "heal.log"
        tail = logf.read_text()[-3000:] if logf.exists() else ""
        prompt = ("You are diagnosing a local memory stack (Cognee + Postgres + an observer). Read-only. Problems: "
                  + ", ".join(persistent) + ". Recent heal log:\n" + tail + "\nIn at most 12 lines: the most likely cause and the exact command a human should run. Do not suggest deleting data.")
        out_file = HEAL_DIR / f"diagnosis-{self.state.today()}.md"
        rc, out = self.sh(["claude", "-p", prompt, "--model", dg["model"], "--max-turns", "6", "--allowedTools", "Read,Grep", "--setting-sources", "",
                           "--permission-mode", "default", "--no-session-persistence"], cwd=ROOT, timeout=300)
        self.state.data["diagnoses_today"] += 1
        if rc == 0:
            out_file.write_text(out)
            self.event("diagnosis_written", file=str(out_file))
            self.alert(f"diagnosis:{self.state.today()}", f"Diagnosis written to {out_file}")

    # -- all
    def run(self) -> list[dict]:
        self.check_infra()
        self.check_swarm()
        for r in self.cfg["repos"]:
            self.check_sync(r)
        self.check_findings()
        self.maybe_diagnose()
        if not self.dry:
            self.state.save()
        return self.events


# ------------------------------------------------------------------ cli
def make_logger():
    HEAL_DIR.mkdir(parents=True, exist_ok=True)
    f = HEAL_DIR / "heal.log"
    if f.exists() and f.stat().st_size > 1_000_000:
        f.rename(f.with_suffix(".log.1"))

    def log(e):
        with f.open("a") as fh:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return log


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "status"
    if cmd == "config":
        print(json.dumps(load_config(), indent=2)); return 0
    if cmd == "add-repo" and len(a) > 1:
        p = Path(a[1]).expanduser().resolve()
        if not (p / ".agent-memory" / "project.yaml").exists():
            print(f"{p} has no .agent-memory/project.yaml", file=sys.stderr); return 2
        cfg_user = (miniyaml.load(CONFIG.read_text()) or {}) if CONFIG.exists() else {}
        repos = [str(r) for r in (cfg_user.get("repos") or [])]
        if str(p) not in repos:
            repos.append(str(p))
        cfg_user["repos"] = repos
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text("# memory_heal config (budgets can be lowered, never raised past the hard caps)\n" + dump_yaml(cfg_user))
        print(f"watching {p}"); return 0
    if cmd == "status":
        st = State(HEAL_DIR / "state.json")
        print(json.dumps({"day": st.data["day"], "syncs_today": st.data["syncs_today"], "restarts": st.data["restarts"], "alerts": list(st.data["alerts"]),
                          "config": str(CONFIG), "repos": load_config()["repos"]}, indent=2))
        return 0
    if cmd == "run":
        dry = "--dry-run" in a
        cfg = load_config()
        h = Healer(cfg, State(HEAL_DIR / "state.json"), dry_run=dry, log=None if dry else make_logger())
        events = h.run()
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        if not events:
            print("all clear")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
