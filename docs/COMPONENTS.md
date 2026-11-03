# What Each Thing Is For

## Repository structure
| Path | What it is for |
|---|---|
| `seed-bundle/` | **Installation entry point**: `SEED.md` (phased runbook for an agent), `AGENT_PROMPT.md` (what to paste to it), `seed.sh` (orchestrator), `manifest.yaml` (tested versions, ports, phases, prohibitions, machine-readable) and `spec/` (technical specification) |
| `scripts/` | All the logic; Python with the standard library and bash (see table below) |
| `skills/` | Claude Code `project-memory-*` skills (recall, handoff, document, bootstrap, maintain, evaluate). They are symlinked into each repo |
| `templates/` | es/en templates: `CLAUDE.md` section, decision, implementation, handoff, project, `project.yaml` contract |
| `profiles/` | **Layered profiles** (dbt, dataform, snowflake, bigquery, webapp, python-lib, generic): rules injected into `CLAUDE.md` and indexing exclusions |
| `deploy/docker/` | Stack `compose.yaml` (Postgres+pgvector, Cognee API and MCP, OTel collector) and a thin Cognee image with a writable model volume |
| `observability/` | OpenTelemetry collector configuration (measures Claude Code tokens) |
| `analytics/` | Optional job (DuckDB) that normalizes telemetry and usage |
| `config/` | `versions.lock` (versions pinned with digest), `plugin.example.env` (plugin settings with cost caps), `projects.example.yaml` |
| `panel/` | **Management Memory**: read-only web dashboard (FastAPI + JS with no build step) |
| `evals/` | Format and example of the retrieval evaluation questions |
| `docs/` | This documentation and the Mermaid diagrams |
| `openspec/` | Current specs and changes for this very project (developed with OpenSpec) |

## Scripts (`scripts/`)
| Script | What it is for |
|---|---|
| `install_project.py` | Installs the memory into a repo: contract, templates, `CLAUDE.md`, hooks, skills, OpenSpec. Detects language and profile and asks if ambiguous |
| `detect_language.py` / `detect_project_type.py` | es/en detection and project type (layers) detection with confidence and evidence; exit code 2 = ask the user |
| `data_graph.py` | Lineage graph of a data repo (dbt, Dataform, Databricks): `build`, `find`, `show`, `upstream`, `downstream`, `impact`, `path`, `check`; writes `docs/agent-memory/data-graph/` |
| `data_connect.py` | Secret-free connection catalog (`.agent-memory/connections.yaml`): `init`, `render`, `check`, `brief` |
| `data_sync.py` | Change-driven sync: fingerprints, optional live metadata, rebuild only if changed, incremental indexing; `hook` is called by the briefing |
| `data_sources.py`, `miniyaml.py` | Opt-in read-only live-metadata adapters (BigQuery, Snowflake, Databricks); YAML loader with a stdlib fallback |
| `memory_brief.py` | **`SessionStart` hook**: builds the briefing (no LLM) and launches the security audit in the background |
| `memory_checkpoint.py` | **`SessionEnd`/`PreCompact` hooks**: writes the branch checkpoint (`handoffs/_local/auto-<rama>.md`) and refreshes usage |
| `memory_deploy.py` | Record of deployments per environment and state per branch (`record`/`status`) |
| `memory_deps.py` | Inventory of dependencies and runtimes, change history with rationale, and `docs/agent-memory/security/dependencies.md` |
| `memory_audit.py` | Vulnerability audit against OSV using the exact versions from the lockfiles |
| `memory_stale.py` | Detects outdated memory documents by comparing their `source_paths` with Git, without spending tokens |
| `sync_markdown.py` | Syncs `docs/agent-memory/` and the OpenSpec specs to Cognee (incremental by hash, verifies retrieval). Indexes in small parallel batches (`--batch-size 8`, `--parallel 2`) with a background `cognify`; a failed batch does not stop the rest and interrupted documents are reconciled by search before being re-indexed |
| `memctl.sh` | Daily operation: `up`, `stop`, `status`, `sync`, `eval`, and for data projects `graph`, `connect`, `datasync` |
| `memory_heal.py`, `memory_heal_launchagent.sh` | Scheduled self-healing: free repairs, budgeted re-sync of pending documents, report-only findings (see `docs/operations.md`) |
| `memory_eval.py` | Evaluates recall@5 with questions from `evals/` |
| `cognee_adapter.py` | Cognee HTTP client (add, cognify, search, forget) |
| `observer.sh`, `observer_launchagent.sh` | Observer: local bridge that uses your Claude subscription (`claude -p`) so Cognee can summarize and index; the LaunchAgent keeps it alive across reboots |
| `host_stats.py`, `host_stats_launchagent.sh` | On-demand measurement of the machine for the dashboard (no resident process) |
| `usage_scan.py` | Summarizes when the memory was used (transcript metadata only) for the dashboard |
| `gen_env.sh`, `mint_mcp_key.py`, `dc.sh` | Stack secrets (0600), API keys and `docker compose` wrapper |
| `claude-memory` | Launches Claude Code with OTel telemetry to measure tokens |
| `weekly_report.py`, `backup.sh` | Weekly consumption report and backup/test restore |
| `install_skills.sh` | Links the skills into the repo and excludes them from Git locally |

