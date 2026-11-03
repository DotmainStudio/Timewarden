"""Spec-first gate and change status. The dispatcher enforces this; agents cannot bypass it."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import changes as ch
from .store import Store

STATUSES = ("draft", "awaiting_approval", "approved", "in_progress", "review", "done", "parked", "needs_attention")


class GateError(RuntimeError):
    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.code = code


def openspec_validate(repo: Path, change_id: str) -> tuple[bool, str]:
    if not shutil.which("openspec"):
        return False, "openspec CLI not installed"
    r = subprocess.run(["openspec", "validate", change_id, "--strict"], cwd=repo, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-600:]


def approval_state(store: Store, project_id: str, change_dir: Path) -> tuple[str, dict | None]:
    """('none'|'valid'|'void', approval). A modified artifact set voids (and records the voiding of) the approval."""
    a = store.active_approval(project_id, change_dir.name)
    if not a:
        return "none", None
    if a["artifact_hash"] != ch.artifact_hash(change_dir):
        store.void_approval(int(a["id"]))
        return "void", a
    return "valid", a


def status_of(store: Store, project_id: str, c: ch.Change, park_after: int = 2, has_active_run: bool = False) -> str:
    if ch.is_complete_plan(c.path):
        return "draft"
    state, _ = approval_state(store, project_id, c.path)
    if state != "valid":
        return "awaiting_approval"
    v = store.latest_verdict(project_id, c.change_id)
    if v and v["passed"] and c.complete:
        return "done"
    if store.failed_verdicts(project_id, c.change_id) >= park_after and not (v and v["passed"]):
        return "parked"
    if c.complete:
        return "review"
    if has_active_run or c.done > 0:
        return "in_progress"
    return "approved"


def require_approved(store: Store, project_id: str, repo: Path, change_id: str) -> ch.Change:
    """Raises GateError unless an approved, unmodified change exists. Used before ANY implementation job."""
    if not ch.valid_change_id(change_id):
        raise GateError(f"invalid change id {change_id!r}", "invalid")
    d = repo / "openspec" / "changes" / change_id
    if not d.is_dir():
        raise GateError(f"no OpenSpec change '{change_id}': run `swarm propose` first (only planning jobs are allowed)", "no_change")
    missing = ch.is_complete_plan(d)
    if missing:
        raise GateError(f"change '{change_id}' is incomplete (missing {', '.join(missing)})", "incomplete")
    state, _ = approval_state(store, project_id, d)
    if state == "none":
        raise GateError(f"change '{change_id}' is awaiting approval: run `swarm approve {change_id}`", "awaiting_approval")
    if state == "void":
        raise GateError(f"artifacts of '{change_id}' were edited after approval: approval voided, approve again", "approval_void")
    return ch.load(d)


def approve(store: Store, project_id: str, repo: Path, change_id: str, note: str = "", validate: bool = True) -> str:
    if not ch.valid_change_id(change_id):
        raise GateError(f"invalid change id {change_id!r}", "invalid")
    d = repo / "openspec" / "changes" / change_id
    if not d.is_dir():
        raise GateError(f"change '{change_id}' does not exist", "no_change")
    missing = ch.is_complete_plan(d)
    if missing:
        raise GateError(f"cannot approve an incomplete change (missing {', '.join(missing)})", "incomplete")
    if validate:
        ok, out = openspec_validate(repo, change_id)
        if not ok:
            raise GateError(f"openspec validate --strict failed: {out}", "invalid_spec")
    h = ch.artifact_hash(d)
    store.record_approval(project_id, change_id, h, note)
    return h
