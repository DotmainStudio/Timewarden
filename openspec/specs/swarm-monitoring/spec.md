# swarm-monitoring Specification

## Purpose
Let the user see, read-only, what every agent is doing, what it decided, what it cost and whether it worked.

## Requirements

### Requirement: Event capture
The runner SHALL record structured events for session start/stop, subagent start/stop, tool use, health-script results, reviewer verdicts and memory recalls into a dedicated database schema, and events MUST NOT contain secrets or file contents beyond metadata.

#### Scenario: Subagent lifecycle
- **WHEN** the leader delegates to an implementer
- **THEN** start and stop events with role, model and duration are stored

### Requirement: Read-only Swarm page
The panel SHALL provide a Swarm page showing the change board (awaiting approval, approved, in progress, review, done, parked), active agents, the live progress file, reviewer verdicts and health-script history, and MUST access the data through a read-only database role.

#### Scenario: Write attempt
- **WHEN** the panel's database role attempts an INSERT, UPDATE or DELETE on the swarm schema
- **THEN** the database rejects it

### Requirement: Efficiency view
The panel SHALL show per run and per role the input and output tokens, cache-read share, turns, context usage at the end, retries, model mix, and a quota-risk indicator.

#### Scenario: Run comparison
- **WHEN** two runs of the same task use different policies
- **THEN** the page lets the user compare their token and outcome figures side by side

### Requirement: Memory usefulness
The page SHALL show how many memory recalls each run made and how many were used, so unproductive recall can be removed.

#### Scenario: Unused recall
- **WHEN** a run made recalls whose results were not used
- **THEN** the page flags them
