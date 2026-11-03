"""Git agent: preflight/postflight/finalize against a real bare remote, a fake GitHub CLI, and one real read-only gh smoke test."""
import json, os, subprocess, sys
from pathlib import Path
import pytest
from conftest import make_change, run, needs_pg, ROOT
from swarmlib import changes as ch, gitops, jobs, lifecycle, runner
from swarmlib.gitops import Gh

pytestmark = needs_pg
FAKE = str(ROOT / "tests/swarm/fake_claude.py")


class FakeGh:
    def __init__(self, origin: Path, checks="pass", available=True):
        self.origin, self._checks, self._avail = origin, checks, available
        self.prs, self.created, self.merged, self.ready = {}, 0, [], []

    def available(self): return self._avail
    def pr_view(self, branch): return self.prs.get(branch)
    def pr_create(self, branch, base, title, body, draft=True):
        self.created += 1; self.prs[branch] = {"url": f"https://example.test/pr/{self.created}", "state": "OPEN", "isDraft": draft}
        return self.prs[branch]["url"]
    def pr_ready(self, branch): self.ready.append(branch)
    def pr_checks(self, branch): return self._checks
    def pr_merge(self, branch, method):
        tmp = self.origin.parent / "merge-clone"
        if tmp.exists(): subprocess.run(["rm", "-rf", str(tmp)])
        run(["git", "clone", "-q", str(self.origin), str(tmp)], self.origin.parent)
        run(["git", "config", "user.email", "t@t.dev"], tmp); run(["git", "config", "user.name", "t"], tmp)
        run(["git", "merge", "-q", "--no-ff", "-m", f"merge {branch}", f"origin/{branch}"], tmp)
        run(["git", "push", "-q", "origin", "HEAD:main"], tmp)
        self.merged.append((branch, method)); self.prs[branch]["state"] = "MERGED"


@pytest.fixture
def remote(repo, tmp_path):
    origin = tmp_path / "origin.git"
    run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], tmp_path)
    run(["git", "remote", "add", "origin", str(origin)], repo)
    run(["git", "push", "-q", "-u", "origin", "main"], repo)
    return origin


@pytest.fixture
def ctx(repo, store, tmp_path, monkeypatch, remote):
    monkeypatch.setenv("SWARM_CLAUDE", FAKE)
    monkeypatch.setattr(jobs, "PAUSE_FILE", tmp_path / "paused")
    monkeypatch.setattr(runner, "ROOT", ROOT / "swarm")
    c = jobs.Ctx(repo, "demo", store, "local", out_base=tmp_path / "runs")
    c.gh = FakeGh(remote)
    c.policy["gitops"]["wait_checks_minutes"] = 0           # tests that want to wait set it explicitly
    return c


def other_clone(origin, tmp_path, name="other"):
    d = tmp_path / name
    run(["git", "clone", "-q", str(origin), str(d)], tmp_path)
    run(["git", "config", "user.email", "o@o.dev"], d); run(["git", "config", "user.name", "o"], d)
    return d


def push_to_main(origin, tmp_path, fname, content="x\n", name="other"):
    d = other_clone(origin, tmp_path, name)
    (d / fname).write_text(content)
    run(["git", "add", "-A"], d); run(["git", "commit", "-q", "-m", f"add {fname}"], d); run(["git", "push", "-q", "origin", "main"], d)


def approve(ctx, cid="demo-change"):
    lifecycle.approve(ctx.store, "demo", ctx.repo, cid, validate=False)


def git_events(ctx):
    return [r["type"] for r in ctx.store.db.rows("select type from swarm.events where type like 'git_%' order by id")]


