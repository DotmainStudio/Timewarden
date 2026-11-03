"""memory_heal: budget, quota, branch and attempt gating, free repairs, report-only findings. All commands are scripted fakes."""
import json, sys, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import memory_heal as mh  # noqa: E402

GOOD_PS = "\n".join(f"{n}|Up 2 hours (healthy)" for n in [*mh.STACK, mh.PANEL_CONTAINER])


class FakeSh:
    """Scripted command runner; records every argv. Override responses by substring of the joined command."""
    def __init__(self, **over):
        self.calls, self.over = [], over
        self.base = {"docker ps": (0, GOOD_PS), "8017/health": (0, "ok"), "quota": (0, "0.10"), "tmux list-sessions": (1, ""),
                     "symbolic-ref": (0, "origin/main"), "branch --show-current": (0, "main"), "status --porcelain": (0, ""),
                     "sync_markdown.py": (0, "project=demo: new=0, changed=0, retry=0, deleted=0"), "api/kb": (0, json.dumps({"datasets": []}))}

    def __call__(self, argv, cwd=None, timeout=120):
        cmd = " ".join(str(a) for a in argv)
        self.calls.append(cmd)
        for table in (self.over, self.base):
            for key, val in table.items():
                if key in cmd or (key == "quota" and "quota_utilization" in cmd):
                    return val(cmd) if callable(val) else val
        return (0, "")

    def ran(self, needle):
        return [c for c in self.calls if needle in c]


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "demo"; (r / ".agent-memory").mkdir(parents=True); (r / ".agent-memory" / "project.yaml").write_text("project_id: demo\n")
    return r


def healer(tmp_path, sh, now=None, repo=None, dry=False, **cfg_over):
    cfg = mh.merge(mh.DEFAULTS, cfg_over)
    cfg["repos"] = [str(repo)] if repo else []
    cfg["notify"] = False
    st = mh.State(tmp_path / "state.json", now=now or time.time)
    return mh.Healer(cfg, st, sh=sh, dry_run=dry)


PENDING = "project=demo: new=2, changed=1, retry=0, deleted=0\n  [new] docs/agent-memory/a.md\n  [new] docs/agent-memory/b.md\n  [changed] openspec/specs/x/spec.md"


# -- config ---------------------------------------------------------------------------------
def test_defaults_are_conservative():
    c = mh.load_config(Path("/nonexistent"))
    b = c["budget"]
    assert (b["max_syncs_per_day"], b["max_docs_per_sync"], b["min_hours_between_syncs"]) == (2, 8, 6) and c["diagnose"]["enabled"] is False


def test_budgets_can_be_lowered_but_never_raised_past_hard_caps(tmp_path):
    f = tmp_path / "heal.yaml"
    f.write_text("budget:\n  max_syncs_per_day: 99\n  max_docs_per_sync: 500\n  quota_pause_at: 2\n  min_hours_between_syncs: 0\n")
    b = mh.load_config(f)["budget"]
    assert b["max_syncs_per_day"] == 6 and b["max_docs_per_sync"] == 20 and b["quota_pause_at"] <= 0.95 and b["min_hours_between_syncs"] >= 1
    f.write_text("budget:\n  max_syncs_per_day: 1\n")
    assert mh.load_config(f)["budget"]["max_syncs_per_day"] == 1


def test_state_resets_counters_on_a_new_day(tmp_path):
    t = [1_700_000_000.0]
    s = mh.State(tmp_path / "s.json", now=lambda: t[0]); s.data["syncs_today"] = 2; s.bump("attempts", "x"); s.save()
    t[0] += 86400 * 1.5
    s2 = mh.State(tmp_path / "s.json", now=lambda: t[0])
    assert s2.data["syncs_today"] == 0 and s2.data["attempts"] == {}


# -- infra (free) -----------------------------------------------------------------------------
def test_unhealthy_container_is_restarted_without_touching_volumes(tmp_path):
    sh = FakeSh(**{"docker ps": (0, GOOD_PS.replace("agents_cognee_api-1|Up 2 hours (healthy)", "agents_cognee_api-1|Up 2 hours (unhealthy)"))})
    h = healer(tmp_path, sh); h.check_infra()
    ups = sh.ran("dc.sh up -d")
    assert len(ups) == 1 and ups[0].endswith("agents_cognee_api")
    assert not sh.ran("down") and not sh.ran("-v")


def test_stopped_or_missing_container_and_panel_and_observer(tmp_path):
    ps = "\n".join(f"{n}|Up 1 hour (healthy)" for n in mh.STACK) + f"\n{mh.PANEL_CONTAINER}|Exited (1) 2 minutes ago"
    sh = FakeSh(**{"docker ps": (0, ps), "8017/health": (7, "")})
    h = healer(tmp_path, sh); h.check_infra()
    assert sh.ran("compose") and sh.ran("mm_app") and sh.ran("observer.sh")


def test_healthy_stack_does_nothing(tmp_path):
    sh = FakeSh(); h = healer(tmp_path, sh); h.check_infra()
    assert not sh.ran("up -d") and not sh.ran("observer.sh") and h.events == []


