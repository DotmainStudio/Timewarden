# SEED — runbook for an agent to install project memory

Audience: an agent (Claude Code or other) that must install Cognee memory on **a new machine and a new repository, without knowing this system**. Follow the phases in order. Each phase has a command, an expected result, and what to do if it fails. Technical detail: `spec/Cognee-memory-specification.md` §21. All paths are relative to the kit folder (`<KIT>`, the one that contains this file in `seed-bundle/`); there are no fixed paths.

## Agent rules
1. **Run unattended.** The user authorized the whole installation by handing you the task: do not stop for approval at the `machine`, plugin, `index` or panel phases (they start containers, touch Claude Code global settings and spend tokens). Report at the end what you did and what indexing cost. Pass `--yes` yourself.
2. **The only questions**: the language and the project type when they are not obvious (phases 2 and 2b; the installer exits with code 3 so that you ask), and an operating system other than macOS + Docker Desktop. Never guess those; ask once, then continue unattended.
3. Do not print or paste secrets (`deploy/docker/.env`, `~/.cognee/.env`, observer token, `profiles.yml`, service accounts).
4. Forbidden: `docker compose down -v`, `forget` with `everything`, mounting `~/.cognee-plugin/observer/`, publishing ports outside `127.0.0.1`.
5. If something fails, read the troubleshooting table (spec §21.7) before improvising. Report what was tested and what was **not** tested.
6. Only macOS + Docker Desktop is validated. On Linux/Windows, warn the user before continuing and report every difference.

## How it works (to explain to the user in 30 seconds)
Everything runs **on the user's machine**, in Docker: Cognee, PostgreSQL with pgvector, the MCP and the panel. **Embeddings are computed locally** (no internet or subscription). Search is local and free. The only things that go out to Claude are the text that gets **indexed** (summaries and concepts, via the *observer* with `claude -p`, which spends subscription tokens) and the retrieved text that Claude Code reads in the conversation. The vulnerability audit sends only **package names and versions** to `api.osv.dev`.

## Phase 0 — Understand the request
Confirm with the user: (a) one repository or several, (b) a stable `project_id` (lowercase, hyphens; not the path), (c) data that must **not** go in (customers, banking, secrets), (d) should session capture stay on (with caps) or off (`--no-capture`)? Default: on with caps.

## Phase 1 — Requirements
```bash
cd <KIT> && seed-bundle/seed.sh doctor
```
Expected: Docker running, `claude` ≥ 2.1.287 with an active session, python3, git, **OpenSpec** (the `openspec` CLI; it is part of the installation — if it is missing, offer to install it for the user with `curl -fsSL https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/scripts/binary/install.sh | sh` after showing them the script, or `npm i -g @fission-ai/openspec`), ports 45873–45876 and 8017 free (or already used by this stack). If Docker is not running, ask for it to be opened. The first startup downloads images and ~640 MB of the embeddings model.

## Phase 2 — Project language (mandatory question if ambiguous)
```bash
python3 -I scripts/detect_language.py <repo>     # LANG=es|en|unknown CONFIDENCE=0..1
```
Exit 0 (confidence ≥ 0.75): report it and continue. Exit 2 / `unknown`: **ask** "Is the project in Spanish or English?" and pass `--lang es|en`. The language decides templates, the `CLAUDE.md` section, the briefing and documents.

## Phase 2b — Project type and profile (mandatory question if ambiguous)
```bash
python3 -I scripts/detect_project_type.py <repo>  # PROFILES=dbt,snowflake CONFIDENCE=.. EVIDENCE=.. [ASK=.. OPTIONS=a|b|c]
```
A profile is 1–2 **layers**: `dbt`, `dataform`, `snowflake`, `bigquery`, `databricks`, `webapp`, `python-lib`, `generic` (e.g. `dbt,snowflake`, `dbt,bigquery`, `dbt,databricks`, `dataform,bigquery`, `databricks`, `bigquery`). Exit 0: report what was detected and its evidence. Exit 2 (ASK/OPTIONS): **ask the user** with those options (typical cases: dbt with no detectable adapter; empty repo; evidence of two warehouses) and pass `--profile <layers>`. Each layer contributes rules to the project's `CLAUDE.md`, indexing exclusions (credentials, keys, Terraform state) and templates. For data projects read `docs/DATA_PROJECTS.md`.

