#!/usr/bin/env python3
"""On-demand memory recall for swarm jobs (replaces an always-attached Cognee MCP server: saves tool-schema tokens).

Usage: recall.py "<question>" [--dataset <name>] [--top-k 3]      |      recall.py --used <query_hash>
- The dataset is PINNED to `memory_dataset` of .agent-memory/project.yaml; any other dataset is rejected and logged.
- Search type is CHUNKS (no LLM). Every call is logged to $SWARM_OUT/events.jsonl with the sources returned.
- Env: COGNEE_BASE_URL, COGNEE_API_KEY (X-Api-Key), SWARM_OUT, SWARM_REPO (default cwd).
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path


def project_dataset(repo: Path) -> str | None:
    f = repo / ".agent-memory" / "project.yaml"
    if not f.exists():
        return None
    m = re.search(r"^memory_dataset:\s*([^\s#]+)", f.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip("'\"") if m else None


def log(rec: dict) -> None:
    out = os.environ.get("SWARM_OUT")
    if out:
        with open(Path(out) / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "role": os.environ.get("SWARM_ROLE", ""), **rec}) + "\n")


def search(base: str, key: str, dataset: str, query: str, top_k: int) -> list:
    req = urllib.request.Request(base.rstrip("/") + "/api/v1/search", method="POST",
                                 data=json.dumps({"searchType": "CHUNKS", "datasets": [dataset], "query": query, "topK": top_k}).encode(),
                                 headers={"Content-Type": "application/json", "X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sources(results) -> list[str]:
    text = json.dumps(results)
    return sorted(set(re.findall(r"path=([^\s\"\\]+)", text)))[:10]


def main(argv: list[str]) -> int:
    repo = Path(os.environ.get("SWARM_REPO", ".")).resolve()
    if len(argv) >= 2 and argv[0] == "--used":
        log({"type": "recall_used", "query_hash": argv[1]})
        return 0
    if not argv:
        print(__doc__); return 2
    query, dataset, top_k = argv[0], None, 3
    rest = argv[1:]
    while rest:
        if rest[0] == "--dataset" and len(rest) > 1:
            dataset, rest = rest[1], rest[2:]
        elif rest[0] == "--top-k" and len(rest) > 1:
            top_k, rest = max(1, min(int(rest[1]), 5)), rest[2:]
        else:
            rest = rest[1:]
    own = project_dataset(repo)
    qh = hashlib.sha256(query.encode()).hexdigest()[:12]
    if not own:
        print("recall: no .agent-memory/project.yaml memory_dataset; read docs/agent-memory directly", file=sys.stderr); return 3
    if dataset and dataset != own:
        log({"type": "recall", "dataset": dataset, "query_hash": qh, "results": 0, "rejected": True})
        print(f"recall: dataset '{dataset}' is not this project's dataset ('{own}'); cross-project recall is disabled", file=sys.stderr)
        return 4
    key = os.environ.get("COGNEE_API_KEY", "")
    if not key:
        print("recall: COGNEE_API_KEY not set; read docs/agent-memory directly", file=sys.stderr); return 5
    try:
        res = search(os.environ.get("COGNEE_BASE_URL", "http://host.docker.internal:45874"), key, own, query, top_k)
    except Exception as e:
        print(f"recall: memory unavailable ({str(e)[:80]}); read docs/agent-memory directly", file=sys.stderr); return 6
    log({"type": "recall", "dataset": own, "query_hash": qh, "results": len(res), "rejected": False, "sources": sources(res)})
    print(json.dumps({"query_hash": qh, "results": res}, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
