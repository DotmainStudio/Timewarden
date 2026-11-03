"""Job execution: planning, implementation (task by task), review, park/cancel/pause. The dispatcher, not agents, writes state."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from . import backlog, lifecycle, policy as pol, runner, streamparse
from . import changes as ch
from .store import Store

PAUSE_FILE = Path.home() / ".local" / "share" / "agents_memory_system" / "swarm" / "paused"
OUT_BASE = Path.home() / ".local" / "share" / "agents_memory_system" / "swarm" / "runs"


class Ctx:
    """Everything a job needs; injectable for tests (`mode='local'`, fake claude via SWARM_CLAUDE)."""

    def __init__(self, repo: Path, project_id: str, store: Store, mode: str = "docker", policy: dict | None = None,
                 out_base: Path = OUT_BASE, health_cmd: str = "bash scripts/health.sh"):
        self.repo, self.project_id, self.store, self.mode = repo.resolve(), project_id, store, mode
        self.policy = policy or pol.load()
        self.out_base, self.health_cmd = out_base, health_cmd
        from .gitops import Gh
        self.gh = Gh(self.repo)


def sh(cmd: list[str] | str, cwd: Path, timeout: int = 900) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def git(ctx_repo: Path, *args: str) -> tuple[int, str]:
    return sh(["git", *args], ctx_repo)


# -- worktrees ------------------------------------------------------------------
def ensure_worktree(ctx: Ctx, branch: str, base: str | None = None) -> Path:
    wt = ctx.repo.parent / f".swarm-worktrees" / f"{ctx.repo.name}-{branch.replace('/', '-')}"
    if wt.exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    base = base or main_branch(ctx.repo)
    rc, out = git(ctx.repo, "worktree", "add", "-b", branch, str(wt), base)
    if rc != 0:
        rc, out = git(ctx.repo, "worktree", "add", str(wt), branch)
        if rc != 0:
            raise RuntimeError(f"cannot create worktree: {out.strip()[-200:]}")
    return wt


def main_branch(repo: Path) -> str:
    rc, out = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[1]
    for b in ("main", "master"):
        if git(repo, "rev-parse", "--verify", b)[0] == 0:
            return b
    return "main"


def worktree_path(repo: Path, branch: str) -> Path:
    return repo.parent / ".swarm-worktrees" / f"{repo.name}-{branch.replace('/', '-')}"


def change_view(repo: Path, change_id: str) -> ch.Change:
    """Task progress lives in the change branch's worktree while the change is in flight; prefer it over the main checkout."""
    wt = worktree_path(repo, f"change/{change_id}") / "openspec" / "changes" / change_id
    return ch.load(wt if (wt / "tasks.md").exists() else repo / "openspec" / "changes" / change_id)


def paused() -> bool:
    return PAUSE_FILE.exists()


# -- one claude invocation ----------------------------------------------------------
def mark_recalls_used(events: list[dict], final_text: str) -> dict:
    """A recall counts as 'used' if the agent said so explicitly, or one of its returned sources/hash shows up in the final answer."""
    explicit = {e.get("query_hash") for e in events if e.get("type") == "recall_used"}
    used = {}
    for e in events:
        if e.get("type") == "recall" and not e.get("rejected"):
            used[e["query_hash"]] = (e["query_hash"] in explicit) or any(src in (final_text or "") for src in e.get("sources", []))
    return used


def ingest_events(ctx: Ctx, run_id: int, out_dir: Path, final_text: str = "") -> int:
    f = out_dir / "events.jsonl"
    n = 0
    if not f.exists():
        return 0
    parsed = []
    for line in f.read_text().splitlines():
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    used = mark_recalls_used(parsed, final_text)
    for e in parsed:
        if e.get("type") == "recall":
            ctx.store.recall(run_id, ctx.project_id, e.get("dataset", ""), e.get("query_hash", ""), int(e.get("results", 0)),
                             None if e.get("rejected") else used.get(e.get("query_hash")), bool(e.get("rejected")))
        if e.get("type") == "recall_used":
            continue
        ctx.store.event(ctx.project_id, e.pop("type", "event"), run_id, role=e.pop("role", None), tool=e.get("tool"),
                        ok=e.get("ok"), detail={k: v for k, v in e.items() if k not in ("ts", "tool", "ok")})
        n += 1
    return n


