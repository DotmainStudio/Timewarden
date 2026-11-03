# swarm — spec-first agent swarm (local, on your Claude subscription)

Runs the official `claude` CLI as small jobs, one OpenSpec change per git worktree, and records everything in Postgres (schema `swarm`) for the read-only **Swarm** page of the panel. Memory stays in Cognee, untouched.

```
idea ──► swarm propose ──► PR with spec ──► you review/merge ──► swarm approve
      ──► [git agent: preflight] swarm implement (task by task, script ticks, [git agent: postflight] after each)
      ──► swarm review (every scenario needs evidence) ──► [git agent: finalize: PR ready, merge if policy holds]
      ──► swarm post-merge (archive on its own branch + ONE memory sync from clean main)
```

## Commands (`swarm --repo <path> [--mode docker|local] <cmd>`)
| Command | What it does |
|---|---|
| `init-db` | schema + roles (`swarm_writer`, `swarm_reader`); stores the reader password in `panel/.env` (0600) |
| `propose "<idea>" [--change id]` | planning job (writes only `openspec/changes/<id>/`); exit 3 + questions if the planner needs answers |
| `approve <change>` | validates (`openspec validate --strict`) and records the artifact hash; editing artifacts later voids it |
| `implement <change> [--max-tasks n]` | refuses without a valid approval; runs tasks in order; ticks a task only after health + its backticked verification pass |
| `review <change>` | read-only reviewer; script judges: a scenario without evidence fails; parked after 2 failed reviews |
| `post-merge <change>` | after YOU merged: archive (own branch) then one `memctl.sh sync` from clean main |
| `backlog` | regenerates `featurelist.json` (a projection; never hand-edit) |
| `status` / `pending` / `sync-state` | board, open tasks, push state to the panel database |
| `git preflight\|postflight\|finalize <change>` | run a git-agent phase by hand (normally automatic) |
| `team "<task>" [--teammates n]` | experimental interactive agent team in tmux (max 5 teammates), on request only; auto-trusts the folder, closes the session when the lead is done |
| `explore "<question>"` | read-only explorer; proves the working tree is unchanged |
| `cancel <run>` / `pause` / `resume` | stop a job (worktree kept) / stop the dispatcher accepting jobs |
| `doctor` | credential, token file (0600 + days left), tools, Postgres |

`--mode docker` (default) = hardened container with the subscription token (`~/.config/swarm/oauth_token`, from `claude setup-token`).
`--mode local` = runs the host `claude` with your own login (no Docker, no token file); same hooks, limits and gate. Use it to start.

## Policy and limits — `swarm/policy.yaml`
Model class and effort per role (explorer haiku/low, implementer and reviewer sonnet/medium, leader sonnet/medium; opus only on escalation), tool allowlists (explorer and reviewer read-only; reviewer's container mount is `:ro`), turn and time limits, cap of 2 concurrent jobs, park after 2 failed reviews. `SWARM_POLICY=<file>` overrides it (still validated).

## Git agent (`gitops`)
An expert in git and the GitHub CLI. The dispatcher launches it **before the first task**, **after every task** and **when review passes**. It checks with plain commands first (zero tokens when clean) and uses the model only for merge conflicts.
- *preflight*: fetch, fast-forward local main, branch + worktree exist and are clean, branch contains the latest main (by **merging** main into it; never rebase, never force-push). Blocks the task if main has unpushed commits, the worktree is dirty or a conflict cannot be resolved.
- *postflight*: worktree clean (code committed), branch pushed, draft pull request created or reused.
- *finalize*: PR ready; merged only if the approval is valid, the latest verdict passed, all tasks are done, `health.sh` passes, required checks are not failing/pending and the branch is up to date; then local main is fast-forwarded and the branch/worktree removed. `gitops.auto_merge: false` in `policy.yaml` leaves the merge to you.
- Runs on the **host** (your git/gh credentials never enter a container). No remote or no `gh`: degrades to local checks.

## Safety
Hooks (`runner/hooks/swarm_hook.py`) block `git push/merge` (except for the git agent, which may push non-main branches), force pushes, pushes to main, rebases, hard resets, deploys, container control, piping downloads into a shell and, for planning jobs, any write outside the change directory. Containers: non-root, `cap_drop ALL`, no docker socket, only the worktree mounted, token passed by name (never in argv), refuses `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`.

## Tests
`python3 -m pytest tests/swarm -q` (pure logic, real Postgres in a throwaway DB, real git, fake `claude`, container isolation if the image is built). Panel: `cd panel && pytest`.

Replicating on another machine or project: `docs/SWARM_REPLICATION.md`.
