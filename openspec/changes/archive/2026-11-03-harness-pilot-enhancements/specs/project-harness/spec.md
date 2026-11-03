# Spec Delta

## ADDED Requirements

### Requirement: Monorepo test detection
The installer SHALL detect test runners and type checks in the repository root and in each immediate subdirectory, SHALL run each detected check inside its own directory from the generated health script, and the health script MUST fail if any of them fails.

#### Scenario: Backend and frontend in subdirectories
- **WHEN** the repository has a Python project in `backend/` (with `poetry.lock`) and a TypeScript project in `frontend/`
- **THEN** the generated health script runs `poetry run pytest` inside `backend/` and a TypeScript check inside `frontend/`, and fails if either fails

#### Scenario: Ignored directories
- **WHEN** a subdirectory is `node_modules`, a virtual environment, a build output or a hidden directory
- **THEN** it is not scanned