def execute(ctx: Ctx, kind: str, role: str, prompt: str, worktree: Path, change_id: str | None = None, task_id: str | None = None,
            branch: str = "", write_root: str | None = None, model_override: str | None = None, mode_override: str | None = None) -> dict:
    """Creates a run row, enforces limits, runs claude, stores figures and events. Returns {run_id, summary, state}."""
    if paused():
        raise RuntimeError("the swarm is paused (`swarm resume`)")
    if role != "gitops" and ctx.store.running_count() >= int(ctx.policy["limits"]["max_concurrent_jobs"]):
        raise RuntimeError("concurrency cap reached; retry when a job finishes")
    r = ctx.policy["roles"][role]
    lim = pol.limits_for(ctx.policy, role)
    model = model_override or r["model"]
    run_id = ctx.store.create_run(ctx.project_id, kind, role, change_id, task_id, model, r.get("effort", ""), "headless", branch, str(worktree), ctx.policy["_hash"])
    out_dir = ctx.out_base / ctx.project_id / str(run_id)
    job = runner.Job(role, prompt, worktree, out_dir, model, r.get("effort", ""), lim["max_turns"], lim["timeout_s"], list(r["tools"]),
                     readonly=r.get("writes") is False, write_root=write_root, name=f"swarm-{ctx.project_id}-{run_id}")
    mode = mode_override or ctx.mode          # the git agent always runs on the host (git/gh credentials never enter containers)
    auth = "subscription-token" if mode == "docker" else "host-login"
    ctx.store.update_run(run_id, state="running", auth_kind=auth)
    ctx.store.event(ctx.project_id, "auth_check", run_id, role, ok=True, detail={"credential": auth, "api_key_present": False})
    if change_id and task_id:
        ctx.store.assign_task(ctx.project_id, change_id, task_id, run_id, role)
    try:
        res = runner.run(job, mode)
    except runner.CredentialError as e:
        ctx.store.update_run(run_id, state="failed", summary=str(e)[:300])
        ctx.store.event(ctx.project_id, "credential_refused", run_id, role, ok=False, detail={"reason": str(e)[:200]})
        raise
    s = streamparse.parse_lines(res.stream_path.read_text().splitlines()) if res.stream_path.exists() else streamparse.RunSummary()
    state = "timeout" if res.timed_out else ("succeeded" if (res.returncode == 0 and s.has_result and not s.is_error) else "failed")
    ctx.store.update_run(run_id, state=state, session_id=s.session_id, turns=s.turns, input_tokens=s.input_tokens, output_tokens=s.output_tokens,
                         cache_read_tokens=s.cache_read_tokens, cache_creation_tokens=s.cache_creation_tokens,
                         cost_usd="" if s.cost_usd is None else s.cost_usd, context_end=s.context_end,
                         quota_utilization="" if s.quota_utilization is None else s.quota_utilization,
                         model=s.main_model or model, summary=(s.result_text or "")[:600])
    ingest_events(ctx, run_id, out_dir, s.result_text)
    for name, n in s.tool_calls.items():
        ctx.store.event(ctx.project_id, "tool_use", run_id, role, tool=name, detail={"count": n})
    if s.subagent_starts:
        ctx.store.event(ctx.project_id, "subagent_start", run_id, role, detail={"count": s.subagent_starts})
    if state == "timeout" and change_id:
        _save_progress(worktree, change_id, task_id, "timeout")
    ctx.store.assign_task(ctx.project_id, change_id, task_id, None, None) if change_id and task_id else None
    return {"run_id": run_id, "summary": s, "state": state, "out_dir": out_dir}


def _save_progress(worktree: Path, change_id: str, task_id: str | None, why: str) -> None:
    p = worktree / "progress" / "current.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"# Current\n\nStopped ({why}) while working on {change_id} task {task_id}. Resume from the next unchecked task.\n")


# -- planning ----------------------------------------------------------------------------
PLAN_PROMPT = """You are the planning leader. Idea: {idea}

Create the OpenSpec change `{cid}` under openspec/changes/{cid}/ with proposal.md, specs/<capability>/spec.md (ADDED Requirements, each with #### Scenario: WHEN/THEN), design.md and tasks.md (each task ends with "(verification: ...)", prefer a backticked command). 
First explore the repository and read the project briefing/docs; query memory only if the corpus is large or the question crosses documents. 
If an ambiguity would change scope, behavior or acceptance criteria, write it under "Open questions" in proposal.md and STOP instead of guessing. 
You may write ONLY inside openspec/changes/{cid}/. Do not write product code. Run `openspec validate {cid} --strict` when done."""


