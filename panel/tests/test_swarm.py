import pytest
from app import swarm


def test_quota_risk_thresholds():
    assert swarm.quota_risk(None) == "unknown"
    assert [swarm.quota_risk(x) for x in (0.0, 0.59, 0.6, 0.84, 0.85, 1.0)] == ["low", "low", "medium", "medium", "high", "high"]


def test_board_has_all_spec_columns():
    for c in ("awaiting_approval", "approved", "in_progress", "review", "done", "parked"):
        assert c in swarm.BOARD


def test_no_write_endpoints_in_swarm_api():
    from app.main import app
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api/swarm"):
            assert r.methods <= {"GET", "HEAD"}, r.path
