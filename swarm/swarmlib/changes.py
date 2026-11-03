"""Reads an OpenSpec change directory: artifacts, tasks, scenarios and the approval hash."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

CHECK = re.compile(r"^- \[( |x|X)\] (\d+\.\d+) (.*)$")
GROUP = re.compile(r"^## (\d+)\. (.*)$")
VERIF = re.compile(r"\(verification:\s*(.*?)\)\s*$")
CMD = re.compile(r"`([^`]+)`")
SCEN = re.compile(r"^#### Scenario:\s*(.+?)\s*$")
REQ = re.compile(r"^### Requirement:\s*(.+?)\s*$")
CHANGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


@dataclass
class Task:
    task_id: str
    title: str
    done: bool
    group: str = ""
    verification: str = ""

    @property
    def command(self) -> str | None:
        """A backticked command inside the verification clause is machine-checkable."""
        m = CMD.search(self.verification)
        return m.group(1) if m else None


@dataclass
class Scenario:
    sid: str
    capability: str
    requirement: str
    name: str


@dataclass
class Change:
    change_id: str
    path: Path
    tasks: list[Task] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(t.done for t in self.tasks)

    @property
    def complete(self) -> bool:
        return bool(self.tasks) and all(t.done for t in self.tasks)

    def next_task(self) -> Task | None:
        return next((t for t in self.tasks if not t.done), None)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def valid_change_id(cid: str) -> bool:
    return bool(CHANGE_ID.match(cid))


def parse_tasks(text: str) -> list[Task]:
    out, group = [], ""
    for line in text.splitlines():
        g = GROUP.match(line)
        if g:
            group = g.group(2).strip()
            continue
        m = CHECK.match(line)
        if m:
            body = m.group(3).strip()
            v = VERIF.search(body)
            out.append(Task(m.group(2), VERIF.sub("", body).strip(), m.group(1) in "xX", group, v.group(1) if v else ""))
    return out


def parse_scenarios(cap: str, text: str) -> list[Scenario]:
    out, req = [], ""
    for line in text.splitlines():
        r = REQ.match(line)
        if r:
            req = r.group(1)
        s = SCEN.match(line)
        if s:
            out.append(Scenario(f"{cap}/{slug(req)}/{slug(s.group(1))}", cap, req, s.group(1)))
    return out


def load(change_dir: Path) -> Change:
    c = Change(change_dir.name, change_dir)
    t = change_dir / "tasks.md"
    if t.exists():
        c.tasks = parse_tasks(t.read_text(encoding="utf-8"))
    for spec in sorted((change_dir / "specs").glob("*/spec.md")):
        c.scenarios += parse_scenarios(spec.parent.name, spec.read_text(encoding="utf-8"))
    return c


def planning_files(change_dir: Path) -> list[Path]:
    files = [change_dir / n for n in ("proposal.md", "design.md", "tasks.md") if (change_dir / n).exists()]
    return files + sorted((change_dir / "specs").glob("**/*.md"))


def artifact_hash(change_dir: Path) -> str:
    """Hash of the planning artifacts. Task checkboxes are normalised so ticking a task does NOT void the approval."""
    h = hashlib.sha256()
    for f in planning_files(change_dir):
        text = f.read_text(encoding="utf-8")
        if f.name == "tasks.md":
            text = re.sub(r"^- \[[xX]\]", "- [ ]", text, flags=re.M)
        h.update(f.relative_to(change_dir).as_posix().encode() + b"\0" + text.encode() + b"\0")
    return h.hexdigest()


def is_complete_plan(change_dir: Path) -> list[str]:
    """Returns what is missing for a change to be approvable (empty list = ok)."""
    miss = []
    for n in ("proposal.md", "tasks.md"):
        if not (change_dir / n).exists():
            miss.append(n)
    if not list((change_dir / "specs").glob("*/spec.md")):
        miss.append("specs/*/spec.md")
    return miss


def list_changes(repo: Path) -> list[Change]:
    base = repo / "openspec" / "changes"
    if not base.exists():
        return []
    return [load(p) for p in sorted(base.iterdir()) if p.is_dir() and p.name != "archive" and not p.name.startswith(".")]