# -- preflight -------------------------------------------------------------------------------
def test_preflight_without_remote_is_local_only_and_costs_no_tokens(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE", FAKE); monkeypatch.setattr(jobs, "PAUSE_FILE", tmp_path / "p")
    c = jobs.Ctx(repo, "demo", store, "local", out_base=tmp_path / "runs")
    rep = gitops.preflight(c, "demo-change")
    assert rep.ok and not rep.remote and not rep.used_model
    assert any("no remote" in a for a in rep.actions)
    row = store.db.one("select kind, role, state, coalesce(input_tokens,0) as tok from swarm.runs order by id desc limit 1")
    assert (row["kind"], row["role"], row["state"], row["tok"]) == ("git", "gitops", "succeeded", 0)


def test_preflight_fast_forwards_main_and_updates_branch_by_merge_not_rebase(ctx, remote, tmp_path):
    make_change(ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo)
    assert gitops.preflight(ctx, "demo-change").ok                         # creates worktree + branch
    wt = jobs.worktree_path(ctx.repo, "change/demo-change")
    (wt / "work.txt").write_text("w\n"); jobs.commit(wt, "work")
    push_to_main(remote, tmp_path, "upstream.txt")
    rep = gitops.preflight(ctx, "demo-change")
    assert rep.ok and not rep.used_model
    assert (ctx.repo / "upstream.txt").exists()                            # local main fast-forwarded
    assert (wt / "upstream.txt").exists() and (wt / "work.txt").exists()   # branch has both
    parents = run(["git", "log", "-1", "--format=%P"], wt).stdout.split()
    assert len(parents) == 2                                               # a merge commit: history not rewritten
    assert "git_preflight" in git_events(ctx)


def test_preflight_blocks_on_unpushed_main_and_dirty_worktree(ctx):
    make_change(ctx.repo)                                                  # local-only commit on main
    rep = gitops.preflight(ctx, "demo-change")
    assert not rep.ok and "unpushed" in rep.blocking[0]
    run(["git", "push", "-q", "origin", "main"], ctx.repo)
    assert gitops.preflight(ctx, "demo-change").ok
    wt = jobs.worktree_path(ctx.repo, "change/demo-change"); (wt / "stray.txt").write_text("x")
    rep = gitops.preflight(ctx, "demo-change")
    assert not rep.ok and "uncommitted" in rep.blocking[0]


def conflict_setup(ctx, remote, tmp_path):
    make_change(ctx.repo); (ctx.repo / "shared.txt").write_text("base\n")
    run(["git", "add", "-A"], ctx.repo); run(["git", "commit", "-q", "-m", "shared"], ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo)
    assert gitops.preflight(ctx, "demo-change").ok
    wt = jobs.worktree_path(ctx.repo, "change/demo-change")
    (wt / "shared.txt").write_text("branch side\n"); jobs.commit(wt, "branch edit")
    push_to_main(remote, tmp_path, "shared.txt", "main side\n")
    return wt


def test_conflict_is_resolved_by_the_model_backed_git_agent_then_health_runs(ctx, remote, tmp_path, monkeypatch):
    wt = conflict_setup(ctx, remote, tmp_path)
    monkeypatch.setenv("FAKE_ACTION", "resolve")
    rep = gitops.preflight(ctx, "demo-change")
    assert rep.ok and rep.used_model and (wt / "shared.txt").read_text() == "resolved\n"
    assert not gitops.unmerged(wt)
    assert ctx.store.db.rows("select 1 from swarm.runs where kind='git' and model <> '' ")
    assert ctx.store.db.rows("select 1 from swarm.health where ok")


def test_unresolvable_conflict_aborts_and_blocks(ctx, remote, tmp_path, monkeypatch):
    wt = conflict_setup(ctx, remote, tmp_path)
    monkeypatch.setenv("FAKE_ACTION", "noop")
    rep = gitops.preflight(ctx, "demo-change")
    assert not rep.ok and "could not be resolved" in rep.blocking[0]
    assert run(["git", "status", "--porcelain"], wt).stdout.strip() == "" and not gitops.unmerged(wt)


# -- postflight ---------------------------------------------------------------------------------
def test_postflight_pushes_branch_and_opens_one_pr(ctx, remote):
    make_change(ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo)
    gitops.preflight(ctx, "demo-change")
    wt = jobs.worktree_path(ctx.repo, "change/demo-change"); (wt / "a.txt").write_text("1"); jobs.commit(wt, "task 1.1")
    r1 = gitops.postflight(ctx, "demo-change", "1.1")
    assert r1.ok and r1.pr and ctx.gh.created == 1
    assert "change/demo-change" in run(["git", "branch", "-r"], ctx.repo).stdout or run(["git", "ls-remote", "--heads", str(remote)], ctx.repo).stdout.count("change/demo-change") == 1
    (wt / "b.txt").write_text("2"); jobs.commit(wt, "task 1.2")
    assert gitops.postflight(ctx, "demo-change", "1.2").ok and ctx.gh.created == 1     # PR reused, not duplicated
    (wt / "dirty.txt").write_text("x")
    rep = gitops.postflight(ctx, "demo-change", "1.3")
    assert not rep.ok and "uncommitted" in rep.blocking[0]


def test_postflight_degrades_when_gh_unavailable(ctx):
    make_change(ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo)
    gitops.preflight(ctx, "demo-change"); ctx.gh._avail = False
    rep = gitops.postflight(ctx, "demo-change", "1.1")
    assert rep.ok and rep.pr is None and any("gh unavailable" in a for a in rep.actions)


# -- full flow with merge policy ---------------------------------------------------------------------
def full_flow(ctx, monkeypatch):
    make_change(ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl"); r = jobs.implement(ctx, "demo-change")
    assert r["complete"]
    monkeypatch.setenv("FAKE_ACTION", "review_pass")
    return jobs.review(ctx, "demo-change")


def test_git_agent_runs_before_and_after_each_task_in_order(ctx, monkeypatch):
    ctx.policy["gitops"]["auto_merge"] = False
    full_flow(ctx, monkeypatch)
    rows = ctx.store.db.rows("select kind, task_id from swarm.runs order by id")
    seq = [r["kind"] + (":" + r["task_id"] if r["task_id"] else "") for r in rows]
    assert seq == ["git", "implement:1.1", "git", "implement:1.2", "git", "review", "git"]
    assert git_events(ctx) == ["git_preflight", "git_postflight", "git_postflight", "git_finalize"]


def test_merge_when_policy_holds_then_main_refreshed_and_cleaned(ctx, monkeypatch):
    out = full_flow(ctx, monkeypatch)["git"]
    assert out["merged"] and ctx.gh.merged == [("change/demo-change", "squash")] and out["ok"]
    assert (ctx.repo / "marker.txt").exists() and (ctx.repo / "marker2.txt").exists()      # local main now has the work
    assert not jobs.worktree_path(ctx.repo, "change/demo-change").exists()
    assert "change/demo-change" not in run(["git", "branch", "--list"], ctx.repo).stdout


@pytest.mark.parametrize("tweak,expect", [
    (lambda c: c.policy["gitops"].__setitem__("auto_merge", False), "auto_merge is disabled"),
    (lambda c: setattr(c.gh, "_checks", "fail"), "required checks are fail"),
    (lambda c: setattr(c.gh, "_checks", "pending"), "required checks are pending"),
])
def test_policy_failures_leave_the_pr_open_and_name_the_condition(ctx, monkeypatch, tweak, expect):
    tweak(ctx)
    out = full_flow(ctx, monkeypatch)["git"]
    assert not out["merged"] and any(expect in u for u in out["unmet"]) and ctx.gh.merged == []
    assert (ctx.repo / "marker.txt").exists() is False


def test_no_merge_without_a_passing_verdict(ctx, monkeypatch):
    make_change(ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl"); jobs.implement(ctx, "demo-change")
    rep = gitops.finalize(ctx, "demo-change")
    assert not rep.merged and any("verdict" in u for u in rep.unmet)


def test_preflight_blocks_implementation_and_no_task_runs(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)                                   # main has an unpushed commit -> preflight blocks
    monkeypatch.setenv("FAKE_ACTION", "impl")
    with pytest.raises(lifecycle.GateError) as e:
        jobs.implement(ctx, "demo-change")
    assert e.value.code == "git_blocked"
    assert not ctx.store.db.rows("select 1 from swarm.runs where kind='implement'")


# -- real smoke ----------------------------------------------------------------------------------------
def test_smoke_real_gh_readonly_and_real_git_remote(repo):
    gh = Gh(ROOT)
    if not gh.available():
        pytest.skip("gh not authenticated")
    pr = gh.pr_view("feat/swarm-harness-platform")        # merged PR of this very repository
    assert pr is None or pr["state"] in ("MERGED", "CLOSED", "OPEN")
    assert isinstance(gh.pr_checks("feat/swarm-harness-platform"), str)


def test_finalize_waits_for_pending_ci_then_merges(ctx, monkeypatch):
    seq = iter(["pending", "pending", "pass", "pass", "pass"])
    ctx.gh.pr_checks = lambda branch: next(seq, "pass")
    ctx.policy["gitops"]["wait_checks_minutes"] = 1
    ctx.sleep = lambda s: None
    out = full_flow(ctx, monkeypatch)["git"]
    assert out["merged"] and any("waited for CI: pass" in a for a in out["actions"])


def test_finalize_does_not_merge_if_ci_never_finishes(ctx, monkeypatch):
    ctx.gh.pr_checks = lambda branch: "pending"
    ctx.policy["gitops"]["wait_checks_minutes"] = 0.01
    ctx.sleep = lambda s: __import__("time").sleep(0.4)
    out = full_flow(ctx, monkeypatch)["git"]
    assert not out["merged"] and any("pending" in u for u in out["unmet"])


def test_main_fast_forward_tolerates_unrelated_local_edits_but_not_conflicting_ones(ctx, remote, tmp_path):
    make_change(ctx.repo); (ctx.repo / "notes.txt").write_text("v1\n"); run(["git", "add", "-A"], ctx.repo)
    run(["git", "commit", "-q", "-m", "notes"], ctx.repo); run(["git", "push", "-q", "origin", "main"], ctx.repo)
    (ctx.repo / "notes.txt").write_text("my local edit\n")                              # tracked + modified, unrelated to the incoming commit
    push_to_main(remote, tmp_path, "upstream.txt")
    rep = gitops.Report("preflight"); gitops.refresh_main(ctx, rep)
    assert rep.ok and (ctx.repo / "upstream.txt").exists() and (ctx.repo / "notes.txt").read_text() == "my local edit\n"
    push_to_main(remote, tmp_path, "notes.txt", "remote edit\n", name="other2")          # now the incoming commit touches the edited file
    rep = gitops.Report("preflight"); gitops.refresh_main(ctx, rep)
    assert not rep.ok and "cannot fast-forward" in rep.blocking[0]
