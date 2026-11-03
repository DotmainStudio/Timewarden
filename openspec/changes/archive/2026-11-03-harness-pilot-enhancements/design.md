# Design

1. **Detection by directory.** `detect_runners` walks the root and depth-1 directories (skipping hidden, `node_modules`, virtualenvs, `dist`, `build`, `.worktrees`). Each runner records its directory; the health script wraps non-root runners in `bash -c "cd <dir> && <cmd>"`. Root runners keep their current command lines so existing installs are unchanged.
2. **Python tool choice.** `poetry run pytest -q` when `poetry.lock` exists, else `python3 -m pytest -q`. TypeScript: `npx tsc --noEmit` when `tsconfig.json` exists and `typescript` is a dependency and there is no usable `test` script.
3. **Explore proof.** `git status --porcelain` before and after; a difference fails the run. Explorer runs read-only in docker mode (mount `:ro`) and under the guard in local mode.
4. **Review flag** `--no-git` skips only the finalize call.
