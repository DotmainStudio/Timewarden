## What and why
<!-- One or two sentences. Link the OpenSpec change if there is one. -->

## Checklist
- [ ] Branch is `feat/`, `fix/`, `docs/` or `chore/` and was updated with the latest `main`
- [ ] `python3 -m pytest tests -q` passes (and `cd panel && pytest -q` if the panel changed)
- [ ] Behaviour change: OpenSpec change added and `openspec validate <id> --strict` passes
- [ ] No names of people/companies/machines, secrets, absolute paths or `.env` files
- [ ] I am not merging my own PR (unless trivial and the other maintainer is unavailable)
