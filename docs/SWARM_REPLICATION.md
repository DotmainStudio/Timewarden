# Replicating the spec-first agent swarm on another project or machine

A complete, ordered specification: what to install, how to configure it, what to decide with the user, what to verify, and what to watch out for. Everything runs **locally** on a Claude subscription (no API key). Cognee memory keeps working exactly as before; the swarm lives next to it and never replaces it.

Read §0 first. The rest is reference, in the order you will need it.

---

## 0. Rules that apply to every installation

1. **Analyse the project before installing anything.** The harness is adapted to each repository (stack, test runners, existing agents, existing memory, existing CI). Never copy files blindly. Run the analysis, read it, decide the agents and the modifications with the user, then install.
2. **Ask the user where the roles live** (the installer refuses to continue without `--scope`, exit code 3):
   - `repo`: roles in `<repo>/.claude/agents/`, versioned with the project, no effect on other repos (recommended default).
   - `global`: roles in `~/.claude/agents/`, shared by every repo on the machine.
   Project knowledge (`AGENTS.md`, `ARCHITECTURE.md`, `progress/`, `scripts/health.sh`, the `CLAUDE.md` block) is always per repo.
3. **Dry run first.** The installer lists every file it would add or change; nothing is written without `--apply`.
4. **Never delete, never overwrite what the harness did not create.** A foreign `AGENTS.md` stays untouched (the protocol goes inline into `CLAUDE.md`). Existing agent definitions stay. Cleanup only *moves* files to `.agent-memory/legacy-backup/<timestamp>/` and only when asked.
5. **Ask the user about auto-merge per repository** (§6.4). In production repositories with CI on every PR it can be on; otherwise leave it off.
6. **One OpenSpec change per installation.** In a repo that follows spec-first rules, the harness install is itself an OpenSpec change (proposal, spec, design, tasks), reviewed and merged by PR.

---

## 1. Requirements

| Item | Version / note |
|---|---|
| macOS + Docker Desktop | validated on macOS (Docker engine 27.x, VM 8 GB). Linux untested; launchd pieces do not exist there |
| Claude Code | version pinned in `config/versions.lock` (`claude_code`); the runner image installs exactly that |
| Python | 3.12. The dispatcher and installer use the standard library only |
| `git`, `gh` (authenticated), `openspec` 1.15+ | `gh` for pull requests and the merge policy; `openspec` for validate/archive |
| `tmux` | only for team mode (`brew install tmux`) |
| Memory stack | Cognee 1.6.5 + Postgres (pgvector) from `deploy/docker/compose.yaml`; the dispatcher reaches Postgres through `docker exec` into the stack's container |
| Panel | `panel/` (FastAPI, read-only) |
| Claude subscription | Pro or Max. No `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` anywhere (§7) |

---

## 2. Install on a machine (once)

```bash
seed-bundle/seed.sh doctor            # checks requirements, changes nothing
seed-bundle/seed.sh machine --yes     # observer, Docker stack, keys (the existing memory install)
seed-bundle/seed.sh swarm-init        # = swarm init-db + build_runner.sh + swarm doctor
seed-bundle/seed.sh panel --yes       # (re)build the panel so it includes the Swarm page
```

What `swarm-init` does:
- Creates schema `swarm` (projects, changes, tasks, approvals, runs, events, verdicts, recalls, health, comparisons) in the stack's database and two roles: `swarm_writer` (DML on `swarm.*`, used by the dispatcher) and `swarm_reader` (SELECT only, read-only transactions, 15 s timeout, used by the panel).
- Generates the reader's password and stores it in `panel/.env` (mode 0600, gitignored, never printed). Re-running keeps it.
- Builds image `swarm-runner:local` with the pinned Claude Code: non-root uid 10001, git, python3, ripgrep, hooks and entrypoint baked in. **Rebuild the image after changing the hooks or `runner/settings.json`** (`swarm/build_runner.sh`).
- Schema changes are idempotent; re-run `swarm init-db` (or apply `swarm/schema.sql` as the DB admin) after pulling a newer kit.

### Subscription token (Docker mode only)
Local mode (`--mode local`) needs no token: it uses the logged-in `claude`. For Docker mode:
1. `claude setup-token` (interactive: authorise in the browser; a code may need pasting back). It yields a one-year token.
2. Store it **without printing it**: pipe the terminal output (or the token) into `swarm token save`. It extracts the `sk-ant-…` value and writes `~/.config/swarm/oauth_token` with mode 0600 (atomic). `swarm token status` shows permissions and days left; `swarm doctor` warns 30 days before expiry.
3. Verify with `swarm --repo <any repo> verify-docker` (§9).

