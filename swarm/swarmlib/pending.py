"""Pending-work view data: open tasks per change, from the OpenSpec files, with who is assigned."""
from __future__ import annotations

from pathlib import Path

from . import changes as ch


def pending(repo: Path) -> list[dict]:
    out = []
    for c in ch.list_changes(repo):
        for t in c.tasks:
            if not t.done:
                out.append({"change": c.change_id, "task": t.task_id, "group": t.group, "title": t.title, "verification": t.verification})
    return out
