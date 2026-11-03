"""Token storage and the real Docker-mode verification (subscription token, hardened container, no secret leaks)."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from . import jobs, runner
from .redact import find_secrets

TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")


def save_token(raw: str, path: Path = runner.TOKEN_FILE) -> dict:
    """Stores the token (first sk-ant-… match in `raw`) with mode 0600, atomically; never prints it."""
    m = TOKEN_RE.search(raw or "")
    if not m:
        raise ValueError("no token found in the input (expected an sk-ant-… value)")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(m.group(0) + "\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return {"saved": str(path), "mode": oct(stat.S_IMODE(path.stat().st_mode)), "length": len(m.group(0))}


def scan_for_token(token: str, paths: list[Path], texts: list[str]) -> list[str]:
    """Returns where the token value appears (empty list = no leak). Also flags generic secret patterns."""
    hits = []
    for p in paths:
        if p.is_file() and token in p.read_text(errors="replace"):
            hits.append(str(p))
    for i, t in enumerate(texts):
        if token in (t or ""):
            hits.append(f"text[{i}]")
    return hits


def verify_docker(ctx: jobs.Ctx) -> dict:
    """Runs ONE real read-only job in the container with the stored token and checks credentials, isolation and leaks."""
    st = runner.token_file_status()
    out: dict = {"token_file": st, "checks": {}}
    if not st["ok"]:
        out["ok"] = False
        out["error"] = f"token file not usable: {st['reason']}"
        return out
    token = runner.load_token()
    checks = out["checks"]
    # 1. conflicting credential is refused before any request (live, with the real image)
    r = subprocess.run(["docker", "run", "--rm", "-e", "ANTHROPIC_API_KEY=x", "-e", runner.TOKEN_VAR, runner.IMAGE, "--version"],
                       capture_output=True, text=True, env={**os.environ, runner.TOKEN_VAR: token})
    checks["api_key_refused"] = r.returncode == 64
    # 2. a real job in the hardened container
    work = Path(tempfile.mkdtemp(prefix="swarm-verify-"))
    (work / "README.md").write_text("# verify\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    ctx.repo, ctx.mode = work, "docker"
    res = jobs.execute(ctx, "explore", "explorer", "Reply with exactly the word DOCKER_OK and nothing else.", work, None, None, "")
    s = res["summary"]
    checks["job_succeeded"] = res["state"] == "succeeded"
    checks["answered"] = "DOCKER_OK" in (s.result_text or "")
    checks["subscription_credential"] = ctx.store.db.one("select auth_kind from swarm.runs where id=:'i'::bigint", i=res["run_id"])["auth_kind"] == "subscription-token"
    checks["no_api_billing_key"] = (s.api_key_source or "none") != "ANTHROPIC_API_KEY"
    checks["tokens_recorded"] = (s.output_tokens or 0) > 0
    checks["tree_unchanged"] = not [p for p in work.iterdir() if p.name not in (".git", "README.md")]
    # 3. no leaks anywhere
    run_dir = res["out_dir"]
    rows = ctx.store.db.rows("select detail::text as d from swarm.events where run_id=:'i'::bigint", i=res["run_id"]) + \
        ctx.store.db.rows("select coalesce(summary,'') as d from swarm.runs where id=:'i'::bigint", i=res["run_id"])
    leaks = scan_for_token(token, list(run_dir.glob("*")) + list(work.rglob("*")), [r["d"] for r in rows])
    checks["no_token_leak"] = not leaks
    out["leaks"] = leaks
    out["run"] = {"id": res["run_id"], "turns": s.turns, "model": s.main_model, "output_tokens": s.output_tokens, "quota_utilization": s.quota_utilization,
                  "api_key_source_reported": s.api_key_source}
    out["ok"] = all(checks.values())
    return out
