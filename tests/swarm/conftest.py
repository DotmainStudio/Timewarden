import os, subprocess, sys, uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "swarm"))
sys.path.insert(0, str(ROOT / "swarm" / "runner" / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
from swarmlib import pg  # noqa: E402
from swarmlib.store import Store  # noqa: E402


def docker_pg_up() -> bool:
    try:
        return subprocess.run(["docker", "exec", pg.Pg().container, "true"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


needs_pg = pytest.mark.skipif(not docker_pg_up(), reason="stack Postgres container not running")


@pytest.fixture(scope="session")
def scratch_db():
    """A throwaway database with the swarm schema and both roles; dropped afterwards."""
    name = "swarm_test_" + uuid.uuid4().hex[:8]
    adm = pg.admin("postgres")
    adm.execute(f"create database {name}")
    try:
        pg.apply_schema(pg.admin(name))
        yield name
    finally:
        adm.execute(f"drop database if exists {name} with (force)")


@pytest.fixture
def store(scratch_db):
    s = Store(pg.Pg(db=scratch_db, user=pg.WRITER))
    pg.admin(scratch_db).execute("truncate swarm.runs, swarm.events, swarm.approvals, swarm.verdicts, swarm.recalls, swarm.health, swarm.tasks, swarm.changes, swarm.projects restart identity cascade")
    return s


def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=kw.pop("check", True), **kw)


@pytest.fixture
def repo(tmp_path):
    """Scratch git repo with a health script, project.yaml and one OpenSpec change (not yet approved)."""
    r = tmp_path / "proj"
    (r / "scripts").mkdir(parents=True)
    (r / ".agent-memory").mkdir()
    (r / ".agent-memory" / "project.yaml").write_text("project_id: demo\nmemory_dataset: demo-knowledge\n")
    (r / "scripts" / "health.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    run(["git", "init", "-q", "-b", "main"], r)
    run(["git", "config", "user.email", "t@t.dev"], r); run(["git", "config", "user.name", "t"], r)
    run(["git", "add", "-A"], r); run(["git", "commit", "-q", "-m", "init"], r)
    return r


def make_change(repo: Path, cid="demo-change", tasks=None, scen=True, commit=True):
    d = repo / "openspec" / "changes" / cid
    (d / "specs" / "demo").mkdir(parents=True, exist_ok=True)
    (d / "proposal.md").write_text("# Demo change\n\n## Why\nx\n")
    (d / "specs" / "demo" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: Demo works\nThe system SHALL work.\n\n"
        + ("#### Scenario: It works\n- **WHEN** x\n- **THEN** y\n" if scen else ""))
    (d / "tasks.md").write_text(tasks or "# Tasks\n\n## 1. Core\n\n- [ ] 1.1 Create marker (verification: `test -f marker.txt`)\n- [ ] 1.2 Create second marker (verification: `test -f marker2.txt`)\n")
    if commit:
        run(["git", "add", "-A"], repo); run(["git", "commit", "-q", "-m", "add change"], repo)
    return d
