import os, stat
from pathlib import Path
import pytest
from conftest import ROOT
from swarmlib import runner, verify

FAKE = "sk-ant-oat01-" + "Zx9" * 20


def test_save_token_is_0600_extracts_the_token_and_never_returns_it(tmp_path):
    f = tmp_path / "cfg" / "oauth_token"
    out = verify.save_token(f"banner...\nYour token:\n{FAKE}\nStore it safely\n", f)
    assert out["mode"] == "0o600" and FAKE not in str(out) and out["length"] == len(FAKE)
    assert f.read_text().strip() == FAKE and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert runner.token_file_status(f)["ok"] and runner.load_token(f) == FAKE


def test_save_token_rejects_garbage_and_overwrites_atomically(tmp_path):
    f = tmp_path / "t"
    with pytest.raises(ValueError):
        verify.save_token("no token here", f)
    assert not f.exists()
    verify.save_token(FAKE, f); verify.save_token(FAKE[:-1] + "Q", f)
    assert f.read_text().strip().endswith("Q") and not f.with_suffix(".tmp").exists()


def test_scan_for_token_finds_leaks_in_files_and_text(tmp_path):
    clean, dirty = tmp_path / "a.log", tmp_path / "b.log"
    clean.write_text("nothing"); dirty.write_text(f"oops {FAKE}")
    assert verify.scan_for_token(FAKE, [clean, dirty], ["x", f"y {FAKE}"]) == [str(dirty), "text[1]"]
    assert verify.scan_for_token(FAKE, [clean], ["ok"]) == []


def test_verify_without_token_file_reports_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "TOKEN_FILE", tmp_path / "missing")
    monkeypatch.setattr(runner, "token_file_status", lambda path=tmp_path / "missing": {"ok": False, "reason": "missing"})
    res = verify.verify_docker(None)
    assert res["ok"] is False and "missing" in res["error"]