def plan(ctx: Ctx, idea: str, change_id: str | None = None) -> dict:
    cid = change_id or ch.slug(idea)[:48]
    if not ch.valid_change_id(cid):
        raise lifecycle.GateError(f"invalid change id {cid!r}", "invalid")
    branch = f"spec/{cid}"
    wt = ensure_worktree(ctx, branch)
    res = execute(ctx, "plan", "leader", PLAN_PROMPT.format(idea=idea, cid=cid), wt, cid, None, branch, write_root=f"openspec/changes/{cid}")
    stray = changed_outside(ctx, wt, f"openspec/changes/{cid}/")
    if stray:
        ctx.store.event(ctx.project_id, "plan_scope_violation", res["run_id"], "leader", ok=False, detail={"files": stray[:10]})
        ctx.store.update_run(res["run_id"], state="failed", summary="planning wrote outside the change directory")
        res["state"], res["stray"] = "failed", stray
        return res
    res["change_id"], res["worktree"] = cid, wt
    d = wt / "openspec" / "changes" / cid
    missing = ch.is_complete_plan(d)
    questions = open_questions(d)
    if res["state"] == "succeeded" and (missing or questions):
        res["state"], res["missing"], res["questions"] = "needs_input", missing, questions
        ctx.store.event(ctx.project_id, "plan_needs_input", res["run_id"], "leader", ok=False, detail={"missing": missing, "open_questions": len(questions)})
    return res


def open_questions(change_dir: Path) -> list[str]:
    """Text of the 'Open questions' section of proposal.md (the planner stops there instead of guessing)."""
    p = change_dir / "proposal.md"
    if not p.exists():
        return []
    m = re.search(r"^## Open questions\s*\n(.*?)(?=^## |\Z)", p.read_text(encoding="utf-8"), flags=re.M | re.S)
    if not m:
        return []
    body = m.group(1).strip()
    if re.match(r"(?i)^[\s*_>-]*(none|n/?a|no open questions|ninguna|ning[uú]n[ao]?|no hay|sin preguntas)\b", body):
        return []                                    # "None" / "Ninguna" is an answer, not a question
    return [q.strip() for q in re.split(r"^\s*\d+\.\s+", body, flags=re.M) if q.strip()][:10]


def changed_outside(ctx: Ctx, wt: Path, prefix: str) -> list[str]:
    base = main_branch(ctx.repo)
    rc, out = git(wt, "status", "--porcelain", "--untracked-files=all")
    files = [l[3:].strip() for l in out.splitlines()]
    rc2, out2 = git(wt, "diff", "--name-only", f"{base}...HEAD")
    files += [l.strip() for l in out2.splitlines() if l.strip()]
    return sorted({f for f in files if f and not f.startswith(prefix)})


# -- implementation ------------------------------------------------------------------------
IMPL_PROMPT = """Implement ONLY task {tid} of change `{cid}`: {title}
Verification required: {verif}
Read openspec/changes/{cid}/ (proposal, design, specs) for context. Follow the repo's AGENTS.md. Do not tick checkboxes, do not commit, do not push.
When finished, run `bash scripts/health.sh` and report what you did in at most 5 lines. Write long details to progress/current.md, not to the reply."""


def implement(ctx: Ctx, change_id: str, max_tasks: int | None = None) -> dict:
    c = lifecycle.require_approved(ctx.store, ctx.project_id, ctx.repo, change_id)   # THE GATE
    from . import gitops
    pre = gitops.preflight(ctx, change_id)                          # git agent BEFORE the first task
    if not pre.ok:
        raise lifecycle.GateError("git preflight blocked: " + "; ".join(pre.blocking), "git_blocked")
    branch = f"change/{change_id}"
    wt = ensure_worktree(ctx, branch)
    done_now, last = 0, None
    while True:
        c = ch.load(wt / "openspec" / "changes" / change_id)        # tasks of the worktree (progress lives in the branch)
        t = c.next_task()
        if not t or (max_tasks is not None and done_now >= max_tasks):
            break
        last = run_task(ctx, c, t, wt, branch)
        if not last["ok"]:
            break
        done_now += 1
        post = gitops.postflight(ctx, change_id, t.task_id)        # git agent AFTER every task
        if not post.ok:
            ctx.store.event(ctx.project_id, "needs_attention", None, "gitops", ok=False, detail={"task": t.task_id, "git": post.blocking})
            last["git_blocked"] = post.blocking
            break
    return {"change": change_id, "tasks_done": done_now, "last": last, "worktree": wt, "complete": ch.load(wt / "openspec" / "changes" / change_id).complete}


