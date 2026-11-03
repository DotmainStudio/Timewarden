"""featurelist.json: a generated projection of the OpenSpec changes (never hand-written, deterministic)."""
from __future__ import annotations

import json
from pathlib import Path

from . import changes as ch


def title_of(change_dir: Path) -> str:
    p = change_dir / "proposal.md"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return change_dir.name


def build(repo: Path, statuses: dict[str, str]) -> dict:
    items = []
    for c in ch.list_changes(repo):
        nxt = c.next_task()
        items.append({
            "change": c.change_id,
            "title": title_of(c.path),
            "status": statuses.get(c.change_id, "awaiting_approval"),
            "tasks": {"total": len(c.tasks), "done": c.done},
            "next_task": nxt.task_id if nxt else None,
            # Acceptance criteria are REFERENCES to spec scenarios (text stays in the spec: no duplication).
            "criteria": [s.sid for s in c.scenarios],
            "spec_dir": f"openspec/changes/{c.change_id}/specs",
        })
    return {"generated": True, "source": "openspec/changes", "do_not_edit": "regenerate with `swarm backlog`", "changes": items}


def write(repo: Path, data: dict) -> Path:
    out = repo / "featurelist.json"
    out.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
