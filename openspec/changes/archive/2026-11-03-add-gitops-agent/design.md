# Design

## Context
The swarm already creates one worktree and branch per change and commits per task. Missing: a component that guarantees sync with the remote and manages pull requests. The user asked for a git-expert agent launched before a change starts and after every task.

## Decisions
1. **Deterministic core + model on demand.** `swarmlib/gitops.py` does fetch, ahead/behind, clean checks, push, PR and merge with plain commands. The `gitops` role (a model) is launched only for conflicts. Most phases therefore cost zero tokens.
2. **Merge, not rebase.** Updating a change branch uses `git merge origin/<main>`: no force push is ever needed and published history is never rewritten.
3. **Host only.** Credentials never enter containers; the git phase runs on the host in every mode. `gh` is injected behind a small client so tests use a fake and a real read-only smoke test uses the real CLI.
4. **Merge policy in code** (approval valid, verdict passed, health passed, no failing checks, up to date) with `gitops.auto_merge` in `policy.yaml`. This amends the earlier rule "agents never merge": the git agent merges, only through a pull request, only under policy. The still-active `swarm-harness-platform` change is edited accordingly (its approval is voided and renewed).
5. **Guard by role.** The hook allows `git push` of non-main branches and `gh pr` commands only for role `gitops`; every other role keeps the full block list. Force pushes, pushes to the main branch and hard resets are blocked for everyone.
6. **Graceful degradation** with no remote or no `gh`.

## Risks
- Auto-merge removes a human check: mitigated by the policy conditions and the off switch.
- A conflict resolved by a model: mitigated by re-running health and the reviewer afterwards.