def run_task(ctx: Ctx, c: ch.Change, t: ch.Task, wt: Path, branch: str) -> dict:
    failed_reviews = ctx.store.failed_verdicts(ctx.project_id, c.change_id)
    model = pol.model_for(ctx.policy, "implementer", failed_reviews)
    prompt = IMPL_PROMPT.format(tid=t.task_id, cid=c.change_id, title=t.title, verif=t.verification or "health script must pass")
    res = execute(ctx, "implement", "implementer", prompt, wt, c.change_id, t.task_id, branch, model_override=model)
    ok, tail = False, ""
    if res["state"] == "succeeded":
        ok, tail = verify_task(ctx, wt, t, res["run_id"], c.change_id)
    if ok:
        tick(wt / "openspec" / "changes" / c.change_id / "tasks.md", t.task_id)
        commit(wt, f"feat({c.change_id}): task {t.task_id} {t.title[:60]}")
    else:
        ctx.store.update_run(res["run_id"], state="failed" if res["state"] == "succeeded" else res["state"], summary=f"verification failed: {tail[-200:]}" if res["state"] == "succeeded" else None)
        ctx.store.event(ctx.project_id, "needs_attention", res["run_id"], "implementer", ok=False, detail={"task": t.task_id})
    res["ok"] = ok
    return res


def verify_task(ctx: Ctx, wt: Path, t: ch.Task, run_id: int, change_id: str) -> tuple[bool, str]:
    """A task is ticked only if the health script passes AND (when stated) its backticked verification command passes."""
    rc, out = sh(ctx.health_cmd, wt)
    ctx.store.health(run_id, ctx.project_id, change_id, rc == 0, out)
    if rc != 0:
        return False, out
    if t.command:
        rc, out = sh(t.command, wt)
        ctx.store.event(ctx.project_id, "task_verification", run_id, "implementer", ok=rc == 0, detail={"task": t.task_id, "command": t.command})
        if rc != 0:
            return False, out
    return True, out


def tick(tasks_md: Path, task_id: str) -> None:
    text = tasks_md.read_text(encoding="utf-8")
    new = re.sub(rf"^- \[ \] ({re.escape(task_id)} )", r"- [x] \1", text, count=1, flags=re.M)
    tasks_md.write_text(new, encoding="utf-8")


def commit(wt: Path, msg: str) -> None:
    git(wt, "add", "-A")
    git(wt, "-c", "user.name=swarm", "-c", "user.email=swarm@localhost", "commit", "-q", "-m", msg, "--allow-empty")


# -- review ---------------------------------------------------------------------------------
REVIEW_PROMPT = """You are the Reviewer for change `{cid}`. Verify the implementation against EVERY scenario below and against the health script.
Scenarios:
{scenarios}
For each scenario find a test or evidence (file:line or command output). You are read-only. 
Reply with ONLY one JSON object: {{"scenarios":[{{"id":"<id>","status":"pass|fail","evidence":"<file:line or command>"}}],"findings":["..."]}}"""


def extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge(change: ch.Change, reply: dict | None, health_ok: bool) -> tuple[bool, list, list]:
    """Script-enforced verdict: every scenario needs a passing entry WITH evidence; health must pass."""
    findings, rows = [], []
    got = {s.get("id"): s for s in (reply or {}).get("scenarios", []) if isinstance(s, dict)}
    for s in change.scenarios:
        e = got.get(s.sid)
        if not e or not str(e.get("evidence", "")).strip():
            rows.append({"id": s.sid, "status": "fail", "evidence": ""})
            findings.append(f"scenario without test or evidence: {s.sid}")
        else:
            rows.append({"id": s.sid, "status": "pass" if e.get("status") == "pass" else "fail", "evidence": str(e["evidence"])[:200]})
            if e.get("status") != "pass":
                findings.append(f"scenario failing: {s.sid}")
    if not health_ok:
        findings.append("health script failed")
    findings += [str(f)[:200] for f in (reply or {}).get("findings", [])[:10]]
    return (not any(r["status"] != "pass" for r in rows) and health_ok and reply is not None), rows, findings


