# project-harness Specification

## Purpose
Define the per-repository file contract that lets the swarm work on any project, an installer that adds it without damaging existing files, and monorepo-aware health checks.

## Requirements

### Requirement: Monorepo test detection
The installer SHALL detect test runners and type checks in the repository root and in each immediate subdirectory, SHALL run each detected check inside its own directory from the generated health script, and the health script MUST fail if any of them fails.

#### Scenario: Backend and frontend in subdirectories
- **WHEN** the repository has a Python project in `backend/` (with `poetry.lock`) and a TypeScript project in `frontend/`
- **THEN** the generated health script runs `poetry run pytest` inside `backend/` and a TypeScript check inside `frontend/`, and fails if either fails

#### Scenario: Ignored directories
- **WHEN** a subdirectory is `node_modules`, a virtual environment, a build output or a hidden directory
- **THEN** it is not scanned

### Requirement: Harness file contract
A harnessed repository SHALL contain an agent entry document, an architecture document, a generated backlog, a `progress/` directory (current state, history), a health script, and role definitions for leader, explorer, implementer and reviewer, and the Claude Code entry file SHALL import the agent entry document so it is actually loaded.

#### Scenario: Entry loaded
- **WHEN** a session starts in a harnessed repository
- **THEN** the harness protocol is part of the session context

### Requirement: Health script gates completion
The health script MUST run the project's real checks (all test runners of the detected profile, plus validation of the OpenSpec change), and a task MUST NOT be reported complete unless it exits successfully after the change.

#### Scenario: Mixed-stack project
- **WHEN** the repository has both a JavaScript and a Python test suite
- **THEN** the health script runs both and fails if either fails

### Requirement: Non-invasive installation
The installer SHALL be idempotent, MUST list every file it would add or change before writing (dry run first), MUST NOT overwrite or delete existing files, and MUST leave foreign agent files (for example an existing `AGENTS.md`, tool directories of other agents) untouched, placing the protocol in the Claude Code entry file instead.

#### Scenario: Existing agent entry file
- **WHEN** the repository already has an `AGENTS.md` not created by this system
- **THEN** it is not modified and the harness protocol is added through `CLAUDE.md`

#### Scenario: Re-run
- **WHEN** the installer runs twice
- **THEN** the second run reports no changes

### Requirement: Stack knowledge from profiles
Stack-specific rules SHALL come from the existing project profiles injected into the roles, and roles MUST stay generic.

#### Scenario: New stack
- **WHEN** a profile for a new stack is added
- **THEN** no role definition has to change