---

## 3. Install in a project

```bash
# 0) memory contract first, if the repo does not have it yet
scripts/install_project.py <repo> --project-id <id>

# 1) analyse (writes nothing)
python3 -I scripts/install_harness.py analyze <repo>

# 2) install: dry run, then apply (scope is mandatory)
python3 -I scripts/install_harness.py install <repo> --scope repo|global
python3 -I scripts/install_harness.py install <repo> --scope repo|global --apply

# 3) make the project visible in the panel
swarm --repo <repo> sync-state
```
Shortcut: `seed-bundle/seed.sh harness <repo> [--scope repo|global] [--apply] [--cleanup]` runs analysis then install.

### 3.1 What the analysis reports
Project id, detected profile (webapp, dbt, dataform, python-lib, …), **test runners and type checks in the root and in every immediate subdirectory** (monorepos), whether memory and OpenSpec are installed, a foreign `AGENTS.md`/`CLAUDE.md`, legacy candidates, and the **proposed agents** (role, model, effort, tools, stack rules injected from the profile) and **proposed modifications**.

### 3.2 What gets created (never overwritten if it exists)
- `AGENTS.md` only if absent (the protocol file, `templates/harness/agents-protocol.md`); otherwise the protocol goes inline into `CLAUDE.md`.
- `ARCHITECTURE.md`, `progress/current.md`, `progress/history.md` (templates).
- `scripts/health.sh`, generated from the detected runners (§3.3).
- Five role files: `leader`, `explorer`, `implementer`, `reviewer`, `gitops` (generic; stack rules come from the profile).
- A marked block `<!-- swarm-harness:begin -->…<!-- swarm-harness:end -->` in `CLAUDE.md`.
- `.agent-memory/project.yaml`: adds `ARCHITECTURE.md` and `progress/history.md` to `sources`, and `progress/current.md` and `exploration_*` to `exclude`. The datasets are untouched.
- `.agent-memory/harness-manifest.json`: lists what the installer owns, so a second run reports "no changes" and only the installer's own files are ever updated.

### 3.3 Adapt the health script to the project's CI
`scripts/health.sh` is the definition of done: a task is never ticked unless it exits 0. The generated script runs the detected checks, each inside its directory (`poetry run pytest` when a `poetry.lock` exists, `npm test`, `npx tsc --noEmit` for TypeScript without a test script, `go test`, `cargo test`, `openspec validate`). **Compare it with the project's CI workflow and add what is missing** (linters, architecture checks, environment variables such as a test settings module). The file is yours after creation. In repos used with git worktrees, make it reuse the main checkout's virtualenv and `node_modules` (resolve the main root with `git rev-parse --git-common-dir`), because worktrees do not carry ignored dependencies.

### 3.4 Cleanup of old configuration (`--cleanup`)
Lists legacy files: a hand-written `featurelist.json` (the new one is generated), `claude-progress.txt`, `init.sh`, `exploration_*`, and agent definitions not created by the harness. With `--apply` they are moved to the backup folder. **Review that list: the installer cannot tell an obsolete agent from one the team still uses.** In a repo that has its own agents, do not apply the agent entries; apply cleanup only for files that are truly obsolete.

