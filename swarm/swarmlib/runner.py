"""Builds and supervises one `claude -p` job: Docker (default) or `local` (dev/tests, host login). Enforces limits."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import policy as pol

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"
IMAGE = os.environ.get("SWARM_RUNNER_IMAGE", "swarm-runner:local")
TOKEN_FILE = Path(os.environ.get("SWARM_TOKEN_FILE", str(Path.home() / ".config" / "swarm" / "oauth_token")))
TOKEN_TTL_DAYS = 365
WARN_DAYS = 30


class CredentialError(RuntimeError):
    pass


def check_env(env: dict) -> None:
    """Refuses to start when a variable that outranks the subscription is present (before any request)."""
    for v in FORBIDDEN_ENV:
        if env.get(v):
            raise CredentialError(f"{v} is set and would take precedence over the subscription token; unset it. "
                                  "This swarm runs on the subscription only (no API billing).")


def token_file_status(path: Path = TOKEN_FILE) -> dict:
    """Verifies the token file is owner-only and reports the days left before the one-year expiry (no value is read into logs)."""
    if not path.exists():
        return {"ok": False, "reason": "missing"}
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return {"ok": False, "reason": f"permissions {oct(mode)} too open (must be 0600)"}
    age = (time.time() - path.stat().st_mtime) / 86400
    left = int(TOKEN_TTL_DAYS - age)
    return {"ok": True, "days_left": left, "warn": left <= WARN_DAYS}


def load_token(path: Path = TOKEN_FILE) -> str:
    st = token_file_status(path)
    if not st["ok"]:
        raise CredentialError(f"token file {path}: {st['reason']}")
    return path.read_text().strip()


@dataclass
class Job:
    role: str
    prompt: str
    worktree: Path
    out_dir: Path
    model: str
    effort: str
    max_turns: int
    timeout_s: int
    tools: list[str]
    readonly: bool = False
    write_root: str | None = None        # path inside /work that writes may touch (planning jobs)
    extra: list[str] = field(default_factory=list)
    name: str = ""


def claude_args(job: Job, settings: str) -> list[str]:
    a = ["-p", job.prompt, "--output-format", "stream-json", "--verbose", "--model", job.model,
         "--max-turns", str(job.max_turns), "--allowedTools", ",".join(job.tools), "--settings", settings,
         "--permission-mode", "acceptEdits", "--no-session-persistence",
         # swarm runs ignore the user's/project's hooks and plugins (no raw-session capture, no audit hooks that write to the repo);
         # only the hooks passed with --settings apply. Auth is unaffected.
         "--setting-sources", ""]
    if job.effort:
        a += ["--effort", job.effort]
    return a + job.extra


def git_common_dir(worktree: Path) -> Path | None:
    g = worktree / ".git"
    if g.is_file():
        m = re.match(r"gitdir:\s*(.+)", g.read_text().strip())
        if m:
            return Path(m.group(1)).resolve().parent.parent   # <repo>/.git/worktrees/<name> -> <repo>/.git
    return None


def docker_argv(job: Job, image: str = IMAGE) -> list[str]:
    """`docker run` with the isolation required by the spec. The token is inherited by NAME (-e VAR), never in argv."""
    wt = job.worktree.resolve()
    argv = ["docker", "run", "--rm", "-i", "--name", job.name or f"swarm-{os.getpid()}", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "512", "--memory", "3g",
            "--network", "bridge",
            "-v", f"{wt}:/work{':ro' if job.readonly else ''}",
            "-v", f"{job.out_dir.resolve()}:/swarm-out",
            "-w", "/work",
            "-e", TOKEN_VAR, "-e", "SWARM_OUT=/swarm-out", "-e", f"SWARM_ROLE={job.role}",
            "-e", f"SWARM_READONLY={'1' if job.readonly else '0'}"]
    if job.write_root:
        argv += ["-e", f"SWARM_WRITE_ROOT=/work/{job.write_root.strip('/')}"]
    gd = git_common_dir(wt)
    if gd and gd.exists():
        argv += ["-v", f"{gd}:{gd}:ro"]        # lets `git status/diff` work; commits are made by the dispatcher
    return argv + [image] + claude_args(job, "/opt/swarm/settings.json")


def local_argv(job: Job) -> list[str]:
    return [os.environ.get("SWARM_CLAUDE", "claude")] + claude_args(job, str(ROOT / "runner" / "settings.local.json"))


def write_local_settings() -> None:
    s = json.loads((ROOT / "runner" / "settings.json").read_text())
    hook = str(ROOT / "runner" / "hooks" / "swarm_hook.py")
    for ev in s["hooks"].values():
        for m in ev:
            for h in m["hooks"]:
                h["command"] = h["command"].replace("/opt/swarm/swarm_hook.py", hook)
    (ROOT / "runner" / "settings.local.json").write_text(json.dumps(s, indent=2))


@dataclass
class Result:
    returncode: int
    timed_out: bool
    stream_path: Path


def run(job: Job, mode: str = "docker", env: dict | None = None) -> Result:
    """Runs the job with a wall-clock timeout; the stream is saved under out_dir/stream.jsonl."""
    env = dict(os.environ if env is None else env)
    check_env(env)
    job.out_dir.mkdir(parents=True, exist_ok=True)
    stream = job.out_dir / "stream.jsonl"
    if mode == "docker":
        env[TOKEN_VAR] = env.get(TOKEN_VAR) or load_token()
        argv = docker_argv(job)
    else:
        write_local_settings()
        env.update({"SWARM_OUT": str(job.out_dir), "SWARM_ROLE": job.role, "SWARM_READONLY": "1" if job.readonly else "0"})
        if job.write_root:
            env["SWARM_WRITE_ROOT"] = str((job.worktree / job.write_root).resolve())
        argv = local_argv(job)
    with stream.open("w") as out:
        p = subprocess.Popen(argv, cwd=job.worktree if mode != "docker" else None, env=env, stdout=out,
                             stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        try:
            _, err = p.communicate(timeout=job.timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            if mode == "docker":
                subprocess.run(["docker", "kill", job.name], capture_output=True)
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _, err = p.communicate()
    if err:
        (job.out_dir / "stderr.log").write_text(_scrub(err))
    return Result(p.returncode if p.returncode is not None else -1, timed_out, stream)


def _scrub(text: str) -> str:
    from .redact import scrub
    return scrub(text)