def test_restart_loop_is_stopped_after_the_daily_limit_with_one_alert(tmp_path):
    sh = FakeSh(**{"docker ps": (0, GOOD_PS.replace("agents_postgres-1|Up 2 hours (healthy)", "agents_postgres-1|Exited (1) now"))})
    h = healer(tmp_path, sh)
    for _ in range(6):
        h.check_infra()
    assert len(sh.ran("up -d agents_postgres")) == h.cfg["budget"]["max_restarts_per_day"]
    assert len([e for e in h.events if e["event"] == "alert"]) == 1


def test_docker_down_only_alerts(tmp_path):
    sh = FakeSh(**{"docker ps": (1, "Cannot connect to the Docker daemon")})
    h = healer(tmp_path, sh); h.check_infra()
    assert [e["key"] for e in h.events if e["event"] == "alert"] == ["docker-down"] and not sh.ran("up -d")


def test_dry_run_acts_on_nothing(tmp_path, repo):
    sh = FakeSh(**{"docker ps": (0, "x|Exited"), "sync_markdown.py": (0, PENDING)})
    h = healer(tmp_path, sh, repo=repo, dry=True); h.run()
    assert not sh.ran("up -d") and not sh.ran("--apply") and not sh.ran("update swarm.runs") and not sh.ran("kill-session")
    assert not (tmp_path / "state.json").exists()


# -- swarm (free) -------------------------------------------------------------------------------
def test_stuck_runs_are_marked_failed_and_old_team_sessions_closed(tmp_path):
    now = 1_800_000_000.0
    sh = FakeSh(**{"update swarm.runs": (0, "41\n42\n"), "tmux list-sessions": (0, f"swarm-team-demo-1 {int(now) - 5 * 3600}\nswarm-team-demo-2 {int(now) - 60}\nother {int(now) - 99999}")})
    h = healer(tmp_path, sh, now=lambda: now); h.check_swarm()
    assert any(e["event"] == "stuck_runs_closed" and e["runs"] == ["41", "42"] for e in h.events)
    kills = sh.ran("kill-session")
    assert len(kills) == 1 and "swarm-team-demo-1" in kills[0]


# -- sync: the part that spends tokens -------------------------------------------------------------
def sync_sh(**over):
    base = {"sync_markdown.py": lambda cmd: (0, "  indexed   docs/agent-memory/a.md\n  indexed   docs/agent-memory/b.md\n  indexed   openspec/specs/x/spec.md\n") if "--apply" in cmd else (0, PENDING)}
    base.update(over)
    return FakeSh(**base)


def test_sync_runs_within_caps_and_records_the_budget(tmp_path, repo):
    sh = sync_sh(); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    apply = sh.ran("--apply")
    assert len(apply) == 1 and "--max-docs 8" in apply[0]
    assert h.state.data["syncs_today"] == 1 and any(e["event"] == "sync_done" and e["indexed"] == 3 for e in h.events)
    assert not sh.ran("forget") and not sh.ran("delete") and not sh.ran("down -v")


def test_nothing_pending_costs_nothing(tmp_path, repo):
    sh = FakeSh(); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    assert not sh.ran("--apply") and h.state.data["syncs_today"] == 0


def test_minimum_hours_between_syncs_and_daily_budget(tmp_path, repo):
    t = [1_800_000_000.0]; sh = sync_sh(); h = healer(tmp_path, sh, now=lambda: t[0], repo=repo)
    h.check_sync(str(repo))
    t[0] += 3600; h.check_sync(str(repo))                         # 1 h later: below the 6 h minimum
    assert len(sh.ran("--apply")) == 1 and any("minimum" in e.get("reason", "") for e in h.events)
    t[0] += 7 * 3600; h.check_sync(str(repo))                     # allowed: 2nd of 2
    t[0] += 7 * 3600; h.check_sync(str(repo))                     # daily budget (2) used
    assert len(sh.ran("--apply")) == 2 and any("daily sync budget" in e.get("reason", "") for e in h.events)


@pytest.mark.parametrize("quota,expect_sync", [("0.69", True), ("0.70", False), ("0.95", False), ("-1", True)])
def test_quota_threshold_pauses_token_spending_but_unknown_proceeds_within_caps(tmp_path, repo, quota, expect_sync):
    sh = sync_sh(quota=(0, quota)); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    assert bool(sh.ran("--apply")) is expect_sync


def test_only_the_default_branch_with_clean_tracked_files_is_indexed(tmp_path, repo):
    sh = sync_sh(**{"branch --show-current": (0, "feature/x")}); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    assert not sh.ran("--apply") and any("not 'main'" in e.get("reason", "") for e in h.events)
    sh = sync_sh(**{"status --porcelain": (0, " M docs/agent-memory/a.md")}); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    assert not sh.ran("--apply") and len([e for e in h.events if e["event"] == "alert"]) == 1
    h.check_sync(str(repo)); assert len([e for e in h.events if e["event"] == "alert"]) == 1     # same alert not repeated


