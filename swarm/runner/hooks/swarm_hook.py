#!/usr/bin/env python3
"""Claude Code hook for swarm runs (stdlib only). Usage: swarm_hook.py <pre|post|session|subagent|stop>

pre   -> PreToolUse guard: exit 2 blocks the tool call (reason on stderr) and records a `blocked` event.
others-> append a sanitised, secret-free event line to $SWARM_OUT/events.jsonl (the dispatcher ingests it into Postgres).

Env: SWARM_OUT (dir for events), SWARM_WRITE_ROOT (the only path writes may touch), SWARM_READONLY=1, SWARM_ROLE.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

CONTENT_KEYS = {"content", "new_string", "old_string", "text", "prompt", "stdout", "stderr", "output", "file_text", "tool_response"}
SECRET = re.compile(r"(sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|"
                    r"(?i:(oauth_token|api_key|auth_token|password|secret|token))\s*[=:]\s*\S{12,})")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Never allowed to ANY role (the git agent included): history rewrites, force pushes, pushes to the main branch, hard resets.
UNIVERSAL_BASH = [
    (r"\bgit\s+push\b[^;&|]*(--force\b|--force-with-lease|\s-f\b|\s\+\S)", "force pushes are never allowed"),
    (r"\bgit\s+push\b[^;&|]*\s(origin\s+)?(HEAD:)?(refs/heads/)?(main|master)\b", "pushing to the main branch is never allowed"),
    (r"\bgit\s+push\b[^;&|]*\s:\S+", "deleting remote branches through push is not allowed"),
    (r"\bgit\s+reset\s+--hard\b", "destructive reset is not allowed"),
    (r"\bgit\s+(checkout|switch)\s+(-[bBcC]\s+\S+\s+)?(main|master)\b", "agents must not switch to the main branch"),
    (r"\bgit\s+rebase\b", "rebasing is not allowed (update branches by merging)"),
    (r"\bgh\s+(repo\s+delete|release|pr\s+merge)\b", "only the dispatcher's merge policy may merge or release"),
]
# The git agent (role gitops) may push non-main branches and merge the main branch INTO its change branch.
GITOPS_ALLOWED_GIT = r"^\s*(git\s+(status|diff|log|add|commit|merge|fetch|push|branch|show|stash|restore|checkout|config\s+--get|rev-parse|ls-files|ls-remote|remote)|gh\s+(pr|auth\s+status|repo\s+view|run|api\s+repos))\b"
# Pushing, merging, deploying and container control are not allowed to the other roles.
FORBIDDEN_BASH = [
    (r"\bgit\s+push\b", "agents must not push (the dispatcher publishes the branch)"),
    (r"\bgit\s+(merge|rebase)\b", "agents must not merge or rebase"),
    (r"\bgit\s+(checkout|switch)\s+(-[bBcC]\s+\S+\s+)?(main|master)\b", "agents must not switch to the main branch"),
    (r"\bgit\s+reset\s+--hard\b", "destructive reset is not allowed"),
    (r"\bgh\s+(pr\s+merge|release|repo\s+delete)\b", "agents must not merge or release"),
    (r"\bdocker\b|\bkubectl\b|\bterraform\s+apply\b|\bhelm\s+(install|upgrade)\b", "deploys and container control belong to the user"),
    (r"\bcurl\b[^|;]*\|\s*(ba|z)?sh\b", "piping downloads into a shell is not allowed"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)(\s|$)", "destructive delete is not allowed"),
]
READONLY_BASH = [(r"(^|[^<>&2])>\s*[^&\s]|>>|\btee\b|\bsed\s+-i\b|\bgit\s+(add|commit|stash|apply|rm|mv|clean)\b|\b(rm|mv|cp|mkdir|touch|chmod|ln)\b|\bpython3?\s+-c\b",
                  "this role is read-only")]


def clean(v, key=""):
    if isinstance(v, dict):
        return {k: clean(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x, key) for x in v[:20]]
    if isinstance(v, str):
        if key in CONTENT_KEYS:
            return f"<{len(v)} chars>"
        v = SECRET.sub("[REDACTED]", v)
        return v if len(v) <= 200 else v[:200] + f"... (+{len(v) - 200})"
    return v


def emit(type_, **fields):
    out = os.environ.get("SWARM_OUT")
    if not out:
        return
    rec = {"ts": time.time(), "type": type_, "role": os.environ.get("SWARM_ROLE", ""), **clean(fields)}
    try:
        with open(Path(out) / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def inside(path: str, root: str, cwd: str) -> bool:
    p = Path(path if os.path.isabs(path) else os.path.join(cwd, path))
    p = Path(os.path.normpath(p))
    r = Path(os.path.normpath(root))
    return p == r or r in p.parents


def decide(tool: str, tinput: dict, cwd: str, root: str | None, readonly: bool, role: str = "") -> str | None:
    """Returns a block reason, or None to allow. Pure function (unit tested)."""
    if tool in WRITE_TOOLS:
        if readonly:
            return "this role is read-only"
        path = tinput.get("file_path") or tinput.get("notebook_path") or ""
        if root and not inside(path, root, cwd):
            return f"writes are restricted to {root}"
    if tool == "Bash":
        cmd = tinput.get("command", "")
        for pat, why in UNIVERSAL_BASH:
            if re.search(pat, cmd):
                return why
        if role == "gitops":
            if not re.search(GITOPS_ALLOWED_GIT, cmd) and re.search(r"\b(git|gh)\b", cmd) is None and not re.match(r"^\s*(bash scripts/health\.sh|cat|ls|grep|head|tail)\b", cmd):
                return "the git agent may only run git, gh (pull requests) and the health script"
            return None
        for pat, why in FORBIDDEN_BASH:
            if re.search(pat, cmd):
                return why
        if readonly or root:
            for pat, why in READONLY_BASH:
                if re.search(pat, cmd):
                    return why if readonly else "planning jobs may only write inside the change directory (use Write/Edit)"
    return None


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    tool, tinput = data.get("tool_name", ""), data.get("tool_input") or {}
    if kind == "pre":
        reason = decide(tool, tinput, data.get("cwd") or os.getcwd(), os.environ.get("SWARM_WRITE_ROOT") or None,
                        os.environ.get("SWARM_READONLY") == "1", os.environ.get("SWARM_ROLE", ""))
        if reason:
            emit("blocked", tool=tool, reason=reason, input=tinput)
            print(f"swarm guard: {reason}", file=sys.stderr)
            sys.exit(2)
        emit("tool_start", tool=tool, input=tinput)
    elif kind == "post":
        emit("tool_end", tool=tool, ok=not bool(data.get("tool_response", {}).get("is_error")) if isinstance(data.get("tool_response"), dict) else True)
    elif kind == "teammate_idle":
        emit("teammate_idle", teammate=data.get("teammate_name") or data.get("agent_type") or "", team=data.get("team_name", ""))
    elif kind == "task_done":
        emit("team_task_completed", teammate=data.get("teammate_name") or "", task=data.get("task_subject") or data.get("task_id") or "")
    elif kind in ("session", "subagent", "stop"):
        emit({"session": "session_start", "subagent": "subagent_stop", "stop": "session_stop"}[kind],
             agent=data.get("agent_type") or data.get("subagent_type") or "", session=data.get("session_id", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
