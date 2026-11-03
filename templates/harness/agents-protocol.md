# AGENTS.md

Entry protocol for agents working in this repository. Keep this file stable: no dates, ids, branch names or metrics.

## Read order
1. The startup briefing (already in context). 2. Small documents directly (`ARCHITECTURE.md`, `docs/agent-memory/`). 3. Memory recall only when the corpus is large or the question crosses documents: `python3 -I /opt/swarm/recall.py "<question>"` (swarm runs) or the `project-memory-recall` skill (interactive sessions).

## Spec first
Product code is written only for tasks of an approved OpenSpec change (`openspec/changes/<id>/`). Execute tasks in order, one at a time. Do not tick checkboxes: the dispatcher ticks a task after its verification passes.

## Definition of done
`bash scripts/health.sh` exits 0 after your change. Never report a task complete otherwise.

## Boundaries
Only the git agent (`gitops`) pushes branches, opens pull requests and merges, under the merge policy; every other role does not push, merge, rebase or reset, and nobody force-pushes or pushes to the main branch. Deploys and container control belong to the user. Do not read or write outside this working tree. Never print or store credentials.

## Progress
Keep `progress/current.md` short (what is done, what is next). Durable lessons go to `docs/agent-memory/` as reviewed documents, not to chat.

## Roles
`leader` plans and delegates; `explorer` reads and summarises (read-only); `implementer` changes code; `reviewer` verifies against the spec scenarios (read-only); `gitops` keeps branches, pull requests and the main branch in sync. Subagents return a short synthesis and write details to files.
