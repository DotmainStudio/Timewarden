# spec-first-delivery Specification

## Purpose
Make the OpenSpec change the single planning authority of the swarm: ideas become reviewed specs before any agent writes product code, and the same spec drives verification, archive and memory.

## Requirements

### Requirement: No implementation without an approved change
The swarm MUST NOT start an implementation job for work that has no OpenSpec change containing a proposal, delta specs, design (when applicable) and tasks, and MUST NOT start it until the user has approved that change.

#### Scenario: Idea without a change
- **WHEN** the user submits an idea or a task to the swarm
- **THEN** only a planning job is created, which writes the change artifacts and stops, and no implementation job is queued

#### Scenario: Change not yet approved
- **WHEN** a change exists but the user has not approved it
- **THEN** the dispatcher refuses to queue implementation jobs for it and reports it as awaiting approval

#### Scenario: Change edited after approval
- **WHEN** any planning artifact of an approved change is modified after the approval was recorded
- **THEN** the approval is treated as void and implementation jobs are not started until the user approves again

### Requirement: Planning jobs are spec-only
A planning job SHALL be allowed to write only inside the change's directory and its PR, SHALL explore the project and consult memory before proposing, and MUST ask the user (instead of guessing) when an ambiguity would change scope, behavior or acceptance criteria.

#### Scenario: Planning output
- **WHEN** a planning job finishes
- **THEN** a pull request contains only the change artifacts, and the job status is "awaiting approval"

### Requirement: Backlog derived from changes
The per-repo backlog (`featurelist.json`) SHALL be generated from the OpenSpec changes and their tasks, MUST NOT be hand-authored as a separate source of truth, and each entry SHALL reference its change id and take its acceptance criteria from the change's spec scenarios.

#### Scenario: Backlog regeneration
- **WHEN** a change is approved, progresses or is archived
- **THEN** regenerating the backlog yields an entry whose status reflects the change state, with no duplicated criteria text

### Requirement: Execution follows the tasks
An implementation job SHALL execute the tasks of an approved change in order, one worktree and one branch per change, ticking each task only after its stated verification passed, and SHALL run tasks of different changes in parallel but tasks of the same change sequentially.

#### Scenario: Task verification
- **WHEN** an implementer finishes a task
- **THEN** the task checkbox is ticked only if the task's own verification command or artifact check succeeded

### Requirement: Verification against scenarios
The Reviewer MUST verify the result against every scenario of the change's delta specs and against the project's health script, and SHALL record a structured verdict; a change is marked done only by a script after a passing verdict.

#### Scenario: Scenario without evidence
- **WHEN** a spec scenario has no test or recorded evidence
- **THEN** the verdict is failing and the finding names the scenario

#### Scenario: Repeated failure
- **WHEN** the Reviewer fails the same change twice
- **THEN** the change is parked and the user is notified instead of retrying again

### Requirement: Archive and remember after merge
After the user merges the pull request, the swarm SHALL archive the change (syncing its delta into the main specs) and then index the durable documents into Cognee, and MUST NOT index anything from an unmerged branch.

#### Scenario: Post-merge flow
- **WHEN** a change's pull request is merged
- **THEN** the change is archived, the main specs are updated, and memory sync runs once for the project

### Requirement: Merges only through the git agent, under policy
Implementation, planning and review agents MUST NOT merge to the main branch, push to it, or deploy; only the git agent (capability `git-operations`) MAY merge, only through a pull request and only when the merge policy holds, and the user performs any deployment and can disable agent merging.

#### Scenario: Attempted push to main
- **WHEN** an agent tries to push to or merge into the main branch outside the git agent's pull-request flow
- **THEN** the action is blocked by the runner's permissions and recorded as an event
