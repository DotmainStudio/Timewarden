# Memory self-heal agent

## Why

The Management Memory panel reports problems (documents not indexed, services down, interrupted syncs, stuck runs) that today need a person to notice and run a command. A periodic healer can fix the mechanical ones, but it must not burn the Claude subscription: indexing costs quota, retries and AI diagnosis can run away.

## What Changes

- New `scripts/memory_heal.py` and a LaunchAgent installer: runs on a timer, deterministic by default, with a hard budget for anything that spends tokens.
- Free fixes: restart unhealthy containers and the observer, mark swarm runs stuck for hours as failed, kill leftover team sessions.
- Token-spending fix (re-sync pending documents) only within caps: syncs per day, documents per sync, minimum hours between syncs, attempts per item, pause when the subscription quota is high, never from a branch that is not the default branch or with uncommitted changes to indexed files.
- Findings that must not be auto-fixed (documents in Cognee without a registry entry) are reported, not deleted.
- Optional, off by default: a once-a-day read-only diagnosis with the lightest model for problems that persist after the attempts are used up.
- Desktop notification (deduplicated per day) and a JSON log.

## Capabilities

### New Capabilities
- `memory-self-heal`: scheduled, budgeted detection and repair of memory-stack problems.

## Impact

- New `scripts/memory_heal.py`, `scripts/memory_heal_launchagent.sh`, tests, docs. No change to the memory data model or datasets.