def review(ctx: Ctx, change_id: str, finalize: bool = True) -> dict:
    c = lifecycle.require_approved(ctx.store, ctx.project_id, ctx.repo, change_id)
    park = int(ctx.policy["limits"]["park_after_failed_reviews"])
    if ctx.store.failed_verdicts(ctx.project_id, change_id) >= park:
        raise lifecycle.GateError(f"change '{change_id}' is parked after {park} failed reviews; the user must intervene", "parked")
    wt = ensure_worktree(ctx, f"change/{change_id}")
    c = ch.load(wt / "openspec" / "changes" / change_id)
    scen = "\n".join(f"- {s.sid}: {s.requirement} / {s.name}" for s in c.scenarios)
    res = execute(ctx, "review", "reviewer", REVIEW_PROMPT.format(cid=change_id, scenarios=scen), wt, change_id, None, f"change/{change_id}")
    rc, out = sh(ctx.health_cmd, wt)
    ctx.store.health(res["run_id"], ctx.project_id, change_id, rc == 0, out)
    reply = extract_json(res["summary"].result_text)
    passed, rows, findings = judge(c, reply, rc == 0)
    ctx.store.verdict(res["run_id"], ctx.project_id, change_id, passed, rows, findings)
    ctx.store.event(ctx.project_id, "verdict", res["run_id"], "reviewer", ok=passed, detail={"scenarios": len(rows), "failed": sum(r["status"] != "pass" for r in rows)})
    parked = (not passed) and ctx.store.failed_verdicts(ctx.project_id, change_id) >= park
    if parked:
        ctx.store.update_run(res["run_id"], state="parked", summary="parked after repeated review failures")
        ctx.store.event(ctx.project_id, "parked", res["run_id"], "reviewer", ok=False, detail={"change": change_id})
    out = {"passed": passed, "scenarios": rows, "findings": findings, "parked": parked, "run_id": res["run_id"]}
    if passed and finalize:
        from . import gitops
        out["git"] = gitops.finalize(ctx, change_id).as_dict()      # git agent when the change passes review
    return out


# -- exploration (read-only, with proof) ----------------------------------------------------------
EXPLORE_PROMPT = """You are the explorer. Answer this question about the repository: {q}
Read the code and docs (read-only). Cite file paths and lines. Reply in at most 2000 characters."""


def tree_state(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all")[1] + git(repo, "rev-parse", "HEAD")[1]


def explore(ctx: Ctx, question: str) -> dict:
    """Runs the read-only explorer on the repository and PROVES the working tree is unchanged afterwards."""
    before = tree_state(ctx.repo)
    res = execute(ctx, "explore", "explorer", EXPLORE_PROMPT.format(q=question), ctx.repo, None, None, "")
    clean = tree_state(ctx.repo) == before
    ctx.store.event(ctx.project_id, "readonly_check", res["run_id"], "explorer", ok=clean, detail={"tree_unchanged": clean})
    if not clean:
        ctx.store.update_run(res["run_id"], state="failed", summary="working tree changed during a read-only exploration")
        res["state"] = "failed"
    res["tree_unchanged"] = clean
    return res


# -- control ----------------------------------------------------------------------------------
def cancel(ctx: Ctx, run_id: int) -> str:
    r = ctx.store.run(run_id)
    if not r:
        raise KeyError(f"run {run_id} not found")
    if r["state"] not in ("queued", "running"):
        return f"run {run_id} is already {r['state']}"
    if ctx.mode == "docker":
        subprocess.run(["docker", "kill", f"swarm-{ctx.project_id}-{run_id}"], capture_output=True)
    ctx.store.update_run(run_id, state="cancelled")
    ctx.store.event(ctx.project_id, "cancelled", run_id, r["role"], ok=False)
    return f"run {run_id} cancelled; worktree kept at {r['worktree']}"


def pause(on: bool) -> None:
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if on:
        PAUSE_FILE.write_text(str(int(time.time())))
    elif PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