## What gets created in your repository
| File | Versioned | What it is for |
|---|---|---|
| `.agent-memory/project.yaml` | Yes | Contract: id, language, profile, datasets, sources and exclusions |
| `.agent-memory/local.yaml` | **No** | Path to the kit on this machine |
| `.agent-memory/deployments.json` | Yes | Deployment record |
| `.agent-memory/dependencies.json` | Yes | Inventory and version history |
| `.agent-memory/security-ignore.txt` | Yes (optional) | Accepted risks |
| `docs/agent-memory/` | Yes | Memory corpus in Markdown (canonical source; Cognee is only a derived index) |
| `docs/agent-memory/security/dependencies.md` | Yes | Versions, history and pending vulnerabilities (generated) |
| `docs/agent-memory/handoffs/_local/` | No | Automatic per-branch checkpoints |
| `CLAUDE.md` (section) | Yes | Rules for the agent: consult when in doubt, OpenSpec mandatory, deployments, security and profile rules |
| `.claude/settings.local.json` | No | Hooks (briefing/checkpoint) |
| `.claude/skills/project-memory-*` | No | Symlinks to the skills |
| `openspec/`, `.claude/commands/opsx-*` | Yes | OpenSpec initialized |

## Containers (Docker, `127.0.0.1` only)
| Container | Port | What it is for |
|---|---|---|
| `agents_cognee_api` | 45874 | Cognee API: ingestion, knowledge graph, search |
| `agents_cognee_mcp` | 45873 | MCP server that exposes `recall` to Claude Code |
| `agents_postgres` | — | PostgreSQL + pgvector: vectors (768 dim) and metadata, one schema per dataset |
| `agents_otel_collector` | 45875 | Collects Claude Code telemetry to measure tokens |
| `mm_app` + `mm_docker_proxy` | 45876 | Management Memory dashboard and a read-only proxy to the Docker engine |
Outside Docker: the **observer** (127.0.0.1:8017) and the optional LaunchAgents. `agents_memory_system` is the internal name of the Docker Compose project (it identifies volumes and network).

## Agent swarm (optional)
| Path | What it is |
|---|---|
| `swarm/` | The `swarm` CLI and dispatcher (standard-library Python): approval gate, jobs, git agent, post-merge, team mode, token tools |
| `swarm/runner/` | Hardened runner image (pinned Claude Code), guard hooks, event capture, on-demand recall script |
| `swarm/policy.yaml` | Model class, effort, tools and limits per role; git agent and team settings |
| `swarm/schema.sql` | Postgres schema `swarm` (runs, events, verdicts, approvals, tasks…) with a writer and a select-only reader role |
| `scripts/install_harness.py`, `templates/harness/` | Project analysis and the non-invasive harness installer (roles, `ARCHITECTURE.md`, `progress/`, health script) |
| `panel/` page **Swarm** | Read-only view: agents and their tasks, pending work, change board, verdicts, efficiency |
