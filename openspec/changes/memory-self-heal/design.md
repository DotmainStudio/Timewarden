# Design

1. **Deterministic core, model opt-in.** Everything is plain commands. The only token cost is the existing `sync_markdown.py --apply`, called with `--max-docs`.
2. **State file** (`~/.local/share/agents_memory_system/heal/state.json`): per-day counters, last sync time, attempts per item, alert dedupe. Counters reset on a new calendar day.
3. **Quota** read from the swarm database (`quota_utilization` of runs in the last 5 hours); unknown means normal caps apply.
4. **Injectable shell** (`sh(argv)`), so tests use a scripted fake and never touch Docker or the memory stack.
5. **LaunchAgent** with `StartInterval`, low priority, no KeepAlive. Reversible (`uninstall`).
6. **Not automatic:** forgetting data, deleting documents, indexing from a non-default branch. These are reported.
