"""After the USER merges: archive the change (updates main specs) and run ONE memory sync from the main checkout."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import jobs

ROOT = Path(__file__).resolve().parent.parent.parent


def is_merged(repo: Path, branch: str) -> bool:
    base = jobs.main_branch(repo)
    rc, _ = jobs.git(repo, "merge-base", "--is-ancestor", branch, base)
    return rc == 0


def run_post_merge(repo: Path, change_id: str, run_sync: bool = True, sync_cmd: list[str] | None = None) -> dict:
    """Runs only after the USER merged. Archive happens on its own branch/worktree (agents never commit to main);
    the single memory sync runs from the CLEAN main checkout, so nothing from an unmerged branch is indexed."""
    repo = repo.resolve()
    base = jobs.main_branch(repo)
    branch = f"change/{change_id}"
    cur = jobs.git(repo, "branch", "--show-current")[1].strip()
    if cur != base:
        return {"ok": False, "reason": f"checkout is on '{cur}', not '{base}': post-merge steps run only from the main branch"}
    if jobs.git(repo, "status", "--porcelain", "--untracked-files=no")[1].strip():
        return {"ok": False, "reason": "main checkout has uncommitted changes to tracked files; sync would index unmerged state"}
    if jobs.git(repo, "rev-parse", "--verify", branch)[0] == 0 and not is_merged(repo, branch):
        return {"ok": False, "reason": f"{branch} is not merged into {base}"}
    steps = []
    ab = f"chore/archive-{change_id}"
    wt = repo.parent / ".swarm-worktrees" / f"{repo.name}-{ab.replace('/', '-')}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    rc, out = jobs.git(repo, "worktree", "add", "-b", ab, str(wt), base)
    if rc != 0:
        return {"ok": False, "reason": f"cannot create archive worktree: {out.strip()[-160:]}"}
    rc, out = jobs.sh(["openspec", "archive", change_id, "--yes"], wt)
    steps.append({"step": "archive", "ok": rc == 0, "tail": out[-200:]})
    if rc != 0:
        return {"ok": False, "reason": "openspec archive failed", "steps": steps}
    jobs.commit(wt, f"chore(openspec): archive {change_id}")
    steps[-1]["branch"] = ab
    if run_sync:
        cmd = sync_cmd or [str(ROOT / "scripts" / "memctl.sh"), "sync", str(repo), "--apply"]
        rc, out = jobs.sh(cmd, repo, timeout=1800)
        steps.append({"step": "memory_sync", "ok": rc == 0, "tail": out[-200:], "from": f"{base} (clean, merged)"})
    return {"ok": all(s["ok"] for s in steps), "steps": steps,
            "note": f"open a PR for {ab} (updated main specs); the next sync after you merge it indexes them"}
