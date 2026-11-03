"""`swarm` command: propose | approve | backlog | status | implement | review | post-merge | cancel | pause | resume | sync-state | doctor."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import miniyaml  # noqa: E402

from . import backlog, changes as ch, jobs, lifecycle, pending, postmerge, runner
from .pg import Pg, apply_schema, admin
from .store import Store


def project_of(repo: Path) -> str:
    f = repo / ".agent-memory" / "project.yaml"
    if f.exists():
        d = miniyaml.load(f.read_text()) or {}
        if d.get("project_id"):
            return str(d["project_id"])
    return repo.resolve().name        # fallback only; the harness installer always writes project.yaml


def sync_state(store: Store, repo: Path, pid: str, park: int = 2) -> dict[str, str]:
    store.upsert_project(pid, repo)
    active = {r["change_id"] for r in store.active_runs(pid) if r.get("change_id")}
    statuses = {}
    for c0 in ch.list_changes(repo):
        c = jobs.change_view(repo, c0.change_id)
        c.path = c0.path            # approval hash is computed on the main checkout's planning artifacts
        st = lifecycle.status_of(store, pid, c, park, c.change_id in active)
        a = store.active_approval(pid, c.change_id)
        store.sync_change(pid, c, st, ch.artifact_hash(c.path), a["artifact_hash"] if a else None)
        statuses[c.change_id] = st
    # changes that no longer exist as active directories were archived (merged and done): keep the board truthful
    ids = ",".join(f"'{k}'" for k in statuses) or "''"
    store.db.execute(f"update swarm.changes set status='done', updated_at=now() where project_id=:'p' and change_id not in ({ids}) and status <> 'done'", p=pid)
    return statuses


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swarm")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--mode", choices=("docker", "local"), default="docker", help="local = host login, for dev/tests only")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose"); p.add_argument("idea"); p.add_argument("--change")
    p = sub.add_parser("approve"); p.add_argument("change"); p.add_argument("--note", default="")
    sub.add_parser("backlog")
    sub.add_parser("status")
    p = sub.add_parser("implement"); p.add_argument("change"); p.add_argument("--max-tasks", type=int)
    p = sub.add_parser("review"); p.add_argument("change"); p.add_argument("--no-git", action="store_true", help="record the verdict without the git agent's finalize phase")
    p = sub.add_parser("explore"); p.add_argument("question")
    p = sub.add_parser("post-merge"); p.add_argument("change"); p.add_argument("--no-sync", action="store_true")
    p = sub.add_parser("cancel"); p.add_argument("run", type=int)
    sub.add_parser("pause"); sub.add_parser("resume")
    p = sub.add_parser("git", help="run a git-agent phase by hand"); p.add_argument("phase", choices=("preflight", "postflight", "finalize")); p.add_argument("change")
    p = sub.add_parser("team", help="interactive agent team in tmux (experimental, on request)"); p.add_argument("task"); p.add_argument("--teammates", type=int, default=2); p.add_argument("--worktree", type=Path); p.add_argument("--model"); p.add_argument("--timeout", type=int, default=1800); p.add_argument("--no-wait", action="store_true")
    p = sub.add_parser("token", help="store the subscription token (reads it from stdin, never prints it) or show its status"); p.add_argument("action", choices=("save", "status"))
    sub.add_parser("verify-docker", help="run one real job in the hardened container with the stored token and check credentials and leaks")
    sub.add_parser("sync-state")
    sub.add_parser("pending")
    sub.add_parser("doctor")
    sub.add_parser("init-db")
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    pid = project_of(repo)

    if a.cmd == "init-db":
        return init_db()
    if a.cmd in ("pause", "resume"):
        jobs.pause(a.cmd == "pause"); print("paused" if a.cmd == "pause" else "resumed"); return 0
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "token":
        from . import verify
        if a.action == "status":
            print(json.dumps(runner.token_file_status())); return 0
        try:
            print(json.dumps(verify.save_token(sys.stdin.read()))); return 0
        except ValueError as e:
            print(f"swarm: {e}", file=sys.stderr); return 2
    store = Store()
    ctx = jobs.Ctx(repo, pid, store, a.mode)
    try:
        if a.cmd == "propose":
            r = jobs.plan(ctx, a.idea, a.change)
            print(json.dumps({"state": r["state"], "run": r["run_id"], "change": r.get("change_id"), "stray": r.get("stray")}))
            if r["state"] == "needs_input":
                print("\nThe planner needs your answers before the spec is complete (re-run `swarm propose` with the answers in the idea):", file=sys.stderr)
                for q in r["questions"]:
                    print(f"  - {q[:300]}", file=sys.stderr)
                return 3
            return 0 if r["state"] == "succeeded" else 1
        if a.cmd == "approve":
            h = lifecycle.approve(store, pid, repo, a.change, a.note)
            sync_state(store, repo, pid); print(f"approved {a.change} (artifact hash {h[:12]})"); return 0
        if a.cmd == "backlog":
            st = sync_state(store, repo, pid); print(backlog.write(repo, backlog.build(repo, st))); return 0
        if a.cmd == "status":
            st = sync_state(store, repo, pid)
            for cid, s in st.items():
                print(f"{cid:40s} {s}")
            for r in store.active_runs(pid):
                print(f"  run {r['id']} {r['role']} {r['state']} change={r['change_id']} task={r['task_id']}")
            return 0
        if a.cmd == "implement":
            r = jobs.implement(ctx, a.change, a.max_tasks); sync_state(store, repo, pid)
            print(json.dumps({"tasks_done": r["tasks_done"], "complete": r["complete"]})); return 0 if r["tasks_done"] or r["complete"] else 1
        if a.cmd == "review":
            r = jobs.review(ctx, a.change, finalize=not a.no_git); sync_state(store, repo, pid)
            print(json.dumps({k: r[k] for k in ("passed", "findings", "parked", "git") if k in r})); return 0 if r["passed"] else 1
        if a.cmd == "explore":
            r = jobs.explore(ctx, a.question)
            print(r["summary"].result_text or "(no answer)")
            print(f"\n[run {r['run_id']} · {r['state']} · working tree unchanged: {r['tree_unchanged']}]", file=sys.stderr)
            return 0 if r["state"] == "succeeded" and r["tree_unchanged"] else 1
        if a.cmd == "post-merge":
            r = postmerge.run_post_merge(repo, a.change, not a.no_sync); print(json.dumps(r, indent=2)); return 0 if r["ok"] else 1
        if a.cmd == "team":
            from . import team
            r = team.start(ctx, a.task, a.teammates, a.worktree, a.model)
            print(json.dumps({"run": r["run_id"], "tmux": r["session"], "teammates": r["teammates"], "attach": f"tmux attach -t {r['session']}"}))
            if a.no_wait:
                return 0
            team.autotrust(r["session"])
            out = team.wait(ctx, r["run_id"], r["session"], r["out_dir"], a.timeout)
            print(json.dumps(out)); return 0 if out.get("state") == "succeeded" else 1
        if a.cmd == "verify-docker":
            from . import verify
            res = verify.verify_docker(ctx)
            print(json.dumps(res, indent=2, default=str)); return 0 if res.get("ok") else 1
        if a.cmd == "git":
            from . import gitops
            rep = {"preflight": gitops.preflight, "postflight": gitops.postflight, "finalize": gitops.finalize}[a.phase](ctx, a.change)
            print(json.dumps(rep.as_dict(), indent=2)); return 0 if rep.ok else 1
        if a.cmd == "cancel":
            print(jobs.cancel(ctx, a.run)); return 0
        if a.cmd == "sync-state":
            print(json.dumps(sync_state(store, repo, pid))); return 0
        if a.cmd == "pending":
            print(json.dumps(pending.pending(repo), indent=2)); return 0
    except (lifecycle.GateError, runner.CredentialError, RuntimeError) as e:
        print(f"swarm: {e}", file=sys.stderr)
        return 2
    return 0


def init_db() -> int:
    """Creates the schema and roles; gives the panel's read-only role a password stored (0600) in panel/.env, never printed."""
    import secrets
    env = Path(__file__).resolve().parent.parent.parent / "panel" / ".env"
    pw = None
    if not (env.exists() and "SWARM_PG_PASSWORD=" in env.read_text()):
        pw = secrets.token_urlsafe(24)
    apply_schema(admin(), reader_password=pw)
    if pw:
        with env.open("a") as f:
            f.write(f"\nSWARM_PG_PASSWORD={pw}\n")
        env.chmod(0o600)
        print("swarm_reader password stored in panel/.env (0600)")
    print("swarm schema and roles ready")
    return 0


def doctor() -> int:
    import os, shutil
    bad = 0
    def line(ok, msg):
        nonlocal bad; bad += (not ok); print(("  OK     " if ok else "  FALTA  ") + msg)
    try:
        runner.check_env(dict(os.environ)); line(True, "no API key / auth-token variable in the environment")
    except runner.CredentialError as e:
        line(False, str(e))
    st = runner.token_file_status()
    line(st["ok"], f"token file {runner.TOKEN_FILE}: " + (f"0600, ~{st['days_left']} days left" + (" (RENEW SOON)" if st.get("warn") else "") if st["ok"] else st["reason"]))
    for b in ("docker", "git", "claude", "openspec"):
        line(bool(shutil.which(b)), b)
    try:
        Pg().one("select 1 as ok"); line(True, "swarm_writer can reach Postgres")
    except Exception as e:
        line(False, f"Postgres: {e} (run `swarm init-db`)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
