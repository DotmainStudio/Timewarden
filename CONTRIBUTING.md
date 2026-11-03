# Contributing to Timewarden

Several people work on this repository, so **nobody commits directly to `main`**. Every change travels in its own branch and a pull request (PR).

## The rule
1. **Start from the latest `main`:** `git fetch origin && git switch -c <type>/<short-name> origin/main`.
2. **One branch per change**, named by type: `feat/…` (new behaviour), `fix/…` (bug), `docs/…` (documentation only), `chore/…` (maintenance, releases). Keep it small and focused.
3. **Never push to `main`, never force-push a shared branch.** Push your feature branch and open a PR against `main`.
4. **Update before you open the PR:** merge the current `main` into your branch (`git merge origin/main`) and resolve conflicts on your side, so the PR merges cleanly and does not disturb what others already merged.
5. **A PR needs:** a clear description, the tests passing locally (`python3 -m pytest tests -q`, and `cd panel && pytest -q` if you touched the panel), and for a behaviour change an OpenSpec change (`openspec/changes/<id>/`, validated with `openspec validate <id> --strict`).
6. **Review and merge:** a second collaborator reviews and merges. Do not merge your own PR unless the other maintainer is unavailable and the change is trivial (typo, docs). Delete the branch after merging.
7. **Releases** (version bump in `VERSION`, tag, zip) go through their own `chore/release-x.y.z` PR and are created by a maintainer after it is merged.

## Keep the kit neutral
Do not add names of people, companies, clients or machines, credentials, absolute paths or `.env` files. The kit is meant to be shared; anything specific to one installation belongs in that installation's own repository.

## Maintainer setting (recommended)
In GitHub: Settings → Branches → add a rule for `main`: **Require a pull request before merging** (at least 1 approval) and **Do not allow bypassing**. This makes the rule above enforced and not only agreed.
