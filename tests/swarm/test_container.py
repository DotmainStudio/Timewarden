"""Runner image isolation (spec: swarm-execution). Skipped if the image is not built (swarm/build_runner.sh)."""
import subprocess
from pathlib import Path
import pytest
from conftest import ROOT
from swarmlib import runner

IMAGE = runner.IMAGE
have = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(not have, reason="swarm-runner image not built")


def sh_in_container(tmp_path, cmd, readonly=False, env=None):
    wt = tmp_path / "wt"; wt.mkdir(exist_ok=True); out = tmp_path / "out"; out.mkdir(exist_ok=True)
    job = runner.Job("implementer", "p", wt, out, "haiku", "low", 1, 30, ["Read"], readonly=readonly, name=f"swarm-test-{tmp_path.name[-8:]}")
    argv = runner.docker_argv(job, IMAGE)
    cut = argv.index(IMAGE)
    full = argv[:cut] + ["--entrypoint", "sh", IMAGE, "-c", cmd]
    return subprocess.run(full, capture_output=True, text=True, env={**__import__("os").environ, "CLAUDE_CODE_OAUTH_TOKEN": "dummy", **(env or {})}, timeout=60)


def test_pinned_version_matches_lock():
    lock = (ROOT / "config/versions.lock").read_text()
    want = [l for l in lock.splitlines() if l.startswith("claude_code")][0].split("=")[1].split()[0]
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "claude", IMAGE, "--version"], capture_output=True, text=True)
    assert want in r.stdout, (want, r.stdout)


def test_non_root_no_capabilities_no_socket_and_no_other_projects(tmp_path):
    r = sh_in_container(tmp_path, "id -u; grep CapEff /proc/self/status; ls /var/run/docker.sock 2>&1; ls /Users 2>&1; ls /home; env | grep -c ANTHROPIC")
    lines = r.stdout.splitlines()
    assert lines[0] == "10001"
    assert lines[1].split()[-1] == "0000000000000000"
    assert "No such file" in r.stdout and "docker.sock" in r.stdout
    assert r.stdout.count("No such file") >= 2            # /Users does not exist: another project's directory is unreachable
    assert lines[-1] == "0"


def test_only_the_worktree_is_writable_and_readonly_roles_cannot_write(tmp_path):
    assert sh_in_container(tmp_path, "touch /work/x && echo ok").stdout.strip() == "ok"
    assert (tmp_path / "wt" / "x").exists()
    r = sh_in_container(tmp_path, "touch /work/y", readonly=True)
    assert r.returncode != 0 and "Read-only" in r.stderr
    r = sh_in_container(tmp_path, "touch /etc/y 2>&1; touch /opt/swarm/y 2>&1")
    assert "denied" in r.stdout.lower()


def test_entrypoint_inside_container_refuses_api_key_and_missing_token(tmp_path):
    base = ["docker", "run", "--rm", "--cap-drop", "ALL", "--user", "10001:10001", "-e", "ANTHROPIC_API_KEY=x", "-e", "CLAUDE_CODE_OAUTH_TOKEN=t", IMAGE, "--version"]
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode == 64 and "subscription" in r.stderr
    r = subprocess.run(["docker", "run", "--rm", IMAGE, "--version"], capture_output=True, text=True)
    assert r.returncode == 65


def test_guard_hook_runs_inside_container(tmp_path):
    r = subprocess.run(["docker", "run", "--rm", "-i", "-e", "SWARM_OUT=/tmp", "--entrypoint", "python3", IMAGE, "-I", "/opt/swarm/swarm_hook.py", "pre"],
                       input='{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}', capture_output=True, text=True)
    assert r.returncode == 2 and ("must not push" in r.stderr or "main branch" in r.stderr)
