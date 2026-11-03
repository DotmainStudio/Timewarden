# Spec Delta

## Purpose
Run agent jobs in Docker with the official Claude Code CLI on the user's subscription, isolated per change, bounded in cost and blast radius, and controllable from a command line.

## ADDED Requirements

### Requirement: Subscription authentication only
The runner SHALL authenticate with a long-lived subscription token supplied through the environment, MUST use the unmodified published `claude` binary, and MUST refuse to start if an API key or bearer-token variable that would take precedence over the subscription is present.

#### Scenario: Conflicting credential
- **WHEN** `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set in the runner environment
- **THEN** the runner exits with an explanatory error before sending any request

#### Scenario: Auth check
- **WHEN** a job starts
- **THEN** the runner confirms the active credential is the subscription and records that fact in the job's events

### Requirement: Token handling
The token MUST be stored only in a file readable by the owner, MUST NOT appear in logs, events, memory or committed files, and the system SHALL warn the user before its one-year expiry.

#### Scenario: Log scan
- **WHEN** logs, events and the repository are scanned after a job
- **THEN** the token value is not found anywhere

### Requirement: Isolated workspace
Each change SHALL run in its own git worktree on its own branch, the container MUST receive only that worktree (no container-engine socket, no environment files, no other project), and MUST drop all extra privileges and run as a non-root user.

#### Scenario: Reaching another project
- **WHEN** an agent inside a job tries to read another project's directory
- **THEN** the path does not exist in the container

### Requirement: Bounded execution
The dispatcher SHALL cap concurrent jobs (default 2), SHALL apply a maximum number of turns and a wall-clock timeout per job, and SHALL park a change after repeated review failures.

#### Scenario: Job exceeds limits
- **WHEN** a job reaches its turn or time limit
- **THEN** it is stopped, its state is saved to the worktree's progress file, and the change is marked "needs attention"

### Requirement: Two execution modes
The system SHALL run ordinary jobs non-interactively with subagents, and SHALL run team-mode jobs as an interactive session with agent teams enabled only when explicitly requested, because teammates are not spawned in non-interactive mode.

#### Scenario: Team mode requested
- **WHEN** the user requests team mode for a job
- **THEN** the job runs interactively inside the runner with at most five teammates

### Requirement: Command-line control
The user SHALL control the swarm through a `swarm` command (propose, approve, status, cancel, pause), and the panel MUST NOT offer write actions.

#### Scenario: Cancel
- **WHEN** the user runs `swarm cancel <job>`
- **THEN** the job stops and its worktree is kept for inspection
