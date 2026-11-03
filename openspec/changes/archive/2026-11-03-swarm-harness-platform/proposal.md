# Proposal

## Why

Claude Code can already do large pieces of software work, but today every session is driven by hand, one at a time, and the plan lives in the chat. The user wants a team of specialised agents that works on several projects in parallel inside Docker, using their Claude subscription (no API key), remembers through Cognee, and can be watched from the existing panel. Without a spec-first gate, an unattended swarm would build the wrong thing quickly; without measurement it would burn the subscription quota.

## What Changes

- **Spec-driven delivery is the entry point of the swarm.** Nothing is implemented unless an OpenSpec change (proposal, delta specs, design, tasks) exists AND the user approved it. The swarm's backlog is derived from OpenSpec changes, not written by hand. The Reviewer verifies against the spec's scenarios. Archive and memory sync happen after merge.
- A Docker **swarm platform** (dispatcher + runner) that runs the unmodified `claude` CLI authenticated with a subscription token, one git worktree and one PR per change, with concurrency and safety limits.
- A per-repo **harness** (the "Harness Engineering" file contract: `AGENTS.md`, `ARCHITECTURE.md`, `featurelist.json` as a generated view, `progress/`, `scripts/init.sh`, role definitions) installed non-invasively.
- **Cognee integration rules**: which data goes to memory, from where, when (after merge only), and how projects stay isolated. No new dataset.
- **Monitoring**: agent events and verdicts stored in Postgres and shown in a read-only "Swarm" page of the Management Memory panel, including a token-efficiency view.
- A **token-efficiency policy** (model routing per role, stable prefix, small toolkit, subagent isolation, per-job limits) measured and tuned with data.
- Pilot in a production repository: read-only roles first, then implementer in worktrees.
- No Strands Agents: it cannot use the subscription.

## Capabilities

### New Capabilities
- `spec-first-delivery`: the planning gate and the lifecycle from idea to merged, archived, remembered change (propose, approve, apply, verify, archive, sync).
- `swarm-execution`: how jobs run in Docker with the subscription token, worktree isolation, limits, and safety rules.
- `project-harness`: the per-repo file contract and the non-invasive installer.
- `swarm-memory`: what the swarm reads from and writes to Cognee, and the isolation between projects.
- `swarm-monitoring`: events, verdicts and token-efficiency data, and the read-only panel page.
- `agent-token-efficiency`: model routing, prompt stability, tool minimalism and limits, with measurement.

### Modified Capabilities
- `portable-bundle`: the distributable kit also carries the swarm and harness components and keeps the neutrality guarantees.

## Impact

- New: `swarm/` (dispatcher, runner image, `policy.yaml`), harness templates under `templates/`, `seed.sh harness`, a `swarm` CLI, a Postgres schema `swarm` with a read-only role, a panel page.
- Changed: `sync_markdown.py` sources list (adds `ARCHITECTURE.md`, `progress/history.md`), `dev/export_kit.sh` whitelist, `config/versions.lock` (pins the Claude Code version for the runner), `mint_mcp_key.py` (per-project key).
- External: depends on `claude setup-token` (one-year token) and on current subscription terms (personal, unmodified binary); both can change and are re-checked at install.
- Out of scope: Strands Agents, multi-user hosting, deploying to production from agents, editing the panel into a control surface.
