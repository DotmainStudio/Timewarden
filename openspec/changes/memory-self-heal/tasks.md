# Tasks

## 1. Healer

- [x] 1.1 `scripts/memory_heal.py`: config with hard caps, state, free repairs (verification: `python3 -m pytest tests/test_memory_heal.py -q -k "infra or swarm or config"`).
- [x] 1.2 Budgeted sync repair with quota, branch and attempt gating (verification: `python3 -m pytest tests/test_memory_heal.py -q -k "sync or budget or quota"`).
- [x] 1.3 Report-only findings, notifications and optional bounded diagnosis (verification: `python3 -m pytest tests/test_memory_heal.py -q -k "orphan or notify or diagnose"`).

## 2. Scheduling and docs

- [x] 2.1 LaunchAgent installer and documentation (verification: `bash scripts/memory_heal_launchagent.sh status` and the section in `docs/operations.md`).
