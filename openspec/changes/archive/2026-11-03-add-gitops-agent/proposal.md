# Add a git-operations agent to the swarm

## Why

Branches, pull requests and merges are currently done by hand or by loose dispatcher commands. Nothing guarantees that, before a task starts, the local checkout and GitHub agree, nor that after a task the code, the branch and the pull request are in sync. A dedicated, git-expert agent closes that gap and keeps the main branch and every change branch up to date without force pushes.

## What Changes

- New role `gitops`: an expert in git and the GitHub CLI, launched by the dispatcher **before the first task** of a change and **after every task**, and once more when the change passes review.
- Deterministic checks run first (no model call when everything is clean); the model is used only to resolve what needs judgment, such as merge conflicts.
- The agent creates and updates the pull request, keeps the change branch up to date with the main branch by merging (never force-pushing), merges the pull request when the merge policy holds, and refreshes the local main branch and prunes merged branches and worktrees.
- It runs on the host (it needs the user's git and GitHub credentials, which are never placed in containers), with its own guard rules.
- The previous rule "agents never merge" becomes "only the git agent merges, only through a pull request, only when policy holds".
- Replication guide and presentation describe the new agent.

## Capabilities

### New Capabilities
- `git-operations`: preflight, postflight and finalize behaviour of the git agent, its guard rules and merge policy.

### Modified Capabilities
<!-- spec-first-delivery "The user keeps the merge" is amended inside the still-active swarm-harness-platform change; see design.md -->

## Impact

- `swarm/policy.yaml` (new role), `swarm/swarmlib/gitops.py` (new), `swarm/swarmlib/jobs.py` (hooks into the task loop), `swarm/runner/hooks/swarm_hook.py` (role-specific git rules), `templates/harness/roles/gitops.md`, installer role list, docs and deck.
- No change to memory datasets. Merging is now automated under policy: the user can turn it off with `gitops.auto_merge: false`.