## Phase 3 — Machine (once per machine)
```bash
seed-bundle/seed.sh machine --yes
```
Starts the observer, generates secrets (0600), brings up Postgres/API/MCP/collector, waits for `/health` = `ready` (60–90 s or more the first time), creates the MCP and plugin keys, creates `~/.cognee/.env` from `config/plugin.example.env` if it does not exist (session capture on with caps) and installs the observer LaunchAgent (macOS; reversible with `scripts/observer_launchagent.sh uninstall`; if the plugin is not yet installed it is retried after phase 4).

## Phase 4 — Project (once per repo)
```bash
seed-bundle/seed.sh project <repo> <project_id> --lang auto --profile auto [--no-capture] [--no-plugin]
```
Creates `.agent-memory/project.yaml` (contract with language, profile and exclusions), `.agent-memory/local.yaml` (kit path on this machine, **not versioned**), the `docs/agent-memory/` skeleton, the memory section in `CLAUDE.md` (profile rules, the rule to consult memory when ambiguous, deployments, security and OpenSpec), hooks (briefing/checkpoint) in `.claude/settings.local.json`, `project-memory-*` skills and local Git exclusions. **Exit code 3** = ambiguous language or profile → go back to phases 2/2b and ask. It initializes **OpenSpec** in the repo (`openspec/`, skills and `/opsx:*` commands) unless `--no-openspec`; exit code 4 with `--openspec yes` indicates the CLI is missing. It installs the `cognee-memory` plugin and the MCP by default (run from the repo; `--no-plugin` skips it and prints the commands). **Data projects (dbt, Dataform, Databricks, BigQuery, Snowflake) are set up automatically in this same phase:** the lineage graph, the connection catalog, identifier discovery from the user's authenticated CLIs (gcloud/bq, snow, databricks), and enabling read-only live metadata for every environment whose probe succeeds. Read-only, metadata only, never table data, no secrets stored; failures are reported, not fatal, and retried after 24 h.

## Phase 5 — Pilot corpus
Use the `project-memory-bootstrap` skill (already installed): read the real documentation, write `project.md` and `architecture.md` as `draft`, and propose 10–20 documents (decisions, implementations, business rules, runbooks **that are not already in `CLAUDE.md`**). List the gaps instead of filling them in; `status: verified` only after checking. If the repo uses **OpenSpec**, its specs and changes are already among the contract's sources: do not copy them into `docs/agent-memory/`.

## Phase 6 — Index (spends tokens; report the cost at the end)
```bash
seed-bundle/seed.sh index <repo>         # plan, then --apply: ≈ 2 Claude calls per chunk (15 docs ≈ 74 calls, 6 min)
```
Run it without asking and include the cost in your final report. Expected: all `indexed`. For data projects the graph and connection documents are queued by the first session's hook, in the background, 60 documents per run (`data_graph.max_baseline_docs`); `seed.sh index` indexes them all now. From then on only changed documents are re-indexed.

## Phase 7 — Control panel (Management Memory)
```bash
seed-bundle/seed.sh panel --yes          # http://127.0.0.1:45876 — read-only
```
It lives **inside the kit** (`panel/`): it clones nothing. It installs (macOS) the on-demand launchd trigger for "Measure the machine now" (no resident process), refreshes `view/usage.jsonl`, runs `panel/scripts/setup.py` (creates its `.env` 0600 and the read-only Postgres role; does not print secrets) and does `docker compose up -d --build` (2 containers). It shows health, vectors, graph, PostgreSQL, tokens/cost, memory usage, resources and size per project. To stop: `docker compose stop` in `panel/` (never `down -v`). To measure Claude Code tokens, open sessions with `scripts/claude-memory <project_id>`.

