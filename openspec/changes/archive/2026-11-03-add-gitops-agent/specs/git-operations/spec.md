# Spec Delta

## Purpose
Keep local branches, the main branch and GitHub in sync around every task, through one git-expert agent, without force pushes and without direct pushes to the main branch.

## ADDED Requirements

### Requirement: Git agent runs around every task
The dispatcher SHALL run the git agent before the first task of a change, after every task, and when the change passes review, and MUST NOT start a task if the preflight reports a blocking problem.

#### Scenario: Preflight before the first task
- **WHEN** an implementation job is about to start
- **THEN** the git agent fetches the remote, fast-forwards the local main branch, ensures the change branch and its worktree exist and contain the latest main branch, and reports the result before any task runs

#### Scenario: Blocking problem
- **WHEN** the preflight finds a dirty worktree it did not create or an unresolved merge conflict
- **THEN** no task starts and the change is marked as needing attention

#### Scenario: Postflight after a task
- **WHEN** a task is ticked and committed
- **THEN** the git agent verifies that the worktree is clean, pushes the change branch, and creates or updates the pull request so that code and GitHub match

### Requirement: Deterministic first, model only for judgment
The git agent SHALL perform its checks with deterministic commands and MUST call the model only to resolve a situation that needs judgment, such as a merge conflict.

#### Scenario: Clean repository
- **WHEN** the repository is clean and in sync
- **THEN** the git phase completes without any model call and records its result as an event

#### Scenario: Conflict
- **WHEN** merging the main branch into the change branch conflicts
- **THEN** a model-backed git agent resolves it with plain merge commits, and the dispatcher re-runs the health script before continuing

### Requirement: Branch updates never rewrite published history
The git agent MUST update a change branch by merging the main branch into it, and MUST NOT force-push, rebase published branches or push to the main branch.

#### Scenario: Forbidden git commands
- **WHEN** the git agent attempts `git push --force`, `git push` to the main branch, or `git reset --hard`
- **THEN** the guard blocks the command and records a blocked event

### Requirement: Merge policy
The git agent SHALL merge a pull request only when the change has a valid approval, the latest review verdict passed, the health script passed, no required check is failing, and the branch contains the latest main branch; the policy flag `gitops.auto_merge` MUST be able to disable merging so that the user merges instead.

#### Scenario: Policy holds
- **WHEN** every merge condition holds and auto-merge is enabled
- **THEN** the pull request is merged, the local main branch is fast-forwarded, and the merged branch and worktree are removed

#### Scenario: Policy does not hold
- **WHEN** any merge condition fails or auto-merge is disabled
- **THEN** the pull request stays open and the report names the failed condition

### Requirement: Works without a remote and without GitHub access
The git agent SHALL degrade gracefully: with no remote it checks local consistency only, and when the GitHub CLI is unavailable it still pushes and reports that no pull request could be managed.

#### Scenario: No remote
- **WHEN** the repository has no remote
- **THEN** the git phases verify main, branch and worktree consistency locally and report the remote as absent without failing

### Requirement: Credentials stay on the host
The git agent MUST run on the host with the user's own git and GitHub credentials and MUST NOT place those credentials in a container.

#### Scenario: Role placement
- **WHEN** the git agent job is launched in docker mode
- **THEN** it still runs on the host and the container runner never receives git or GitHub credentials
