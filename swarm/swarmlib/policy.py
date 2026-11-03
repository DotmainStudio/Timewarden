"""Loads policy.yaml, validates it and resolves model/effort/tools per role."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
import miniyaml  # noqa: E402

import os
POLICY = Path(os.environ.get("SWARM_POLICY", ROOT / "policy.yaml"))   # override for experiments (still validated)
LIGHTEST = "haiku"
ORDER = ["haiku", "sonnet", "opus"]
ROLES = ("explorer", "implementer", "reviewer", "leader", "gitops")


class PolicyError(ValueError):
    pass


def load(path: Path | None = None) -> dict:
    path = path or POLICY
    text = path.read_text(encoding="utf-8")
    data = miniyaml.load(text)
    if not isinstance(data, dict):
        raise PolicyError("policy.yaml is not a mapping")
    validate(data)
    data["_hash"] = hashlib.sha256(text.encode()).hexdigest()[:12]
    return data


def validate(p: dict) -> None:
    roles = p.get("roles") or {}
    for r in ROLES:
        if r not in roles:
            raise PolicyError(f"missing role {r}")
        if roles[r].get("model") not in ORDER:
            raise PolicyError(f"role {r}: unknown model class")
        if not roles[r].get("tools"):
            raise PolicyError(f"role {r}: explicit tool allowlist required")
    strongest = (p.get("escalation") or {}).get("strongest_class", "opus")
    if any(v.get("model") == strongest for v in roles.values()):
        raise PolicyError(f"the strongest class ({strongest}) must not be a default for any role")
    if roles["explorer"]["model"] != LIGHTEST or roles["explorer"].get("effort") != "low":
        raise PolicyError("explorer must use the lightest class and low effort")
    for r in ("explorer", "reviewer"):
        bad = [t for t in roles[r]["tools"] if str(t).split("(")[0] in ("Edit", "Write", "NotebookEdit")]
        if bad:
            raise PolicyError(f"{r} must be read-only; has {bad}")
        if roles[r].get("writes") is not False:
            raise PolicyError(f"{r} must declare writes: false")
    g = p.get("gitops") or {}
    if g.get("merge_method", "squash") not in ("squash", "merge"):
        raise PolicyError("gitops.merge_method must be squash or merge")
    if int(p["limits"]["max_concurrent_jobs"]) < 1:
        raise PolicyError("max_concurrent_jobs must be >= 1")


def model_for(p: dict, role: str, failed_reviews: int = 0, architecture_change: bool = False) -> str:
    """Default class per role; the strongest class only on escalation (architecture change or two failed reviews)."""
    base = p["roles"][role]["model"]
    allowed = (p.get("escalation") or {}).get("allowed_when", [])
    if role in ("implementer", "leader") and (
        (architecture_change and "architecture_change" in allowed) or (failed_reviews >= 2 and "two_failed_reviews" in allowed)
    ):
        return p["escalation"]["strongest_class"]
    return base


def limits_for(p: dict, role: str) -> dict:
    lim = p["limits"]
    return {"max_turns": int(lim["max_turns"][role]), "timeout_s": int(lim["timeout_minutes"][role]) * 60}
