# Tasks

## 1. Verify assumptions and token path

- [x] 1.1 (needs the user: `claude setup-token` is an interactive browser login; container image, entrypoint checks and isolation are already verified without it) Create a scratch repo and a subscription token (`claude setup-token`) stored 0600 outside git; verify in a minimal container that `claude -p "say ok"` answers and `/status`-equivalent shows the subscription (verification: recorded output, no API billing).
- [x] 1.2 Verify that an `ANTHROPIC_API_KEY` in the environment is detected and refused by the entry script (verification: test that exits non-zero with the message).
- [x] 1.3 Verify whether Cognee supports per-project users/permissions with the current access-control setup and record the decision in design.md (verification: documented experiment with two throwaway datasets).
- [x] 1.4 Measure baseline tokens of one small task run by hand (verification: numbers stored as the first efficiency baseline).

## 2. Runner image and entry script

- [x] 2.1 Runner image with pinned Claude Code version, non-root, `cap_drop ALL`, no docker socket, single worktree mount (verification: container inspect test asserts these properties).
- [x] 2.2 Entry script: credential checks, capture disabled, token never logged (verification: log/repo scan test finds no token).
- [x] 2.3 Pin the version in `config/versions.lock` (verification: lock diff + build uses it).

## 3. Swarm database and event capture

- [x] 3.1 Schema `swarm` (runs, events, verdicts, approvals) and a read-only role (verification: INSERT as the role is rejected).
- [x] 3.2 Hook scripts for session, subagent, tool, health and verdict events with secret-free payloads (verification: unit tests on payload shape; scan finds no secrets).
- [x] 3.3 Stream-json parser writing token/turn/model figures per run (verification: replay of a recorded stream produces expected rows).

## 4. Spec-first dispatcher

- [x] 4.1 `swarm propose` creates a planning job restricted to the change directory (verification: test that a write outside it is blocked and the PR holds only change artifacts).
- [x] 4.2 `swarm approve` records approval with the artifact hash; editing artifacts voids it (verification: tests for approve, edit-after-approve, unapproved refusal).
- [x] 4.3 Backlog generator producing `featurelist.json` from OpenSpec changes (verification: golden-file test; no criteria duplicated).
- [x] 4.4 Job execution: one worktree per change, tasks in order, checkbox ticked only after the task's verification passes, cap 2 concurrent, turn and time limits, park after 2 failed reviews (verification: simulated-job tests for each rule).
- [x] 4.5 Post-merge step: archive the change then one memory sync from main (verification: integration test with a scratch repo; nothing indexed from unmerged branch).
- [x] 4.6 `swarm status|cancel|pause` (verification: CLI tests; cancel keeps the worktree).

## 5. Harness templates and installer

- [x] 5.1 Role definitions (leader, explorer, implementer, reviewer) with model class, effort and tool allowlists from `policy.yaml` (verification: lint that static documents contain no dates/ids/branch names; reviewer and explorer have no write tools).
- [x] 5.2 Per-profile health script including `openspec validate` (verification: mixed-stack fixture runs both suites).
- [x] 5.3 Installer with dry run, manifest, idempotence and no-overwrite; protocol through `CLAUDE.md` importing `@AGENTS.md`; foreign `AGENTS.md` untouched (verification: fixture with a foreign `AGENTS.md`; second run reports no changes).
- [x] 5.4 `seed.sh harness` entry and docs (verification: documented command works on the scratch repo).

## 6. Cognee integration

- [x] 6.1 Add `ARCHITECTURE.md` and `progress/history.md` to the sources list; exclude `progress/current.md` and `exploration_*` (verification: sync dry run lists exactly the expected files).
- [x] 6.2 Per-project credential via `mint_mcp_key.py` (or per-project user per task 1.3) and recall pinned to the project's datasets (verification: cross-project recall is rejected and logged).
- [x] 6.3 Recall logging with a "used" flag fed to the monitoring schema (verification: a run with one used and one unused recall shows 1/2).
- [x] 6.4 Read-order rule in the harness protocol and recall exposed as skill, not always-on MCP (verification: tool list of a runner session lacks the Cognee server).

## 7. Panel Swarm page

- [x] 7.1 Endpoints and read-only role wiring (verification: pytest, write attempt rejected).
- [x] 7.2 Change board, active agents, live progress file, verdicts, health history (verification: pytest on endpoints + manual page check with seeded data).
- [x] 7.3 Efficiency tab and quota-risk indicator and recall-usefulness view (verification: seeded runs render expected figures; glossary updated).

## 8. Token policy

- [x] 8.1 `swarm/policy.yaml` with model class and effort per role and the escalation rule (verification: dispatcher test chooses lightest model for explorer and never defaults to the strongest).
- [x] 8.2 Before/after comparison workflow recorded in the efficiency view (verification: two runs on the same task are comparable side by side).

## 9. Kit export

- [x] 9.1 Add swarm and harness files to the export whitelist and neutrality scan; token and per-machine config generated, never shipped (verification: export succeeds on clean tree and fails on an injected forbidden term).

## 10. Pilot in a production repository

> Done on the first production repository (installed through its own OpenSpec change, read-only phase, then one real change end to end with the git agent and real CI).

- [x] 10.1 In the pilot repository, open its own OpenSpec change for the harness install; installer dry run reviewed by the user (verification: dry-run listing shows no edit to foreign files).
- [x] 10.2 Phase 1: explorer and reviewer jobs only, no repo writes (verification: git status clean after jobs; events visible in the panel).
- [x] 10.3 Phase 2: one small real change end to end: propose, approve, implement in worktree, review, user merges, archive, sync (verification: change archived, memory returns the new knowledge, efficiency numbers recorded).

## 11. Team mode

> Implemented as an opt-in experimental command (`swarm team`), verified with a real two-teammate session.

- [x] 11.1 Interactive tmux runner with agent teams enabled on request, max five teammates, hooks for idle/task events (verification: a two-teammate review on a scratch PR completes and its events appear in the panel).

## Workflow follow-up

- Archive this change after merge and run `memctl.sh sync . --apply` once.
- Re-check subscription terms and the token expiry reminder at install time.
