#!/usr/bin/env python3
"""Stand-in for an interactive Claude Code team session: records its flags/env and emits team events like the real hooks do."""
import json, os, sys, time
out = os.environ["SWARM_OUT"]
open(os.path.join(out, "argv.json"), "w").write(json.dumps({"argv": sys.argv[1:], "team_flag": os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"), "cwd": os.getcwd()}))
with open(os.path.join(out, "events.jsonl"), "a") as f:
    for t in ("teammate_idle", "teammate_idle", "team_task_completed"):
        f.write(json.dumps({"ts": time.time(), "type": t, "role": "leader", "teammate": "reviewer-1"}) + "\n")
time.sleep(float(os.environ.get("FAKE_TEAM_SLEEP", "0.5")))