## Phase 8 — Verify and deliver
```bash
seed-bundle/seed.sh verify <repo>
scripts/memctl.sh eval <repo>            # with evals/cases.<project_id>.jsonl (20 questions; see evals/cases.example.jsonl)
```
Acceptance: API ready, observer reachable from the container, panel on :45876, MCP connected, briefing < 6000 characters, correct retrieval in top-5. Close with the `project-memory-handoff` skill, commit `docs/agent-memory/`, `.agent-memory/` (except `local.yaml`) and `CLAUDE.md` through the repo's normal flow, and deliver: what was installed, where, what it cost (tokens), how to disconnect (`claude plugin disable cognee-memory@cognee`, `claude mcp remove agents_cognee`) and the consumption review date (one week: `scripts/weekly_report.py`).

## Phase 9 — Agent swarm (optional: only if the user asks for it)
The swarm is NOT part of the zero-touch memory install. When requested: read `docs/SWARM_REPLICATION.md` and follow it. Order: `seed.sh swarm-init` (once per machine: schema, roles, runner image), then per project **analyse first** (`seed.sh harness <repo>` runs `install_harness.py analyze`), decide the agents with the user, and **ask whether the roles go global (`~/.claude/agents`) or inside each repo**; the installer exits 3 without `--scope`. Dry run first, then `--apply`; never apply `--cleanup` to agents the team still uses. Ask whether the git agent may merge PRs on its own (`gitops.auto_merge`). The Docker mode needs the subscription token (`claude setup-token`, then `swarm token save`); local mode does not.

## Data projects: what is automatic
- **Graph:** `data_graph.py` rebuilds from the repo (using `manifest.json` / `dataform compile` when present). Query it instead of reading files: `data_graph.py impact|upstream|downstream|show|path|check`.
- **Connections:** read `docs/agent-memory/connections.md`; never ask the user how to connect. `data_connect.py check` shows tools and variables on this machine.
- **Keeping current:** the session-start hook fingerprints the repo and (where enabled) live metadata; it rebuilds and re-indexes only what changed.

## What the system remembers once installed (verify it in the first session)
- **Briefing on session open:** goal, decisions, rules, pending items, deployments, security, active OpenSpec changes, current branch checkpoint and last handoff.
- **Deployments** (`scripts/memory_deploy.py record <repo> <environment> --commit <sha>`): which commit is deployed per environment and the state of each branch. Recorded **only after verifying**. In data projects, "deployed" = the production job/release finished successfully on that commit.
- **Versions and security** (`memory_deps.py`, `memory_audit.py`): inventory of direct dependencies with history (`security` if the commit cites a CVE/GHSA), OSV audit launched automatically on session open (at most every 24 h, in the background, fails silently without network) and pending items in `docs/agent-memory/security/dependencies.md`. To accept a risk: `.agent-memory/security-ignore.txt`. To manually record a prior change: `memory_deps.py note <repo> --pkg X --reason security --cve CVE-... --date AAAA-MM-DD`.
- **OpenSpec drives every implementation or change** (mandatory rule in `CLAUDE.md`): `/opsx:propose` → user review → `/opsx:apply` → `/opsx:archive`; without an active change, no product code is written (exceptions: typos, formatting, urgent hotfix documented afterwards). Its specs (current) and changes (active and archived) are indexed with `memctl.sh sync` and the briefing lists the active ones.
- **When facing ambiguity the agent consults memory before deciding or asking** (rule in `CLAUDE.md`).

## Uninstall a project
Disconnect the plugin and MCP (above), delete `.agent-memory/`, `docs/agent-memory/` (if the user wants), the `CLAUDE.md` section and the hooks in `.claude/settings.local.json`. That project's Cognee data is removed with `forget` **on the specific dataset** (never `everything`).
