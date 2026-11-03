# Tasks

## 1. Installer

- [x] 1.1 Monorepo-aware runner detection and health script generation (verification: `python3 -m pytest tests/swarm/test_installer.py -q -k monorepo`).

## 2. Swarm commands

- [x] 2.1 `swarm explore` with working-tree proof (verification: `python3 -m pytest tests/swarm/test_integration.py -q -k explore`).
- [x] 2.2 `swarm review --no-git` (verification: `python3 -m pytest tests/swarm/test_integration.py -q -k no_git`).
