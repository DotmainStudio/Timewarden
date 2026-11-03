# Tasks

## 1. Policy and role

- [x] 1.1 Add role `gitops` and the `gitops` settings (`auto_merge`) to `swarm/policy.yaml` and the policy validator (verification: `python3 -m pytest tests/swarm -q -k policy`).
- [x] 1.2 Add `templates/harness/roles/gitops.md` and include the role in the installer (verification: `python3 -m pytest tests/swarm/test_installer.py -q`).

## 2. Guard rules

- [x] 2.1 Role-specific git rules in the hook: allow non-main push and `gh pr` for `gitops`, block force push, push to main and hard reset for all (verification: `python3 -m pytest tests/swarm/test_pure.py -q -k guard`).

## 3. Git operations

- [x] 3.1 `swarmlib/gitops.py`: preflight, postflight, finalize, merge policy, graceful degradation (verification: `python3 -m pytest tests/swarm/test_gitops.py -q`).
- [x] 3.2 Conflict path: launch the `gitops` model job and re-run health (verification: conflict test in `tests/swarm/test_gitops.py`).
- [x] 3.3 Wire phases into `jobs.implement` and the CLI (`swarm git <phase>`) (verification: `python3 -m pytest tests/swarm/test_integration.py -q -k gitops`).
- [x] 3.4 Real smoke: read-only `gh` commands against the real repository and one local end-to-end with a bare remote (verification: `python3 -m pytest tests/swarm/test_gitops.py -q -k smoke`).

## 4. Docs

- [x] 4.1 Update `docs/SWARM_REPLICATION.md`, `swarm/README.md` and the deck (verification: replication guide contains the section "Git agent").
