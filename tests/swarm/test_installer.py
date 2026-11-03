"""Harness installer: analysis, scope question, dry run, idempotence, foreign files, health script, cleanup, static-doc lint."""
import json, os, re, subprocess, sys
from pathlib import Path
import pytest
from conftest import ROOT, run

INST = [sys.executable, "-I", str(ROOT / "scripts/install_harness.py")]


def inst(*args, home=None, **kw):
    env = {**os.environ, **({"HOME": str(home)} if home else {})}
    return subprocess.run([*INST, *args], capture_output=True, text=True, env=env, **kw)


@pytest.fixture
def mixed(repo):
    (repo / "scripts" / "health.sh").unlink(); run(["git", "commit", "-qam", "rm health"], repo)
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\""}}))
    (repo / "tests").mkdir(); (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (repo / ".agent-memory" / "project.yaml").write_text("project_id: demo\nmemory_dataset: demo-knowledge\nsources:\n  - docs/agent-memory/**/*.md\nexclude:\n  - '**/.env*'\n")
    return repo


def test_scope_is_required_and_asks(mixed):
    r = inst("install", str(mixed))
    assert r.returncode == 3 and "ASK_SCOPE" in r.stderr and "globally" in r.stderr
    assert not (mixed / "ARCHITECTURE.md").exists()


def test_analyze_reports_stack_runners_and_proposes_agents(mixed):
    d = json.loads(inst("analyze", str(mixed)).stdout)
    assert {r["name"] for r in d["test_runners"]} >= {"node", "python"}
    assert set(d["proposed_agents"]) == {"leader", "explorer", "implementer", "reviewer", "gitops"}
    assert d["proposed_agents"]["explorer"]["model"] == "haiku" and d["memory_installed"] and d["project_id"] == "demo"


def test_dry_run_writes_nothing_then_apply_then_idempotent(mixed):
    r = inst("install", str(mixed), "--scope", "repo")
    assert "DRY RUN" in r.stdout and "add    ARCHITECTURE.md" in r.stdout
    assert not (mixed / "ARCHITECTURE.md").exists() and not (mixed / ".claude/agents").exists()
    r = inst("install", str(mixed), "--scope", "repo", "--apply"); assert r.returncode == 0
    for f in ("AGENTS.md", "ARCHITECTURE.md", "progress/current.md", "progress/history.md", "scripts/health.sh", ".claude/agents/reviewer.md"):
        assert (mixed / f).exists(), f
    assert "@AGENTS.md" in (mixed / "CLAUDE.md").read_text() if (mixed / "CLAUDE.md").exists() else False
    snap = {p: p.read_text() for p in mixed.rglob("*") if p.is_file() and ".git/" not in str(p)}
    assert inst("install", str(mixed), "--scope", "repo", "--apply").stdout.strip() == "no changes"
    assert snap == {p: p.read_text() for p in mixed.rglob("*") if p.is_file() and ".git/" not in str(p)}


def test_foreign_agents_md_untouched_protocol_inline(mixed):
    (mixed / "AGENTS.md").write_text("# foreign rules\nkeep me\n"); (mixed / "CLAUDE.md").write_text("# mine\n")
    inst("install", str(mixed), "--scope", "repo", "--apply")
    assert (mixed / "AGENTS.md").read_text() == "# foreign rules\nkeep me\n"
    cm = (mixed / "CLAUDE.md").read_text()
    assert cm.startswith("# mine") and "Definition of done" in cm and "@AGENTS.md" not in cm
    assert inst("install", str(mixed), "--scope", "repo", "--apply").stdout.strip() == "no changes"


def test_existing_files_are_never_overwritten(mixed):
    (mixed / "ARCHITECTURE.md").write_text("my architecture\n"); (mixed / "scripts" / "health.sh").write_text("#!/bin/sh\nexit 0\n")
    r = inst("install", str(mixed), "--scope", "repo", "--apply")
    assert "skip   ARCHITECTURE.md" in r.stdout and (mixed / "ARCHITECTURE.md").read_text() == "my architecture\n"
    assert (mixed / "scripts/health.sh").read_text() == "#!/bin/sh\nexit 0\n"


def test_health_script_runs_both_suites_and_fails_if_either_fails(mixed):
    inst("install", str(mixed), "--scope", "repo", "--apply")
    h = mixed / "scripts" / "health.sh"
    assert subprocess.run(["bash", str(h)], capture_output=True).returncode == 0
    (mixed / "tests" / "test_x.py").write_text("def test_x():\n    assert False\n")
    r = subprocess.run(["bash", str(h)], capture_output=True, text=True)
    assert r.returncode != 0 and "FAILED: python" in r.stdout
    (mixed / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (mixed / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(1)\""}}))
    r = subprocess.run(["bash", str(h)], capture_output=True, text=True)
    assert r.returncode != 0 and "FAILED: node" in r.stdout