def test_observer_down_skips_the_sync(tmp_path, repo):
    sh = sync_sh(**{"8017/health": (7, "")}); h = healer(tmp_path, sh, repo=repo); h.check_sync(str(repo))
    assert not sh.ran("--apply")


def test_failing_documents_stop_after_their_attempts_and_raise_one_alert(tmp_path, repo):
    t = [1_800_000_000.0]
    sh = sync_sh(**{"sync_markdown.py": lambda cmd: (1, "  ERROR docs/agent-memory/a.md: boom\n") if "--apply" in cmd else (0, PENDING)})
    h = healer(tmp_path, sh, now=lambda: t[0], repo=repo, budget={"max_syncs_per_day": 6, "min_hours_between_syncs": 1})
    for _ in range(6):
        h.check_sync(str(repo)); t[0] += 2 * 3600
    assert len(sh.ran("--apply")) == h.cfg["budget"]["max_attempts_per_item"]
    assert len([e for e in h.events if e["event"] == "alert" and e["key"].startswith("persistent")]) == 1


def test_repo_without_a_contract_is_skipped(tmp_path):
    sh = FakeSh(); h = healer(tmp_path, sh); h.check_sync(str(tmp_path / "nope"))
    assert not sh.calls and h.events[0]["event"] == "skip"


# -- report-only findings ------------------------------------------------------------------------------
def test_orphans_are_reported_once_and_never_deleted(tmp_path):
    kb = {"datasets": [{"name": "demo-knowledge", "flags": [{"level": "warn", "code": "orphans", "text": "1 document(s) in Cognee with no registry entry"}]}]}
    sh = FakeSh(**{"api/kb": (0, json.dumps(kb))}); h = healer(tmp_path, sh)
    h.check_findings(); h.check_findings()
    assert len([e for e in h.events if e["event"] == "alert"]) == 1
    assert not sh.ran("forget") and not sh.ran("DELETE") and not sh.ran("delete")


def test_notification_is_deduplicated_per_day(tmp_path):
    sh = FakeSh(); h = healer(tmp_path, sh); h.cfg["notify"] = True
    h.alert("k", "problem"); h.alert("k", "problem")
    if sys.platform == "darwin":
        assert len(sh.ran("osascript")) == 1


# -- optional diagnosis ----------------------------------------------------------------------------------
def test_diagnosis_is_off_by_default_and_makes_no_model_call(tmp_path):
    sh = FakeSh(); h = healer(tmp_path, sh); h.state.data["alerts"]["persistent:demo"] = 1; h.maybe_diagnose()
    assert not sh.ran("claude")


def test_diagnosis_when_enabled_is_read_only_lightest_model_once_per_day_and_quota_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(mh, "HEAL_DIR", tmp_path / "heal")
    (tmp_path / "heal").mkdir()
    sh = FakeSh(**{"claude -p": (0, "likely cause...")}); h = healer(tmp_path, sh, diagnose={"enabled": True}); h.state.data["alerts"]["persistent:demo"] = 1
    h.maybe_diagnose(); h.maybe_diagnose()
    c = sh.ran("claude -p")
    assert len(c) == 1 and "--model haiku" in c[0] and "--allowedTools Read,Grep" in c[0] and '--setting-sources ' in c[0]
    sh2 = FakeSh(**{"quota": (0, "0.9"), "claude -p": (0, "x")}); h2 = healer(tmp_path, sh2, diagnose={"enabled": True}); h2.state.data["alerts"]["persistent:demo"] = 1
    h2.maybe_diagnose(); assert not sh2.ran("claude -p")


# -- cli ---------------------------------------------------------------------------------------------------
def test_add_repo_validates_and_is_idempotent(tmp_path, monkeypatch, repo, capsys):
    monkeypatch.setattr(mh, "CONFIG", tmp_path / "cfg" / "heal.yaml")
    assert mh.main(["add-repo", str(repo)]) == 0 and mh.main(["add-repo", str(repo)]) == 0
    assert mh.load_config(tmp_path / "cfg" / "heal.yaml")["repos"] == [str(repo.resolve())]
    assert mh.main(["add-repo", str(tmp_path)]) == 2


def test_config_written_by_add_repo_is_readable_without_pyyaml(tmp_path, monkeypatch, repo):
    monkeypatch.setattr(mh, "CONFIG", tmp_path / "cfg" / "heal.yaml")
    mh.main(["add-repo", str(repo)])
    f = tmp_path / "cfg" / "heal.yaml"
    f.write_text(f.read_text() + "budget:\n  max_syncs_per_day: 1\n  quota_pause_at: 0.5\n")
    monkeypatch.setenv("TIMEWARDEN_NO_PYYAML", "1")                 # force the stdlib parser
    c = mh.load_config(f)
    assert c["repos"] == [str(repo.resolve())] and c["budget"]["max_syncs_per_day"] == 1 and c["budget"]["quota_pause_at"] == 0.5
