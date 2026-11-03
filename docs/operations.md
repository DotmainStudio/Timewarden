# Operations

Everything goes through `scripts/memctl.sh`. The values below were verified on 2026-10-26.

| Operation | Command | What keeps working |
|---|---|---|
| Start | `memctl.sh up` (observer + stack) | — |
| **Pause capture** | `COGNEE_CAPTURE=false` in `~/.cognee/.env` (already the pilot value) | recall and explicit saving |
| **Disconnect agent** | `claude plugin disable cognee-memory@cognee` and `claude mcp remove agents_cognee` | data and Markdown |
| **Stop memory** | `memctl.sh stop` (= `docker compose stop`; **never** `down -v`) | normal Claude work (tested: 4.5 s session with the stack down) |
| Status | `memctl.sh status <repo>` | — |
| Sync | `memctl.sh sync <repo> [--apply]` | — |
| Evaluate | `memctl.sh eval <repo>` | — |
| Backup | `scripts/backup.sh` (pauses the API for a moment) | — |
| Test restore | `scripts/backup.sh restore-test <dir>` | uses disposable resources |
| Telemetry | `scripts/dc.sh --profile eval run --rm agents_analytics report --project <id>` | — |

## Install memory in a new project
`scripts/install_project.py <repo> --project-id <id>` (idempotent): `.agent-memory/project.yaml` contract, `docs/agent-memory/` skeleton, templates, section in `CLAUDE.md`, hooks (briefing/checkpoint) in `.claude/settings.local.json`, skills, and local Git exclusions. Then write `project.md` and the first documents, and run `memctl.sh sync <repo> --apply`.

## Persistent observer (LaunchAgent)
`scripts/observer_launchagent.sh install` starts it at login and restarts it if it dies (tested: auth ok under launchd, restart after `kill`, reachable from the container). `status` and `uninstall` manage it. Log: `~/.local/share/agents_memory_system/observer-launchd.log`. With the agent installed, `memctl.sh up` doesn't need to start it.

## Cold start
1. `scripts/observer.sh start` (the observer is a process on the Mac; it is lost on reboot).
2. `scripts/gen_env.sh` (idempotent; syncs the observer token to `.env`).
3. `scripts/dc.sh up -d` (Postgres → API → MCP, collector).
4. First time: `scripts/mint_mcp_key.py` and restart `agents_cognee_mcp`.

## Verify that the observer is reachable from Docker
`docker run --rm curlimages/curl -H "Authorization: Bearer $(cat ~/.cognee-plugin/observer/token)" http://host.docker.internal:8017/v1/models`

## Session telemetry
`scripts/claude-memory <project_id> <A|B> -- <claude args>` exports OTel to the collector (`127.0.0.1:45875`).

## Things NOT to do
`docker compose down -v`, `forget` with `everything`, mounting `~/.cognee-plugin/observer/` (it contains the token), exposing ports outside `127.0.0.1`.

## Self-healing (scheduled, budgeted)
`scripts/memory_heal.py` runs from a LaunchAgent (`scripts/memory_heal_launchagent.sh install <repo>...`, every 60 min by default) and fixes the mechanical problems the panel reports. It is **deterministic and spends no tokens by default**.

| What | How | Costs quota |
|---|---|---|
| A stack container, the panel or the observer is down/unhealthy | restarts only that service (never `down -v`), at most 3 times a day, then one notification | No |
| Swarm runs stuck "running" for hours; leftover team tmux sessions | marks the runs failed; closes the sessions | No |
| Documents pending, changed or interrupted in a configured repo | `sync_markdown.py --apply --max-docs 8`, only within the budget below | **Yes (capped)** |
| Documents in memory with no registry entry (orphans) | reported once a day, **never deleted** | No |
| Persistent failures | optional read-only diagnosis with the lightest model, off by default | Only if enabled |

**Token budget (config `~/.config/agents_memory_system/heal.yaml`; values can be lowered, never raised past the hard caps):** `max_syncs_per_day` 2 (cap 6), `max_docs_per_sync` 8 (cap 20), `min_hours_between_syncs` 6, `max_attempts_per_item` 3 (a failing document stops being retried that day), `quota_pause_at` 0.7 (no token-spending action while the subscription utilisation reported by the swarm runs is at or above it). A repository is synced only from its default branch with no uncommitted changes to tracked files, so nothing unmerged is indexed.
Commands: `memory_heal.py run [--dry-run]`, `status`, `config`, `add-repo <path>`; `memory_heal_launchagent.sh install|uninstall|status|dry-run|run-now`. Log and state: `~/.local/share/agents_memory_system/heal/`.
