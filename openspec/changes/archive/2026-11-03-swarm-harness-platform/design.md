# Design

## Context

See proposal.md for motivation. Existing pieces reused: Cognee API/MCP and Postgres on network `agents_memory_net`, OTel collector, observer, Management Memory panel (FastAPI, read-only, role `mm_reader` pattern), Timewarden export with neutrality scan, project profiles, OpenSpec (mandatory, `openspec` CLI 1.15, skills `openspec-propose/apply/archive`), briefing and recall skills. Constraints: macOS + Docker Desktop (8 GB VM), personal use, subscription auth, user performs merges and deploys, repo and kit docs in English.

Verified external facts (checked 2026-11-02): `claude setup-token` yields a one-year token for `CLAUDE_CODE_OAUTH_TOKEN` (model requests only; `--bare` ignores it; `ANTHROPIC_API_KEY` outranks it); running the unmodified binary with one's own subscription is permitted while products for third parties need API keys; agent teams are experimental and are not spawned in `-p` mode. Not verified (treated as hypotheses): cache discount applicability to subscription quota, 20-40% context-degradation thresholds, 37%/3x tool-reduction figures.

## Goals / Non-Goals

**Goals:** spec-first autonomy on the subscription; one change = one worktree = one PR; Cognee as the only long-term memory; observable and cheap to run.

**Non-Goals:** Strands Agents (API/Bedrock providers only; wrapping `claude -p` would route plan credentials through a third-party harness); panel write actions; multi-user hosting; agents merging or deploying.

## Decisions

1. **OpenSpec is step zero, enforced by the dispatcher, not by agent goodwill.**
   Lifecycle: `swarm propose "<idea>"` -> planning job (explore + memory + `openspec-propose`, spec-only PR) -> user reviews -> `swarm approve <change>` (records approval + hash of the artifacts in the swarm DB) -> implementation jobs -> Reviewer verdict against scenarios -> user merges -> dispatcher runs archive and one memory sync. Alternative rejected: let the Leader decide whether a spec is needed (reintroduces "spec afterwards").
2. **Backlog is a generated projection.** `featurelist.json` is produced from `openspec/changes/*` (status, task progress, scenario list as acceptance criteria). Alternative rejected: hand-written backlog next to OpenSpec (two sources drift).
3. **Engine = official `claude` CLI in a container**, jobs via `claude -p --output-format stream-json`; team mode via tmux interactive later. Alternatives: Strands (no subscription), Agent SDK app (policy reserves API keys for products; support notes SDK usage with a plan still counts against plan limits but the terms are in flux).
4. **Parallelism across changes, sequence within a change.** Avoids file conflicts and merge races on `tasks.md` and the backlog.
5. **Roles are generic** (leader, explorer, implementer, reviewer); stack rules come from Timewarden profiles. The planning job runs as the leader with write access limited to the change directory.
6. **Done is written by a script**, after a structured reviewer verdict (JSON), never by an agent.
7. **Cognee: one home per fact, no new dataset**, writes only from merged main via existing sync; recall order briefing -> file -> Cognee. Sources list gains `ARCHITECTURE.md` and `progress/history.md`. Alternative rejected: `<id>-swarm` dataset (second isolation unit, schema churn, mixes unmerged work).
8. **Isolation key:** `project_id` from `project.yaml`; runner credential restricted per project. Whether Cognee supports per-project users/permissions is verified in the first Cognee task; if yes use it, else the recall wrapper pins datasets.
9. **Monitoring data:** hooks + stream-json -> dispatcher -> Postgres schema `swarm`; panel reads with a read-only role. OTel is complementary (token metrics), not the source of tool-level detail.
10. **Token policy in `swarm/policy.yaml`** (model class and effort per role, limits). Cognee is exposed through the recall skill, not an always-on MCP server, to avoid paying its tool schemas every turn.
11. **Claude Code reads `CLAUDE.md`, not `AGENTS.md`:** `CLAUDE.md` imports `@AGENTS.md`; existing foreign `AGENTS.md` is never edited.
12. **Pilot = the pilot repository** (production repo with foreign files): phase 1 read-only roles, phase 2 implementer in worktrees. The harness install there is itself an OpenSpec change in that repo.

## Risks / Trade-offs

- [Subscription terms or limits change; one-year token expires] -> re-check terms at install, expiry reminder, API-key side lane possible later.
- [Quota exhaustion from parallel jobs] -> concurrency cap 2, per-job limits, quota-risk indicator, pause command.
- [Cross-project memory leakage] -> per-project credential, `cross_project_recall: false`, rejection logged.
- [Runaway or destructive agent] -> worktree-only mount, no docker socket, no secrets, no push to main, user merges.
- [Approval hash too strict, annoying] -> hash only planning artifacts, not code; `swarm approve` is one command.
- [Spec ceremony slows small fixes] -> repo rule already exempts typos, formatting, comments, urgent hotfixes (documented afterwards); the swarm accepts a `--hotfix` job type that still records a change afterwards.
- [Recall costs more than reading files] -> enforced read order and recall-usefulness metric.
- [Foreign files in the pilot repository damaged] -> dry-run listing, no overwrite, read-only first phase.

## Migration Plan

Build in this repo, test on a scratch repo, then pilot in the pilot repository phase 1 -> phase 2. Rollback: stop the dispatcher, remove `swarm/` containers, delete harness files listed by the installer's manifest; no data in Cognee is created beyond existing datasets.
