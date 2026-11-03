"""6.1: sync dry-run lists exactly the expected harness documents; ephemeral state is never indexed."""
from pathlib import Path
from conftest import ROOT
import miniyaml, sync_markdown as sm


def test_sources_include_architecture_and_history_but_not_current_or_exploration(tmp_path):
    cfg = miniyaml.load((ROOT / "templates/project.yaml.tmpl").read_text().replace("__PROJECT_ID__", "demo").replace("__LANG__", "en"))
    for rel in ("ARCHITECTURE.md", "progress/history.md", "progress/current.md", "exploration_x.md", "docs/agent-memory/project.md", "README.md"):
        f = tmp_path / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("# x\n")
    got = set(sm.enumerate_docs(tmp_path, cfg))
    assert got == {"ARCHITECTURE.md", "progress/history.md", "docs/agent-memory/project.md"}


def test_swarm_adds_no_dataset_beyond_knowledge_and_sessions():
    cfg = miniyaml.load((ROOT / "templates/project.yaml.tmpl").read_text().replace("__PROJECT_ID__", "demo").replace("__LANG__", "en"))
    assert sorted(k for k in cfg if k.endswith("_dataset")) == ["memory_dataset", "session_dataset"]
    assert cfg["policy"]["cross_project_recall"] is False
