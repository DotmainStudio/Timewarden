# swarm-memory Specification

## Purpose
Keep Cognee as the single long-term memory for the swarm: one home per fact, no cross-project leakage and no pollution from unfinished work.

## Requirements

### Requirement: One home per fact
Backlog and status SHALL live in the OpenSpec changes, ephemeral task state in `progress/current.md`, run telemetry in the swarm database, and durable knowledge in project documents indexed into Cognee; ephemeral state and telemetry MUST NOT be indexed.

#### Scenario: Current progress file
- **WHEN** memory sync runs
- **THEN** `progress/current.md` is not indexed

### Requirement: Existing dataset reused
Swarm knowledge (architecture document, history log, archived specs and decisions) SHALL be indexed into the project's existing knowledge dataset through the existing sync, and the system MUST NOT create an additional dataset per project for the swarm.

#### Scenario: Dataset list
- **WHEN** a project is harnessed and the swarm runs
- **THEN** the project still has only its knowledge and sessions datasets

### Requirement: Write only from merged state
Indexing SHALL run only from the main branch checkout after a merge, never from a job worktree.

#### Scenario: Unmerged work
- **WHEN** a job has written a history entry in its branch that is not merged
- **THEN** a memory query returns nothing about that entry

### Requirement: Read order
Agents SHALL use the deterministic startup briefing first, then direct reading of small documents, and Cognee recall only when the corpus is large or the question crosses documents, and every recall SHALL be logged with whether its result was used.

#### Scenario: Small corpus
- **WHEN** the answer is in a document of a few pages
- **THEN** the agent reads the file instead of calling recall

### Requirement: Project isolation
Each project SHALL be identified by its `project_id` and datasets from `.agent-memory/project.yaml` (never by working directory), cross-project recall MUST remain disabled, and each runner SHALL use a credential restricted to its project's datasets.

#### Scenario: Cross-project query
- **WHEN** an agent of project A asks for a dataset of project B
- **THEN** the request is rejected and logged

### Requirement: No automatic raw-session capture in swarm runs
Swarm runs MUST NOT use automatic raw-session capture; durable lessons SHALL enter memory only as reviewed documents.

#### Scenario: Capture setting
- **WHEN** a runner starts
- **THEN** capture is disabled in its environment
