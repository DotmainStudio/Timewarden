"""Git operations agent: keeps main, change branches and GitHub in sync around every task.

Deterministic first (zero tokens when everything is clean); the model-backed `gitops` role is launched only to resolve
merge conflicts. Runs on the HOST (needs the user's git/gh credentials, never put in containers). Never force-pushes,
never rebases, never pushes to the main branch; updates branches by merging the main branch INTO them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import backlog, lifecycle
from . import changes as ch
from . import jobs


@dataclass
class Report:
    phase: str
    ok: bool = True
    blocking: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    remote: bool = False
    pr: str | None = None
    merged: bool = False
    used_model: bool = False
    unmet: list[str] = field(default_factory=list)

    def block(self, msg: str) -> "Report":
        self.ok = False
        self.blocking.append(msg)
        return self

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("phase", "ok", "blocking", "actions", "remote", "pr", "merged", "used_model", "unmet")}


class Gh:
    """Thin GitHub CLI client (injectable: tests use a fake)."""

    def __init__(self, repo: Path):
        self.repo = repo

    def available(self) -> bool:
        return bool(shutil.which("gh")) and subprocess.run(["gh", "auth", "status"], cwd=self.repo, capture_output=True).returncode == 0

    def _run(self, *args: str) -> tuple[int, str]:
        r = subprocess.run(["gh", *args], cwd=self.repo, capture_output=True, text=True, timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()

    def pr_view(self, branch: str) -> dict | None:
        rc, out = self._run("pr", "view", branch, "--json", "url,state,isDraft,number")
        return json.loads(out) if rc == 0 else None

    def pr_create(self, branch: str, base: str, title: str, body: str, draft: bool = True) -> str:
        args = ["pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body] + (["--draft"] if draft else [])
        rc, out = self._run(*args)
        if rc != 0:
            raise RuntimeError(out[-200:])
        return out.splitlines()[-1].strip()

    def pr_ready(self, branch: str) -> None:
        self._run("pr", "ready", branch)

    def pr_checks(self, branch: str) -> str:
        """'pass' | 'fail' | 'pending' | 'none'"""
        rc, out = self._run("pr", "checks", branch, "--json", "state")
        if rc != 0 and "no checks" in out.lower():
            return "none"
        try:
            states = {c["state"] for c in json.loads(out)}
        except (json.JSONDecodeError, KeyError, TypeError):
            return "none"
        if not states:
            return "none"
        if states & {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"}:
            return "fail"
        return "pending" if states & {"PENDING", "QUEUED", "IN_PROGRESS"} else "pass"

    def pr_merge(self, branch: str, method: str) -> None:
        rc, out = self._run("pr", "merge", branch, f"--{method}")
        if rc != 0:
            raise RuntimeError(out[-200:])


# -- low-level helpers -----------------------------------------------------------------
def has_remote(repo: Path) -> bool:
    return "origin" in jobs.git(repo, "remote")[1].split()


def counts(repo: Path, a: str, b: str) -> tuple[int, int] | None:
    rc, out = jobs.git(repo, "rev-list", "--left-right", "--count", f"{a}...{b}")
    if rc != 0:
        return None
    left, right = out.split()
    return int(left), int(right)


def unmerged(wt: Path) -> list[str]:
    return [l for l in jobs.git(wt, "diff", "--name-only", "--diff-filter=U")[1].splitlines() if l.strip()]


def dirty(wt: Path) -> list[str]:
    lines = jobs.git(wt, "status", "--porcelain", "--untracked-files=all")[1].splitlines()
    return [l for l in lines if l[3:].strip() not in ("progress/current.md",)]


def refresh_main(ctx: jobs.Ctx, rep: Report) -> str:
    """Fetch and fast-forward the local main branch. Never pushes. Returns the ref new branches should contain."""
    repo, base = ctx.repo, jobs.main_branch(ctx.repo)
    rep.remote = has_remote(repo)
    if not rep.remote:
        rep.actions.append("no remote: local consistency only")
        return base
    rc, out = jobs.git(repo, "fetch", "origin", "--prune")
    if rc != 0:
        rep.block(f"cannot reach the remote: {out.strip()[-120:]}")
        return base
    ab = counts(repo, base, f"origin/{base}")
    if ab is None:
        rep.actions.append(f"origin/{base} not found: skipped main refresh")
        return base
    ahead, behind = ab
    if ahead and behind:
        rep.block(f"local {base} and origin/{base} diverged ({ahead} ahead, {behind} behind)")
    elif ahead:
        rep.block(f"local {base} has {ahead} unpushed commit(s); agents never push the main branch")
    elif behind:
        cur = jobs.git(repo, "branch", "--show-current")[1].strip()
        if cur == base:
            # unrelated local edits are fine: git itself refuses only if the incoming commits touch them
            rc, out = jobs.git(repo, "merge", "--ff-only", f"origin/{base}")
            if rc != 0:
                rep.block(f"local {base} is behind and cannot fast-forward: {out.strip()[-140:]}")
            else:
                rep.actions.append(f"fast-forwarded {base} by {behind} commit(s)")
        else:
            jobs.git(repo, "fetch", "origin", f"{base}:{base}")
            rep.actions.append(f"updated {base} by {behind} commit(s)")
    return f"origin/{base}"


def update_branch(ctx: jobs.Ctx, wt: Path, base_ref: str, change_id: str, branch: str, rep: Report) -> None:
    """Merge the main branch INTO the change branch (never rebase / force). Conflicts go to the model-backed agent."""
    ab = counts(wt, "HEAD", base_ref)
    if ab is None or ab[1] == 0:
        return
    rc, out = jobs.git(wt, "-c", "user.name=swarm-gitops", "-c", "user.email=swarm@localhost", "merge", "--no-edit", base_ref)
    if rc == 0:
        rep.actions.append(f"merged {base_ref} into {branch} ({ab[1]} commit(s))")
        return
    files = unmerged(wt)
    if not files:
        jobs.git(wt, "merge", "--abort")
        rep.block(f"merge of {base_ref} failed: {out.strip()[-120:]}")
        return
    rep.used_model = True
    prompt = (f"Merging {base_ref} into {branch} conflicted in: {', '.join(files[:10])}. Resolve every conflict keeping the intent of both sides, "
              f"run `bash scripts/health.sh`, then `git add -A` and `git commit --no-edit`. Do not push. Report in at most 5 lines.")
    res = jobs.execute(ctx, "git", "gitops", prompt, wt, change_id, None, branch, mode_override="local")
    still = unmerged(wt)
    merging = (wt / ".git").exists() and jobs.git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    rc_h, out_h = jobs.sh(ctx.health_cmd, wt)
    ctx.store.health(res["run_id"], ctx.project_id, change_id, rc_h == 0, out_h)
    if still or merging or rc_h != 0 or res["state"] != "succeeded":
        jobs.git(wt, "merge", "--abort")
        rep.block("merge conflict could not be resolved safely (aborted); needs attention")
    else:
        rep.actions.append(f"resolved merge conflicts in {len(files)} file(s) with the git agent")


def push_branch(wt: Path, branch: str, rep: Report) -> bool:
    rc, out = jobs.git(wt, "push", "-u", "origin", branch)
    if rc != 0:
        rep.block(f"push of {branch} failed: {out.strip()[-120:]}")
        return False
    rep.actions.append(f"pushed {branch}")
    return True


def ensure_pr(ctx: jobs.Ctx, wt: Path, change_id: str, branch: str, rep: Report, draft: bool = True) -> None:
    gh = ctx.gh
    if not gh.available():
        rep.actions.append("gh unavailable: branch pushed, no pull request managed")
        return
    base = jobs.main_branch(ctx.repo)
    pr = gh.pr_view(branch)
    if pr and pr.get("state") == "OPEN":
        rep.pr = pr["url"]
        return
    c = ch.load(wt / "openspec" / "changes" / change_id)
    title = f"{change_id}: {backlog.title_of(wt / 'openspec' / 'changes' / change_id)}"[:120]
    body = f"Change `{change_id}` ({c.done}/{len(c.tasks)} tasks done). Spec: `openspec/changes/{change_id}/`.\n\nManaged by the swarm git agent."
    try:
        rep.pr = gh.pr_create(branch, base, title, body, draft)
        rep.actions.append("opened pull request" + (" (draft)" if draft else ""))
    except RuntimeError as e:
        rep.actions.append(f"could not open the pull request: {e}")


# -- phases --------------------------------------------------------------------------------
def record(ctx: jobs.Ctx, rep: Report, change_id: str) -> Report:
    rid = ctx.store.create_run(ctx.project_id, "git", "gitops", change_id, None, "", "", "host", f"change/{change_id}", "", ctx.policy["_hash"])
    ctx.store.update_run(rid, state="succeeded" if rep.ok else "failed", auth_kind="host-git", summary="; ".join(rep.blocking or rep.actions)[:500])
    ctx.store.event(ctx.project_id, f"git_{rep.phase}", rid, "gitops", ok=rep.ok, detail=rep.as_dict())
    return rep


def preflight(ctx: jobs.Ctx, change_id: str) -> Report:
    """Before the first task: main refreshed, worktree present and clean, branch contains the latest main."""
    rep = Report("preflight")
    base_ref = refresh_main(ctx, rep)
    branch = f"change/{change_id}"
    if rep.ok:
        wt = jobs.ensure_worktree(ctx, branch)
        d = dirty(wt)
        if d:
            rep.block(f"worktree has uncommitted changes: {', '.join(x[3:] for x in d[:5])}")
        elif unmerged(wt):
            rep.block("worktree has unresolved merge conflicts")
        else:
            update_branch(ctx, wt, base_ref, change_id, branch, rep)
    return record(ctx, rep, change_id)


def postflight(ctx: jobs.Ctx, change_id: str, task_id: str = "") -> Report:
    """After a task: worktree clean (code committed), branch pushed, pull request created/updated."""
    rep = Report("postflight")
    branch, wt = f"change/{change_id}", jobs.worktree_path(ctx.repo, f"change/{change_id}")
    d = dirty(wt)
    if d:
        rep.block(f"uncommitted changes after task {task_id}: {', '.join(x[3:] for x in d[:5])}")
        return record(ctx, rep, change_id)
    rep.remote = has_remote(ctx.repo)
    if not rep.remote:
        rep.actions.append("no remote: local consistency only")
    elif push_branch(wt, branch, rep):
        ensure_pr(ctx, wt, change_id, branch, rep, draft=True)
    return record(ctx, rep, change_id)


def merge_conditions(ctx: jobs.Ctx, change_id: str, wt: Path, behind: int, checks: str) -> list[str]:
    unmet = []
    g = ctx.policy.get("gitops") or {}
    if not g.get("auto_merge", True):
        unmet.append("auto_merge is disabled: the user merges")
    state, _ = lifecycle.approval_state(ctx.store, ctx.project_id, ctx.repo / "openspec" / "changes" / change_id)
    if state != "valid":
        unmet.append("change approval is not valid")
    v = ctx.store.latest_verdict(ctx.project_id, change_id)
    if not (v and v["passed"]):
        unmet.append("latest review verdict has not passed")
    if not ch.load(wt / "openspec" / "changes" / change_id).complete:
        unmet.append("not all tasks are done")
    rc, out = jobs.sh(ctx.health_cmd, wt)
    if rc != 0:
        unmet.append("health script failed")
    if behind:
        unmet.append("branch does not contain the latest main branch")
    if g.get("require_checks", True) and checks in ("fail", "pending"):
        unmet.append(f"required checks are {checks}")
    return unmet


def wait_for_checks(ctx: jobs.Ctx, branch: str, rep: Report) -> str:
    """Polls the PR checks while they are pending, up to gitops.wait_checks_minutes (the CI must finish before a merge decision)."""
    g = ctx.policy.get("gitops") or {}
    deadline = time.time() + float(g.get("wait_checks_minutes", 10)) * 60
    state = ctx.gh.pr_checks(branch)
    waited = False
    while state == "pending" and time.time() < deadline:
        waited = True
        getattr(ctx, "sleep", time.sleep)(float(g.get("check_poll_seconds", 15)))
        state = ctx.gh.pr_checks(branch)
    if waited:
        rep.actions.append(f"waited for CI: {state}")
    return state


def finalize(ctx: jobs.Ctx, change_id: str) -> Report:
    """After review passes: sync, mark the PR ready, and merge ONLY if every policy condition holds; then refresh main and clean up."""
    rep = Report("finalize")
    branch, wt = f"change/{change_id}", jobs.worktree_path(ctx.repo, f"change/{change_id}")
    base_ref = refresh_main(ctx, rep)
    if not rep.ok:
        return record(ctx, rep, change_id)
    if dirty(wt):
        rep.block("worktree has uncommitted changes")
        return record(ctx, rep, change_id)
    update_branch(ctx, wt, base_ref, change_id, branch, rep)
    if not rep.ok:
        return record(ctx, rep, change_id)
    if not rep.remote:
        rep.unmet.append("no remote: nothing to merge through")
        return record(ctx, rep, change_id)
    if not push_branch(wt, branch, rep):
        return record(ctx, rep, change_id)
    ensure_pr(ctx, wt, change_id, branch, rep, draft=False)
    if not ctx.gh.available() or not rep.pr:
        rep.unmet.append("no pull request available (gh missing or PR not created)")
        return record(ctx, rep, change_id)
    ctx.gh.pr_ready(branch)
    behind = (counts(wt, "HEAD", base_ref) or (0, 0))[1]
    rep.unmet = merge_conditions(ctx, change_id, wt, behind, wait_for_checks(ctx, branch, rep))
    if rep.unmet:
        rep.actions.append("pull request left open: " + "; ".join(rep.unmet))
        return record(ctx, rep, change_id)
    try:
        ctx.gh.pr_merge(branch, (ctx.policy.get("gitops") or {}).get("merge_method", "squash"))
    except RuntimeError as e:
        rep.block(f"merge failed: {e}")
        return record(ctx, rep, change_id)
    rep.merged = True
    rep.actions.append("merged the pull request")
    refresh_main(ctx, rep)
    cleanup_merged(ctx, wt, branch, rep)
    return record(ctx, rep, change_id)


def cleanup_merged(ctx: jobs.Ctx, wt: Path, branch: str, rep: Report) -> None:
    jobs.git(ctx.repo, "worktree", "remove", "--force", str(wt))
    jobs.git(ctx.repo, "branch", "-D", branch)
    jobs.git(ctx.repo, "push", "origin", "--delete", branch)
    jobs.git(ctx.repo, "worktree", "prune")
    rep.actions.append(f"removed worktree and branch {branch}")