### 3.5 Where to run the install from
A repo with uncommitted or untracked files of the user (for example another tool's `AGENTS.md`) should not be switched to a new branch. Do the install in a `git worktree` of the repo. If the user's untracked `AGENTS.md` is not in the worktree, copy it in temporarily so the installer sees it as foreign (and remove the copy before committing).

---

## 4. Memory: how it is configured and why it stays intact

- **Two datasets per project, unchanged:** `<project_id>-knowledge` (documents) and `<project_id>-sessions`. The swarm creates **no** dataset.
- **Git is canonical, Cognee is a derived index.** Memory is written only by `memctl.sh sync <repo> --apply`, run **once per milestone from a clean main checkout after the merge**; nothing from an unmerged branch is ever indexed. `swarm post-merge <change>` archives the change on its own branch (`chore/archive-<id>`), and the next sync indexes the updated specs.
- **Indexed:** `docs/agent-memory/**`, OpenSpec specs and changes, `ARCHITECTURE.md`, `progress/history.md`. **Not indexed:** `progress/current.md` (ephemeral) and all swarm telemetry (it lives in Postgres).
- **Read order for agents:** startup briefing (already in context) → read small files directly → recall only when the corpus is large or the question crosses documents. Inside swarm jobs, recall is an on-demand script (`runner/recall.py`), not an always-attached MCP server, so its tool schemas cost nothing per turn. Interactive sessions keep the existing `project-memory-recall` skill and MCP server.
- **Isolation between projects:** `recall.py` is pinned to `memory_dataset` in the project's `.agent-memory/project.yaml`; any other dataset is rejected and logged. `cross_project_recall: false` stays. *Per-project Cognee users do not work on 1.6.5* (a read grant is accepted but the search stays denied across tenants, and API keys are per user, not per dataset), so the pinned wrapper is the isolation mechanism.
- **Cognee API keys use the header `X-Api-Key`** (not Bearer).
- **No raw-session capture in swarm runs.** Jobs start with `--setting-sources ""`, so the user's and the project's hooks and plugins (the capture plugin, audit hooks that write into the repo) do not run inside swarm jobs; only the swarm's own hooks (`--settings`) apply. Authentication is unaffected. Durable lessons enter memory only as reviewed documents.
- **Recall usefulness** (recalls made vs used) is recorded per run and flagged in the panel.

### 4.1 Rotating the Cognee API keys
Three consumers hold a key: `panel/.env` (`COGNEE_API_KEY`), `deploy/docker/.env` (`COGNEE_MCP_API_TOKEN`) and `~/.cognee/.env` (`COGNEE_API_KEY`, the plugin). Procedure: mint new keys (`POST /api/v1/auth/api-keys`), write them into those files without printing them, recreate the MCP container and the panel, kill the plugin worker (`pkill -f _cloud_worker.py`, it respawns), verify each new key (a CHUNKS search with `X-Api-Key`), check panel and MCP health, and only then revoke the old keys (`DELETE /api/v1/auth/api-keys/{id}`). **The key-list endpoint returns key values: never print its output.**

---

## 5. Commands

`swarm --repo <repo> [--mode docker|local] <command>` (options before the command).

| Command | What it does |
|---|---|
| `init-db` | schema + roles; stores the panel reader password once |
| `doctor` | credential conflict, token file (0600, days left), tools, Postgres |
| `token save` / `token status` | store the subscription token from stdin (never printed) / show its status |
| `verify-docker` | one real container job with the stored token and a leak check (§9) |
| `propose "<idea>" [--change id]` | planning job; writes only `openspec/changes/<id>/`; exit 3 with the questions if the planner needs answers |
| `approve <change>` | validates (`openspec validate --strict`) and records the artifact hash |
| `implement <change> [--max-tasks n]` | refuses without a valid approval; git preflight, then tasks in order, git postflight after each |
| `review <change> [--no-git]` | read-only reviewer; script-judged verdict; on pass runs the git agent's finalize unless `--no-git` |
| `explore "<question>"` | read-only explorer; proves the working tree is unchanged |
| `git preflight\|postflight\|finalize <change>` | run a git-agent phase by hand |
| `post-merge <change> [--no-sync]` | archive on its own branch, then one memory sync from clean main |
| `team "<task>" [--teammates n]` | experimental interactive agent team in tmux (§8) |
| `backlog` / `status` / `pending` / `sync-state` | generated backlog, board, open tasks, push state to the panel |
| `cancel <run>` / `pause` / `resume` | stop a job (worktree kept) / stop accepting jobs |

Local mode runs the host `claude` with the login of the user (no Docker, no token file); it uses the same gate, hooks and limits. Start there.

---

## 6. How a change flows, and the rules the dispatcher enforces

```
idea ─► propose ─► spec PR ─► merge ─► approve ─► [git preflight] implement (task by task, script ticks)
     ─► [git postflight after each task] ─► review (every scenario needs evidence)
     ─► [git finalize: PR ready, wait for CI, merge if policy holds] ─► post-merge (archive + one sync)
```

### 6.1 Spec-first gate
No approved change, no implementation. `approve` stores a SHA-256 of proposal, design, specs and tasks (task checkboxes normalised, so ticking tasks does not void it); editing any artifact voids the approval. A planner that finds an ambiguity writes it under "Open questions" and stops (the CLI reports `needs_input`); an answer such as "None" is not a question.

### 6.2 Execution
One worktree and branch (`change/<id>`) per change, tasks in order, parallelism across changes only (cap 2). A task is ticked, and committed, by the dispatcher only after `health.sh` passes and, when the task states a backticked verification command, that command passes. Per-job turn and time limits; on a timeout the state is saved to `progress/current.md` and the change needs attention.

### 6.3 Verification
The reviewer is read-only (also mounted `:ro` in Docker) and answers a JSON per scenario. A script judges: a scenario without evidence fails and is named, `health.sh` must pass, two failed verdicts park the change. The reviewer may run the repository's `scripts/check*` verification scripts.

### 6.4 Git agent (`gitops`)
An expert in git and the GitHub CLI, launched before the first task, after every task and when review passes. It does everything with plain commands first (zero tokens when clean) and uses the model only to resolve merge conflicts (then `health.sh` runs again). It runs on the **host** (the user's git and `gh` credentials never enter a container).
- *preflight:* fetch, fast-forward local main (unrelated local edits are fine; git refuses only on conflicts), worktree present and clean, branch contains the latest main **by merging main into it**. Blocks the task if main has unpushed commits, the worktree is dirty or a conflict cannot be resolved.
- *postflight:* worktree clean (code committed), branch pushed, draft pull request created or reused.
- *finalize:* PR ready, **waits for the CI** (`gitops.wait_checks_minutes`, default 10), then merges only if the approval is valid, the verdict passed, all tasks are done, `health.sh` passes, required checks are not failing or pending and the branch is up to date. Then it fast-forwards main and removes the merged branch and worktree.
- Degrades gracefully: no remote = local checks only; no `gh` = push without a PR.
- **Policy in `swarm/policy.yaml`:** `gitops.auto_merge` (`false` = the agent opens the PR and the user merges), `gitops.merge_method` (`squash` or `merge`; match the repository's convention), `gitops.require_checks`, `gitops.wait_checks_minutes`, `gitops.check_poll_seconds`. The policy is global to the kit.
- **Guard rules (every role):** no force push, no push to main/master, no rebase, no hard reset, no deleting remote branches through push, no `gh pr merge` from a model. The git role may push non-main branches and run `gh pr` commands.
- Protect the main branch on GitHub (require PRs) so the server agrees with the guard.

### 6.5 Hotfix exception
Typos, formatting, comments and urgent fixes follow the repository's own rule and are documented with a change afterwards.

---

## 7. Subscription rules
- Use the official, unmodified `claude` binary with your own subscription, for your own work. Products for third parties require API keys and are out of scope; re-check the terms when you install and when the token is renewed.
- The runner **refuses to start** if `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set (they outrank the subscription token and would bill the API). The dispatcher and the container entrypoint both check, before any request (exit 64; missing token = exit 65).
- Concurrency defaults to 2 jobs. The panel's quota-risk indicator uses the utilisation figure Claude Code reports; at "high" run `swarm pause`.

---

## 8. Team mode (experimental, opt-in)
`swarm --repo <repo> --mode local team "<task>" --teammates 2` starts an interactive Claude Code session inside tmux with agent teams enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `--teammate-mode in-process`), at most `team.max_teammates` (5), because teammates are not spawned in `-p` mode. The first-run folder-trust dialog (its default is "No, exit") is answered "Yes"; the swarm hooks record `teammate_idle` and `team_task_completed`; when the lead's turn ends the session is closed with `/exit`; a session with no teammate activity is recorded as failed. The run appears in the panel as kind `team`, mode `interactive`. Attach with `tmux attach -t swarm-team-<project>-<run>`. Check its quota consumption before using it routinely.

---

## 9. Verify an installation

```bash
python3 -m pytest tests -q && (cd panel && pytest -q)     # all green
swarm doctor
swarm --repo <repo> verify-docker                          # real container + subscription token
swarm --repo <repo> --mode local explore "<a question>"    # read-only, tree proven unchanged
swarm --repo <repo> --mode local propose "<small idea>" --change <id>
swarm --repo <repo> approve <id> && swarm --repo <repo> --mode local implement <id>
swarm --repo <repo> --mode local review <id>
```
`verify-docker` checks: a live `ANTHROPIC_API_KEY` is refused (exit 64), the job answers, the run is recorded as `subscription-token`, the reported API-key source is none, tokens are recorded, the working tree is unchanged, and the token value appears nowhere (stream, events, stderr, database rows, working tree).
Open the panel `http://127.0.0.1:45876/#swarm`: runs with their assigned task, pending work, change board, verdicts, health history and efficiency must appear. Before sharing the kit, run `dev/export_kit.sh --no-zip`: it must report no forbidden terms or secrets.

Phased rollout for a production repository (recommended): (1) install through its own OpenSpec change and PR; (2) read-only phase: `explore` and `review --no-git`, confirm the tree is unchanged and events show in the panel; (3) one small real change end to end (a documentation change such as filling `ARCHITECTURE.md` is a good first one); (4) archive, one memory sync, confirm recall returns the new knowledge.

---

## 10. Things to consider

- **Specs are managed with OpenSpec** (behaviour and acceptance scenarios). Decisions, handoffs and architecture live in `docs/agent-memory/` and `ARCHITECTURE.md`, not in specs. After archiving, write a real *Purpose* in each new main spec (the archive leaves a placeholder that fails strict validation).
- **`ARCHITECTURE.md` is a template until someone fills it.** Agents know the stack type (profile rules), the briefing and memory, but not the system's architecture until that file is written and merged. Make filling it the first change.
- **Language:** role and protocol templates are English; the target repo's own documents keep their language. The planner should be told which language to write the spec in.
- **Merge method:** match the repository's history convention (`squash` vs `merge`).
- **Ephemeral state** is saved to the worktree on a timeout so work can resume.
- **Rollback:** stop using `swarm`; remove image `swarm-runner:local`; delete the files listed in `.agent-memory/harness-manifest.json` and the marked block in `CLAUDE.md`; `drop schema swarm cascade` if desired. No Cognee data is created beyond the existing datasets.

### Lessons from the first production pilot (already fixed in the kit)
| Finding | Fix |
|---|---|
| Local-mode jobs loaded the user's hooks: a capture plugin stored swarm sessions and an audit hook modified tracked files | jobs start with `--setting-sources ""` |
| The CI was still pending when the merge was decided | `finalize` waits for checks |
| Main could not be fast-forwarded when the user had unrelated local edits | try the fast-forward and let git decide |
| "None" under *Open questions* was reported as a question | recognised as an answer |
| The installer only looked at the repository root | monorepo detection per directory |
| `AGENTS.md` matched `.gitignore`, so its template was never committed | template renamed `agents-protocol.md` |
| The first-run trust dialog selects "No, exit" by default and closed team sessions | key sequence selects "Yes" |
| `--cleanup` offers a team's own agents as "legacy" | review the list; do not apply agent entries |
| Archiving leaves placeholder *Purpose* text | write the Purpose before merging the archive PR |

---

## 11. State of the reference installation

| Piece | Value |
|---|---|
| Memory stack | containers `agents_memory_system-agents_{postgres,cognee_api,cognee_mcp,otel_collector}-1`; API `127.0.0.1:45874`, MCP `45873`, OTLP `45875` |
| Datasets | `<project>-knowledge` and `<project>-sessions` per project; nothing added by the swarm |
| Panel | container `management_memory-mm_app-1`, `127.0.0.1:45876`, page `#swarm`; env in `panel/.env` (incl. `SWARM_PG_PASSWORD`) |
| Database | `agents_memory`, schema `swarm`; roles `swarm_writer`, `swarm_reader` |
| Runner | image `swarm-runner:local`, Claude Code pinned in `config/versions.lock`, non-root, `cap_drop ALL`, no Docker socket |
| Runs data | `~/.local/share/agents_memory_system/swarm/runs/<project>/<run>/` (stream and events) |
| Token | `~/.config/swarm/oauth_token` (0600, one year) |
| Policy | explorer haiku/low; implementer, reviewer, leader sonnet/medium; gitops sonnet/low (conflicts only); opus only on escalation; `gitops.auto_merge: true`, `merge_method: squash`, wait for CI up to 10 min; team max 5 |
| Baseline (haiku, small two-task change, local mode) | 5 runs, 37 turns, about 20k output tokens, 87% of input tokens served from cache |
| Tests | 167 in `tests/` (logic, real Postgres in a throwaway DB, real git, fake `claude`, container isolation, git agent with a real bare remote, team mode) + 24 in `panel/` |
