"""Team mode: an interactive Claude Code session (agent teams enabled) inside a tmux session, on explicit request only.

Agent teams are experimental and are not spawned in `-p` mode, so team jobs run interactively. At most `team.max_teammates`
(5) teammates. Events from the swarm hooks (teammate idle, team task completed, guard blocks) are ingested like any other run.
Runs on the host (the user's login); the same guard rules and `--setting-sources ""` isolation apply.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from . import jobs, runner

TEAM_FLAG = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


def tmux(*args: str) -> tuple[int, str]:
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def session_alive(name: str) -> bool:
    return tmux("has-session", "-t", name)[0] == 0


def clamp(n: int, cap: int) -> int:
    return max(1, min(int(n), cap))


def build_prompt(task: str, teammates: int) -> str:
    return (f"Create an agent team with exactly {teammates} teammate(s) for this task, give each a distinct focus, wait for their reports, "
            f"then summarise in at most 8 lines and stop. Task: {task}\nRules: teammates are read-only unless the task says otherwise; "
            f"never push, merge or use force; do not print credentials.")


def start(ctx: jobs.Ctx, task: str, teammates: int = 2, worktree: Path | None = None, model: str | None = None) -> dict:
    if not __import__("shutil").which("tmux"):
        raise RuntimeError("tmux is required for team mode (brew install tmux)")
    cap = int((ctx.policy.get("team") or {}).get("max_teammates", 5))
    n = clamp(teammates, cap)
    wt = (worktree or ctx.repo).resolve()
    r = ctx.policy["roles"]["leader"]
    run_id = ctx.store.create_run(ctx.project_id, "team", "leader", None, None, model or r["model"], r.get("effort", ""), "interactive", "", str(wt), ctx.policy["_hash"])
    out_dir = ctx.out_base / ctx.project_id / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    runner.write_local_settings()
    claude = os.environ.get("SWARM_CLAUDE", "claude")
    argv = [claude, "--model", model or r["model"], "--setting-sources", "", "--settings", str(runner.ROOT / "runner" / "settings.local.json"),
            "--permission-mode", "acceptEdits", "--allowedTools", ",".join(r["tools"]), "--teammate-mode", "in-process", build_prompt(task, n)]
    env = {"SWARM_OUT": str(out_dir), "SWARM_ROLE": "leader", "SWARM_READONLY": "0", TEAM_FLAG: "1"}
    name = f"swarm-team-{ctx.project_id}-{run_id}"[:60].replace(".", "-")
    cmd = "env " + " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items()) + " " + shlex.join(argv)
    rc, out = tmux("new-session", "-d", "-s", name, "-c", str(wt), "-x", "200", "-y", "50", cmd)
    if rc != 0:
        ctx.store.update_run(run_id, state="failed", summary=out.strip()[-200:])
        raise RuntimeError(f"tmux failed: {out.strip()[-160:]}")
    ctx.store.update_run(run_id, state="running", auth_kind="host-login")
    ctx.store.event(ctx.project_id, "team_started", run_id, "leader", ok=True, detail={"session": name, "teammates": n, "requested": teammates})
    return {"run_id": run_id, "session": name, "teammates": n, "out_dir": out_dir}


def autotrust(name: str, wait_s: float = 4.0) -> bool:
    """First start in a folder shows a trust dialog whose default is "No, exit": move to "Yes, I trust this folder" and confirm."""
    time.sleep(wait_s)
    pane = tmux("capture-pane", "-p", "-t", name)[1]
    low = pane.lower()
    if "trust this folder" not in low and "do you trust" not in low and "is this a project you created" not in low:
        return False
    if "❯ no" in low or "> no" in low:
        tmux("send-keys", "-t", name, "Down")
    tmux("send-keys", "-t", name, "Enter")
    return True


def finish(ctx: jobs.Ctx, run_id: int, name: str, out_dir: Path) -> dict:
    """Ingest events and close the run once the tmux session has ended; returns {done, state}."""
    if session_alive(name):
        return {"done": False}
    jobs.ingest_events(ctx, run_id, out_dir)
    txt = (out_dir / "events.jsonl").read_text() if (out_dir / "events.jsonl").exists() else ""
    n_idle = txt.count('"teammate_idle"')
    active = n_idle + txt.count('"team_task_completed"') > 0
    state = "succeeded" if active else "failed"          # a session that never ran a teammate is a failure, not a success
    ctx.store.update_run(run_id, state=state, summary=f"team session ended; teammate idle events: {n_idle}" + ("" if active else "; no teammate activity"))
    return {"done": True, "state": state, "teammate_idle_events": n_idle}


def lead_done(out_dir: Path) -> bool:
    """The lead finished its turn (Stop hook) after the team did some work (teammate idle / task completed events)."""
    f = out_dir / "events.jsonl"
    if not f.exists():
        return False
    txt = f.read_text()
    last_stop = txt.rfind('"session_stop"')
    work = max(txt.rfind('"teammate_idle"'), txt.rfind('"team_task_completed"'))
    return last_stop != -1 and work != -1 and last_stop > work


def wait(ctx: jobs.Ctx, run_id: int, name: str, out_dir: Path, timeout_s: int = 1800, poll: float = 5.0, grace: float = 8.0) -> dict:
    deadline = time.time() + timeout_s
    done_since = None
    while time.time() < deadline:
        r = finish(ctx, run_id, name, out_dir)
        if r["done"]:
            return r
        if lead_done(out_dir):                      # an interactive session never ends by itself: close it after a short grace
            done_since = done_since or time.time()
            if time.time() - done_since >= grace:
                tmux("send-keys", "-t", name, "/exit", "Enter")
                done_since = time.time() + 30
        else:
            done_since = None
        time.sleep(poll)
    tmux("kill-session", "-t", name)
    jobs.ingest_events(ctx, run_id, out_dir)
    ctx.store.update_run(run_id, state="timeout", summary="team session exceeded its time limit and was stopped")
    return {"done": True, "state": "timeout"}