def test_memory_sources_extended_without_touching_dataset(mixed):
    inst("install", str(mixed), "--scope", "repo", "--apply")
    y = (mixed / ".agent-memory/project.yaml").read_text()
    assert "ARCHITECTURE.md" in y and "progress/history.md" in y and "progress/current.md" in y and "exploration_*" in y
    assert "memory_dataset: demo-knowledge" in y and y.count("ARCHITECTURE.md") == 1


def test_global_scope_puts_roles_in_home_not_repo(mixed, tmp_path):
    home = tmp_path / "home"; home.mkdir()
    r = inst("install", str(mixed), "--scope", "global", "--apply", home=home)
    assert r.returncode == 0 and (home / ".claude/agents/implementer.md").exists()
    assert not (mixed / ".claude/agents").exists() and (mixed / "ARCHITECTURE.md").exists()


def test_cleanup_lists_then_moves_to_backup_never_deletes(mixed):
    (mixed / "featurelist.json").write_text('{"features": []}'); (mixed / "claude-progress.txt").write_text("old"); (mixed / "exploration_a.md").write_text("n")
    r = inst("install", str(mixed), "--scope", "repo", "--cleanup")
    assert "move   featurelist.json" in r.stdout and (mixed / "featurelist.json").exists()
    inst("install", str(mixed), "--scope", "repo", "--cleanup", "--apply")
    assert not (mixed / "featurelist.json").exists()
    bk = list((mixed / ".agent-memory/legacy-backup").glob("*/featurelist.json"))
    assert len(bk) == 1 and bk[0].read_text() == '{"features": []}'
    assert (mixed / ".agent-memory/legacy-backup").glob("*/claude-progress.txt")


def test_generated_featurelist_is_not_legacy(mixed):
    (mixed / "featurelist.json").write_text('{"generated": true, "changes": []}')
    assert json.loads(inst("analyze", str(mixed)).stdout)["legacy"] == []


def test_roles_are_generic_and_readonly_roles_have_no_write_tools(mixed):
    inst("install", str(mixed), "--scope", "repo", "--apply")
    for role in ("explorer", "reviewer"):
        front = (mixed / f".claude/agents/{role}.md").read_text().split("---")[1]
        tools = re.search(r"tools: (.*)", front).group(1)
        assert not re.search(r"\b(Edit|Write)\b", tools)
    assert "model: haiku" in (mixed / ".claude/agents/explorer.md").read_text()


DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b|\b[0-9a-f]{7,40}\b")
BRANCH = re.compile(r"\b(feat|fix|chore|spec|change)/[\w-]+")


def test_static_documents_have_no_dates_ids_or_branch_names():
    docs = list((ROOT / "templates/harness").rglob("*.md")) + [ROOT / "swarm/policy.yaml"]
    for d in docs:
        t = d.read_text()
        assert not DATE.search(t), (d, DATE.search(t).group(0))
        assert not BRANCH.search(t), (d, BRANCH.search(t).group(0))


def test_monorepo_detection_and_health_per_directory(repo):
    (repo / "scripts" / "health.sh").unlink(); run(["git", "commit", "-qam", "rm"], repo)
    be, fe = repo / "backend", repo / "frontend"
    (be / "tests").mkdir(parents=True); (be / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    (be / "pytest.ini").write_text("[pytest]\n"); (be / "poetry.lock").write_text("")
    fe.mkdir(); (fe / "package.json").write_text(json.dumps({"scripts": {"build": "x"}, "devDependencies": {"typescript": "5"}})); (fe / "tsconfig.json").write_text("{}")
    (repo / "node_modules" / "pkg").mkdir(parents=True); (repo / "node_modules" / "pkg" / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}))
    d = json.loads(inst("analyze", str(repo)).stdout)
    got = {r["name"]: r for r in d["test_runners"]}
    assert got["python:backend"]["cmd"] == "poetry run pytest -q" and got["python:backend"]["dir"] == "backend"
    assert got["typecheck:frontend"]["cmd"] == "npx tsc --noEmit"
    assert not any("node_modules" in n for n in got)
    inst("install", str(repo), "--scope", "repo", "--apply")
    h = (repo / "scripts" / "health.sh").read_text()
    assert "cd backend && poetry run pytest -q" in h and "cd frontend && npx tsc --noEmit" in h


def test_monorepo_health_fails_if_a_subdirectory_check_fails(repo):
    (repo / "scripts" / "health.sh").unlink(); run(["git", "commit", "-qam", "rm"], repo)
    be = repo / "backend"; (be / "tests").mkdir(parents=True); (be / "pytest.ini").write_text("[pytest]\n")
    (be / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    inst("install", str(repo), "--scope", "repo", "--apply")
    h = repo / "scripts" / "health.sh"
    assert subprocess.run(["bash", str(h)], capture_output=True).returncode == 0
    (be / "tests" / "test_a.py").write_text("def test_a():\n    assert False\n")
    r = subprocess.run(["bash", str(h)], capture_output=True, text=True)
    assert r.returncode != 0 and "FAILED: python:backend" in r.stdout
