"""Team mode (interactive, tmux). Needs tmux and the Postgres container."""
import json, shutil, subprocess, sys, os
from pathlib import Path
import pytest
from conftest import ROOT, needs_pg, run
from swarmlib import jobs, runner, team

pytestmark = [needs_pg, pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")]
FAKE = str(ROOT / "tests/swarm/fake_team_claude.py")


@pytest.fixture
def ctx(repo, store, tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE", FAKE)
    monkeypatch.setattr(runner, "ROOT", ROOT / "swarm")
    return jobs.Ctx(repo, "demo", store, "local", out_base=tmp_path / "runs")


def test_team_runs_in_tmux_with_flag_and_capped_teammates_and_ingests_events(ctx):
    r = team.start(ctx, "review the change", teammates=9)
    assert r["teammates"] == 5                                              # clamped to the policy cap
    res = team.wait(ctx, r["run_id"], r["session"], r["out_dir"], timeout_s=30, poll=0.5)
    assert res["done"] and res["state"] == "succeeded" and res["teammate_idle_events"] == 2
    info = json.loads((r["out_dir"] / "argv.json").read_text())
    assert info["team_flag"] == "1" and "exactly 5 teammate" in " ".join(info["argv"])
    assert "--setting-sources" in info["argv"] and Path(info["cwd"]).resolve() == ctx.repo.resolve()
    row = ctx.store.db.one("select kind, mode, state from swarm.runs where id=:'i'::bigint", i=r["run_id"])
    assert row == {"kind": "team", "mode": "interactive", "state": "succeeded"}
    types = {e["type"] for e in ctx.store.db.rows("select type from swarm.events where run_id=:'i'::bigint", i=r["run_id"])}
    assert {"team_started", "teammate_idle", "team_task_completed"} <= types
    assert not team.session_alive(r["session"])


def test_team_cap_comes_from_policy_and_minimum_is_one(ctx):
    ctx.policy["team"]["max_teammates"] = 3
    r = team.start(ctx, "x", teammates=4)
    assert r["teammates"] == 3
    team.wait(ctx, r["run_id"], r["session"], r["out_dir"], timeout_s=30, poll=0.5)
    assert team.clamp(0, 5) == 1


def test_team_timeout_stops_the_session(ctx, monkeypatch):
    monkeypatch.setenv("FAKE_TEAM_SLEEP", "60")
    r = team.start(ctx, "x", teammates=2)
    res = team.wait(ctx, r["run_id"], r["session"], r["out_dir"], timeout_s=2, poll=0.5)
    assert res["state"] == "timeout" and not team.session_alive(r["session"])
    assert ctx.store.db.one("select state from swarm.runs where id=:'i'::bigint", i=r["run_id"])["state"] == "timeout"


def test_hook_records_teammate_events(tmp_path):
    env = {**os.environ, "SWARM_OUT": str(tmp_path), "SWARM_ROLE": "leader"}
    for kind, payload in (("teammate_idle", {"teammate_name": "r1"}), ("task_done", {"teammate_name": "r1", "task_subject": "review"})):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "swarm/runner/hooks/swarm_hook.py"), kind], input=json.dumps(payload), capture_output=True, text=True, env=env)
        assert r.returncode == 0
    types = [json.loads(l)["type"] for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert types == ["teammate_idle", "team_task_completed"]
    settings = json.loads((ROOT / "swarm/runner/settings.json").read_text())["hooks"]
    assert "TeammateIdle" in settings and "TaskCompleted" in settings


def test_autotrust_selects_yes_not_the_default_no(tmp_path):
    script = tmp_path / "dialog.sh"
    script.write_text("#!/bin/bash\necho 'Quick safety check: Is this a project you created or one you trust?'\necho ' ❯ No, exit'\necho '   Yes, I trust this folder'\n"
                      "read -rsn3 key; if [ \"$key\" = $'\\x1b[B' ]; then read -rsn1 k2; echo CHOSE_YES; else echo CHOSE_NO; fi\nsleep 2\n")
    script.chmod(0o755)
    name = "swarm-test-trust"
    team.tmux("kill-session", "-t", name)
    team.tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "20", f"bash {script}; sleep 5")
    try:
        assert team.autotrust(name, wait_s=1.0)
        import time; time.sleep(1.0)
        assert "CHOSE_YES" in team.tmux("capture-pane", "-p", "-t", name)[1]
    finally:
        team.tmux("kill-session", "-t", name)


def test_session_without_teammate_activity_is_a_failure(ctx, monkeypatch, tmp_path):
    quiet = tmp_path / "quiet.py"; quiet.write_text("#!/usr/bin/env python3\nimport os,time\ntime.sleep(0.3)\n"); quiet.chmod(0o755)
    monkeypatch.setenv("SWARM_CLAUDE", str(quiet))
    r = team.start(ctx, "x", teammates=2)
    res = team.wait(ctx, r["run_id"], r["session"], r["out_dir"], timeout_s=30, poll=0.5)
    assert res["state"] == "failed"
