"""Secret scanning and event-payload sanitising: events carry metadata only, never secrets or file contents."""
from __future__ import annotations

import re

PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|PASSWORD|SECRET|TOKEN)\s*[=:]\s*[\"']?[A-Za-z0-9+/_\-.]{12,}"),
]
# Fields that may hold file contents or free text; replaced by their length.
CONTENT_KEYS = {"content", "new_string", "old_string", "text", "prompt", "stdout", "stderr", "output", "file_text"}
MAX_STR = 200


def find_secrets(text: str) -> list[str]:
    return [p.pattern[:30] for p in PATTERNS if p.search(text or "")]


def scrub(text: str) -> str:
    for p in PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def sanitize(value, key: str = ""):
    """Recursively strips content-bearing fields to their size and truncates/redacts the rest."""
    if isinstance(value, dict):
        return {k: sanitize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, key) for v in value[:20]]
    if isinstance(value, str):
        if key in CONTENT_KEYS:
            return f"<{len(value)} chars>"
        s = scrub(value)
        return s if len(s) <= MAX_STR else s[:MAX_STR] + f"... (+{len(s) - MAX_STR})"
    return value
