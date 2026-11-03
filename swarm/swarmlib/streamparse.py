"""Parses `claude -p --output-format stream-json --verbose` into per-run figures (tokens, turns, model mix, quota)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class RunSummary:
    session_id: str | None = None
    models: dict = field(default_factory=dict)       # model -> assistant message count
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float | None = None
    context_end: int = 0
    quota_utilization: float | None = None
    is_error: bool = False
    result_text: str = ""
    stop_subtype: str | None = None
    tool_calls: dict = field(default_factory=dict)   # tool name -> count
    subagent_starts: int = 0
    api_key_source: str | None = None
    has_result: bool = False

    @property
    def cache_read_share(self) -> float:
        tot = self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens
        return round(self.cache_read_tokens / tot, 4) if tot else 0.0

    @property
    def main_model(self) -> str | None:
        return max(self.models, key=self.models.get) if self.models else None


def parse_lines(lines) -> RunSummary:
    s = RunSummary()
    seen_msgs: set[str] = set()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t == "system" and d.get("subtype") == "init":
            s.session_id = d.get("session_id")
            s.api_key_source = d.get("apiKeySource")
        elif t == "assistant":
            m = d.get("message") or {}
            mid = m.get("id")
            if mid and mid not in seen_msgs:
                seen_msgs.add(mid)
                s.turns += 1
                s.models[m.get("model", "?")] = s.models.get(m.get("model", "?"), 0) + 1
            u = m.get("usage") or {}
            if u:
                s.context_end = int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
            for b in m.get("content") or []:
                if b.get("type") == "tool_use":
                    name = b.get("name", "?")
                    s.tool_calls[name] = s.tool_calls.get(name, 0) + 1
                    if name in ("Task", "Agent"):
                        s.subagent_starts += 1
        elif t == "rate_limit_event":
            w = ((d.get("rate_limit_info") or {}).get("unifiedWindows") or {})
            vals = [float(v.get("utilization", 0)) for v in w.values() if isinstance(v, dict) and "utilization" in v]
            if vals:
                s.quota_utilization = max(vals)
        elif t == "result":
            s.has_result = True
            u = d.get("usage") or {}
            s.input_tokens = int(u.get("input_tokens", 0))
            s.output_tokens = int(u.get("output_tokens", 0))
            s.cache_read_tokens = int(u.get("cache_read_input_tokens", 0))
            s.cache_creation_tokens = int(u.get("cache_creation_input_tokens", 0))
            s.cost_usd = d.get("total_cost_usd")
            s.is_error = bool(d.get("is_error")) or d.get("subtype") not in (None, "success")
            s.stop_subtype = d.get("subtype")
            s.result_text = d.get("result") or ""
            if d.get("num_turns"):
                s.turns = int(d["num_turns"])
            s.session_id = s.session_id or d.get("session_id")
    return s
