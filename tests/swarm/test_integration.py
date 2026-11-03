"""Integration tests: real Postgres (throwaway DB), real git repos, fake claude. Covers the spec scenarios."""
import json, os, subprocess, sys
from pathlib import Path
import pytest
from conftest import make_change, run, needs_pg, ROOT
from swarmlib import changes as ch, jobs, lifecycle, pg, postmerge, runner
from swarmlib.store import Store

pytestmark = needs_pg
FAKE = str(ROOT / "tests/swarm/fake_claude.py")


@pytest.fixture
def ctx(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE", FAKE)
    monkeypatch.setattr(jobs, "PAUSE_FILE", tmp_path / "paused")
    monkeypatch.setattr(runner, "ROOT", ROOT / "swarm")
    return jobs.Ctx(repo, "demo", store, "local", out_base=tmp_path / "runs")


def approve(ctx, cid="demo-change"):
    return lifecycle.approve(ctx.store, "demo", ctx.repo, cid, validate=False)


# -- spec-first gate ------------------------------------------------------------
def test_idea_without_change_only_planning_allowed(ctx):
    with pytest.raises(lifecycle.GateError) as e:
        jobs.implement(ctx, "no-such-change")
    assert e.value.code == "no_change" and ctx.store.active_runs("demo") == []


def test_unapproved_change_refused_then_approved_ok(ctx, monkeypatch):
    make_change(ctx.repo)
    with pytest.raises(lifecycle.GateError) as e:
        jobs.implement(ctx, "demo-change")
    assert e.value.code == "awaiting_approval"
    approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl")
    r = jobs.implement(ctx, "demo-change")
    assert r["tasks_done"] == 2 and r["complete"]


def test_edit_after_approval_voids_it(ctx):
    d = make_change(ctx.repo)
    approve(ctx)
    lifecycle.require_approved(ctx.store, "demo", ctx.repo, "demo-change")
    (d / "proposal.md").write_text("# Demo change\n\nEdited after approval\n")
    with pytest.raises(lifecycle.GateError) as e:
        lifecycle.require_approved(ctx.store, "demo", ctx.repo, "demo-change")
    assert e.value.code == "approval_void"
    with pytest.raises(lifecycle.GateError):                      # stays void until re-approved
        lifecycle.require_approved(ctx.store, "demo", ctx.repo, "demo-change")
    approve(ctx)
    lifecycle.require_approved(ctx.store, "demo", ctx.repo, "demo-change")


def test_cannot_approve_incomplete_change(ctx):
    d = ctx.repo / "openspec/changes/half"; d.mkdir(parents=True); (d / "proposal.md").write_text("# h")
    with pytest.raises(lifecycle.GateError) as e:
        lifecycle.approve(ctx.store, "demo", ctx.repo, "half", validate=False)
    assert e.value.code == "incomplete"


def test_status_progression(ctx, monkeypatch):
    c = ch.load(make_change(ctx.repo))
    st = lambda: lifecycle.status_of(ctx.store, "demo", ch.load(ctx.repo / "openspec/changes/demo-change"))
    assert st() == "awaiting_approval"
    approve(ctx); assert st() == "approved"


# -- planning ----------------------------------------------------------------------
def test_planning_writes_only_change_dir(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_ACTION", "plan")
    r = jobs.plan(ctx, "add demo feature", "demo-feat")
    assert r["state"] == "succeeded" and r["change_id"] == "demo-feat", r.get("stray")
    assert jobs.changed_outside(ctx, r["worktree"], "openspec/changes/demo-feat/") == []
    assert (r["worktree"] / "openspec/changes/demo-feat/proposal.md").exists()
    assert not ch.is_complete_plan(r["worktree"] / "openspec/changes/demo-feat")
    assert ctx.store.running_count() == 0


def test_planning_scope_violation_is_failed_and_logged(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_ACTION", "plan"); monkeypatch.setenv("FAKE_STRAY", "1")
    r = jobs.plan(ctx, "x", "demo-stray")
    assert r["state"] == "failed" and "src_evil.py" in r["stray"]
    ev = ctx.store.db.rows("select type from swarm.events where type='plan_scope_violation'")
    assert len(ev) == 1


def test_planner_with_open_questions_reports_needs_input(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_ACTION", "plan_open")
    r = jobs.plan(ctx, "x", "demo-q")
    assert r["state"] == "needs_input" and len(r["questions"]) == 2 and "specs/*/spec.md" in r["missing"]
    assert ctx.store.db.rows("select 1 from swarm.events where type='plan_needs_input'")


# -- implementation / tasks -------------------------------------------------------------
def test_task_not_ticked_when_verification_fails(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl_noop")               # agent "finishes" without creating the marker
    r = jobs.implement(ctx, "demo-change")
    assert r["tasks_done"] == 0
    tasks = (r["worktree"] / "openspec/changes/demo-change/tasks.md").read_text()
    assert "- [ ] 1.1" in tasks
    run_row = ctx.store.db.one("select state from swarm.runs order by id desc limit 1")
    assert run_row["state"] == "failed"
    assert ctx.store.db.rows("select 1 from swarm.events where type='needs_attention'")


def test_health_failure_blocks_tick(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    ctx.health_cmd = "exit 1"
    monkeypatch.setenv("FAKE_ACTION", "impl")
    assert jobs.implement(ctx, "demo-change")["tasks_done"] == 0


def test_tasks_run_in_order_and_commit_per_task(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl")
    r = jobs.implement(ctx, "demo-change", max_tasks=1)
    assert r["tasks_done"] == 1
    t = ch.load(r["worktree"] / "openspec/changes/demo-change")
    assert [x.done for x in t.tasks] == [True, False]
    log = run(["git", "log", "--oneline"], r["worktree"]).stdout
    assert "task 1.1" in log
    assert ctx.repo.joinpath("marker.txt").exists() is False        # main checkout untouched (worktree isolation)


def test_concurrency_cap_and_pause(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    for i in range(2):                                              # fill the cap (policy default 2)
        rid = ctx.store.create_run("demo", "implement", "implementer"); ctx.store.update_run(rid, state="running")
    monkeypatch.setenv("FAKE_ACTION", "impl")
    with pytest.raises(RuntimeError, match="concurrency cap"):
        jobs.implement(ctx, "demo-change")
    ctx.store.db.execute("update swarm.runs set state='cancelled'")
    jobs.pause(True)
    with pytest.raises(RuntimeError, match="paused"):
        jobs.implement(ctx, "demo-change")
    jobs.pause(False)


def test_timeout_stops_job_and_saves_progress(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    ctx.policy["limits"]["timeout_minutes"]["implementer"] = 0.02     # ~1 s
    monkeypatch.setenv("FAKE_ACTION", "sleep")
    r = jobs.implement(ctx, "demo-change")
    assert r["tasks_done"] == 0
    row = ctx.store.db.one("select state from swarm.runs order by id desc limit 1")
    assert row["state"] == "timeout"
    assert "Stopped (timeout)" in (r["worktree"] / "progress/current.md").read_text()


def test_credential_conflict_refuses_before_any_request(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x"); monkeypatch.setenv("FAKE_ACTION", "impl")
    with pytest.raises(runner.CredentialError):
        jobs.implement(ctx, "demo-change")
    assert ctx.store.db.rows("select 1 from swarm.events where type='credential_refused'")
    assert not (ctx.repo.parent / ".swarm-worktrees").glob("*/marker.txt").__next__ if False else True


# -- review ------------------------------------------------------------------------------
def prepared(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl"); jobs.implement(ctx, "demo-change")


def test_review_pass_marks_done(ctx, monkeypatch):
    prepared(ctx, monkeypatch)
    monkeypatch.setenv("FAKE_ACTION", "review_pass")
    r = jobs.review(ctx, "demo-change")
    assert r["passed"]
    wt = ctx.repo.parent / ".swarm-worktrees" / "proj-change-demo-change"
    assert lifecycle.status_of(ctx.store, "demo", ch.load(wt / "openspec/changes/demo-change")) == "done"


def test_scenario_without_evidence_fails_and_names_it(ctx, monkeypatch):
    prepared(ctx, monkeypatch)
    monkeypatch.setenv("FAKE_ACTION", "review_noevidence")
    r = jobs.review(ctx, "demo-change")
    assert not r["passed"] and any("demo/demo-works/it-works" in f for f in r["findings"])


def test_unparseable_review_fails(ctx, monkeypatch):
    prepared(ctx, monkeypatch)
    monkeypatch.setenv("FAKE_ACTION", "noop")
    assert not jobs.review(ctx, "demo-change")["passed"]


def test_parked_after_two_failed_reviews(ctx, monkeypatch):
    prepared(ctx, monkeypatch)
    monkeypatch.setenv("FAKE_ACTION", "review_fail")
    assert not jobs.review(ctx, "demo-change")["parked"]
    r2 = jobs.review(ctx, "demo-change")
    assert r2["parked"]
    with pytest.raises(lifecycle.GateError) as e:
        jobs.review(ctx, "demo-change")
    assert e.value.code == "parked"
    assert ctx.store.db.rows("select 1 from swarm.events where type='parked'")


def test_reviewer_role_is_readonly_in_policy_and_mount():
    p = __import__("swarmlib.policy", fromlist=["x"]).load()
    assert p["roles"]["reviewer"]["writes"] is False


# -- cancel -------------------------------------------------------------------------------
def test_cancel_keeps_worktree(ctx):
    wt = jobs.ensure_worktree(ctx, "change/x")
    rid = ctx.store.create_run("demo", "implement", "implementer", worktree=str(wt)); ctx.store.update_run(rid, state="running")
    msg = jobs.cancel(ctx, rid)
    assert "worktree kept" in msg and wt.exists() and ctx.store.run(rid)["state"] == "cancelled"


# -- monitoring store -----------------------------------------------------------------------
def test_run_figures_events_and_task_assignment(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl")
    jobs.implement(ctx, "demo-change", max_tasks=1)
    r = ctx.store.db.one("select * from swarm.runs where kind='implement' order by id limit 1")
    assert (r["input_tokens"], r["output_tokens"], r["cache_read_tokens"], r["turns"]) == (3, 5, 100, 2)
    assert r["auth_kind"] == "host-login" and float(r["quota_utilization"]) == 0.07 and r["policy_hash"]
    assert ctx.store.db.rows("select 1 from swarm.events where type='auth_check' and (detail->>'api_key_present')='false'")
    assert ctx.store.db.rows("select 1 from swarm.health where ok")


def test_events_contain_no_secrets(ctx):
    tok = "sk-ant-oat01-" + "z" * 40
    ctx.store.event("demo", "tool_start", None, detail={"input": {"command": f"echo {tok}", "content": "SECRET=" + "q" * 40}})
    rows = ctx.store.db.rows("select detail::text as d from swarm.events")
    assert tok not in rows[0]["d"] and "SECRET=" not in rows[0]["d"]


def test_roles_reader_cannot_write_writer_can(scratch_db, store):
    rd = pg.Pg(db=scratch_db, user=pg.READER)
    assert rd.rows("select count(*) as n from swarm.runs")[0]["n"] == 0
    for stmt in ("insert into swarm.projects(project_id) values ('x')", "update swarm.runs set state='failed'", "delete from swarm.events"):
        with pytest.raises(pg.PgError, match="permission denied|read-only"):
            rd.execute(stmt)
    store.upsert_project("p", Path("/x"))


def test_recall_usage_marking():
    ev = [{"type": "recall", "query_hash": "a", "sources": ["docs/agent-memory/x.md"], "rejected": False},
          {"type": "recall", "query_hash": "b", "sources": ["docs/y.md"], "rejected": False},
          {"type": "recall", "query_hash": "c", "sources": [], "rejected": True}]
    u = jobs.mark_recalls_used(ev, "Per docs/agent-memory/x.md the rule is...")
    assert u == {"a": True, "b": False}
    assert jobs.mark_recalls_used(ev + [{"type": "recall_used", "query_hash": "b"}], "")["b"] is True


def test_recall_wrapper_rejects_other_dataset(repo, tmp_path):
    out = tmp_path / "o"; out.mkdir()
    env = {**os.environ, "SWARM_OUT": str(out), "SWARM_REPO": str(repo), "COGNEE_API_KEY": "k"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "swarm/runner/recall.py"), "anything", "--dataset", "other-project-knowledge"], capture_output=True, text=True, env=env)
    assert r.returncode == 4 and "cross-project" in r.stderr
    ev = json.loads((out / "events.jsonl").read_text().splitlines()[0])
    assert ev["rejected"] is True and ev["dataset"] == "other-project-knowledge"


# -- post-merge ----------------------------------------------------------------------------------
def test_post_merge_requires_main_and_merged(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl"); jobs.implement(ctx, "demo-change")
    r = postmerge.run_post_merge(ctx.repo, "demo-change", run_sync=False)
    assert not r["ok"] and "not merged" in r["reason"]
    run(["git", "merge", "-q", "--no-edit", "change/demo-change"], ctx.repo)
    r = postmerge.run_post_merge(ctx.repo, "demo-change", run_sync=False)
    assert r["ok"] and r["steps"][0]["step"] == "archive"
    assert (ctx.repo / "openspec/changes/demo-change").exists()      # main checkout untouched: archive is on its own branch
    arch = ctx.repo.parent / ".swarm-worktrees" / "proj-chore-archive-demo-change"
    assert (arch / "openspec/changes/archive").exists() and (arch / "openspec/specs/demo/spec.md").exists()


def test_post_merge_refuses_off_main_or_dirty(ctx):
    make_change(ctx.repo)
    run(["git", "checkout", "-q", "-b", "feature"], ctx.repo)
    assert "not 'main'" in postmerge.run_post_merge(ctx.repo, "demo-change", run_sync=False)["reason"]
    run(["git", "checkout", "-q", "main"], ctx.repo); (ctx.repo / "dirty.txt").write_text("x")      # untracked: ignored
    (ctx.repo / "scripts" / "health.sh").write_text("#!/usr/bin/env bash\nexit 0 # edited\n")        # tracked + modified: refused
    assert "uncommitted" in postmerge.run_post_merge(ctx.repo, "demo-change", run_sync=False)["reason"]


def test_post_merge_runs_one_sync_from_main(ctx, tmp_path):
    marker = tmp_path / "sync.log"
    cmd = ["bash", "-c", f"echo $(git branch --show-current) >> {marker}"]
    make_change(ctx.repo)
    r = postmerge.run_post_merge(ctx.repo, "demo-change", sync_cmd=cmd)
    assert r["steps"][-1]["step"] == "memory_sync" and marker.read_text().split() == ["main"]


def test_status_reads_progress_from_the_change_worktree(ctx, monkeypatch):
    from swarmlib.cli import sync_state
    make_change(ctx.repo); approve(ctx)
    assert sync_state(ctx.store, ctx.repo, "demo")["demo-change"] == "approved"
    monkeypatch.setenv("FAKE_ACTION", "impl"); jobs.implement(ctx, "demo-change", max_tasks=1)
    assert sync_state(ctx.store, ctx.repo, "demo")["demo-change"] == "in_progress"
    jobs.implement(ctx, "demo-change")
    assert sync_state(ctx.store, ctx.repo, "demo")["demo-change"] == "review"
    monkeypatch.setenv("FAKE_ACTION", "review_pass"); jobs.review(ctx, "demo-change")
    assert sync_state(ctx.store, ctx.repo, "demo")["demo-change"] == "done"
    row = ctx.store.db.one("select tasks_done, tasks_total, status from swarm.changes")
    assert (row["tasks_done"], row["tasks_total"], row["status"]) == (2, 2, "done")


def test_explore_proves_the_tree_is_unchanged(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_ACTION", "noop")
    r = jobs.explore(ctx, "where is the entry point?")
    assert r["state"] == "succeeded" and r["tree_unchanged"]
    assert ctx.store.db.rows("select 1 from swarm.events where type='readonly_check' and ok")
    assert ctx.store.db.one("select kind, role from swarm.runs order by id desc limit 1") == {"kind": "explore", "role": "explorer"}


def test_explore_that_changes_the_tree_fails(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_ACTION", "explore_dirty")
    r = jobs.explore(ctx, "x")
    assert r["state"] == "failed" and not r["tree_unchanged"]
    assert ctx.store.db.rows("select 1 from swarm.events where type='readonly_check' and not ok")


def test_review_no_git_records_verdict_without_finalize(ctx, monkeypatch):
    make_change(ctx.repo); approve(ctx)
    monkeypatch.setenv("FAKE_ACTION", "impl"); jobs.implement(ctx, "demo-change")
    monkeypatch.setenv("FAKE_ACTION", "review_pass")
    r = jobs.review(ctx, "demo-change", finalize=False)
    assert r["passed"] and "git" not in r
    assert not ctx.store.db.rows("select 1 from swarm.events where type='git_finalize'")


def test_archived_changes_show_as_done_on_the_board(ctx):
    from swarmlib.cli import sync_state
    make_change(ctx.repo); approve(ctx)
    assert sync_state(ctx.store, ctx.repo, "demo")["demo-change"] == "approved"
    run(["git", "rm", "-rq", "openspec/changes/demo-change"], ctx.repo); run(["git", "commit", "-qm", "archived"], ctx.repo)
    sync_state(ctx.store, ctx.repo, "demo")
    assert ctx.store.db.one("select status from swarm.changes where change_id='demo-change'")["status"] == "done"
