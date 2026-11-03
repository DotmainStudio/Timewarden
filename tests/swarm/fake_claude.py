#!/usr/bin/env python3
"""Deterministic stand-in for `claude -p` used in tests (no quota, no network). Behaviour via FAKE_ACTION."""
import json, os, re, sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
act = os.environ.get("FAKE_ACTION", "noop")
cwd = Path.cwd()
text = "done"
if act == "plan":
    cid = re.search(r"openspec/changes/([a-z0-9-]+)/", prompt).group(1)
    d = cwd / "openspec" / "changes" / cid
    (d / "specs" / "demo").mkdir(parents=True, exist_ok=True)
    (d / "proposal.md").write_text("# Demo change\n\n## Why\nx\n")
    (d / "specs" / "demo" / "spec.md").write_text("## ADDED Requirements\n\n### Requirement: Demo works\nThe system SHALL work.\n\n#### Scenario: It works\n- **WHEN** x\n- **THEN** y\n")
    (d / "tasks.md").write_text("# Tasks\n\n## 1. Core\n\n- [ ] 1.1 Create marker (verification: `test -f marker.txt`)\n- [ ] 1.2 Create second marker (verification: `test -f marker2.txt`)\n")
    if os.environ.get("FAKE_STRAY"):
        (cwd / "src_evil.py").write_text("print('outside')\n")
elif act == "plan_open":
    cid = re.search(r"openspec/changes/([a-z0-9-]+)/", prompt).group(1)
    d = cwd / "openspec" / "changes" / cid; d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.md").write_text("# P\n\n## Open questions\n\n1. What about strings?\n   - (A) concat\n2. Which rounding?\n")
elif act == "resolve":
    import subprocess
    files = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True).stdout.split()
    for f in files:
        (cwd / f).write_text("resolved\n")
    subprocess.run(["git", "add", "-A"]); subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--no-edit"])
elif act == "explore_dirty":
    (cwd / "oops.txt").write_text("a read-only role must not do this\n")
elif act == "impl":
    t = re.search(r"task (\d+\.\d+)", prompt).group(1)
    (cwd / ("marker.txt" if t == "1.1" else "marker2.txt")).write_text("ok\n")
elif act == "impl_noop":
    pass
elif act in ("review_pass", "review_fail", "review_noevidence"):
    ids = re.findall(r"^- (\S+/\S+/\S+):", prompt, re.M)
    if act == "review_pass":
        rows = [{"id": i, "status": "pass", "evidence": "tests/x.py:1"} for i in ids]
    elif act == "review_noevidence":
        rows = [{"id": i, "status": "pass", "evidence": ""} for i in ids]
    else:
        rows = [{"id": i, "status": "fail", "evidence": "tests/x.py:9"} for i in ids]
    text = json.dumps({"scenarios": rows, "findings": []})
elif act == "sleep":
    import time; time.sleep(30)
print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake-1", "apiKeySource": "none"}))
print(json.dumps({"type": "assistant", "message": {"id": "m1", "model": "claude-haiku-5-5", "content": [{"type": "text", "text": text}],
                  "usage": {"input_tokens": 3, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 10}}}))
print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.07}}}}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, "num_turns": 2, "total_cost_usd": 0.001,
                  "usage": {"input_tokens": 3, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 10}, "session_id": "fake-1"}))
