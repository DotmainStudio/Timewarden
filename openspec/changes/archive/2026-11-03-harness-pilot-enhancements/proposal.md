# Harness pilot enhancements

## Why

The first production pilot is a monorepo (`backend/` and `frontend/`, each with its own toolchain), so the installer's root-only detection of test runners would generate a health script that checks nothing real. The pilot's first phase also needs read-only jobs that provably leave the repository untouched, and a way to review a change without triggering the git agent's merge.

## What Changes

- Installer detects test runners and type checks in the repository root and in its immediate subdirectories (monorepos), preferring `poetry run` when a `poetry.lock` exists, and generates a health script that runs each one inside its directory.
- New `swarm explore "<question>"`: runs the read-only explorer role on the repository and verifies the working tree is unchanged afterwards, recording the check as an event.
- `swarm review <change> --no-git`: reviews and records the verdict without launching the git agent's finalize phase.

## Capabilities

### Modified Capabilities
<!-- project-harness and swarm-execution are still defined inside the active swarm-harness-platform change; these deltas are ADDED requirements -->

## Impact

- `scripts/install_harness.py`, `swarm/swarmlib/jobs.py`, `swarm/swarmlib/cli.py`, tests, docs.
