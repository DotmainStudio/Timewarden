"""Swarm state in Postgres: runs, events, approvals, verdicts, changes/tasks projection."""
from __future__ import annotations

import json
from pathlib import Path

from . import changes as ch
from .pg import Pg
from .redact import sanitize


class Store:
    def __init__(self, db: Pg | None = None):
        self.db = db or Pg()

    # -- projects / changes -------------------------------------------------
    def upsert_project(self, project_id: str, repo: Path) -> None:
        self.db.execute("insert into swarm.projects(project_id, repo_path) values (:'p', :'r') "
                        "on conflict (project_id) do update set repo_path=:'r', updated_at=now()", p=project_id, r=str(repo))

    def sync_change(self, project_id: str, c: ch.Change, status: str, current: str, approved: str | None) -> None:
        self.db.execute(
            "insert into swarm.changes(project_id,change_id,status,current_hash,approved_hash,tasks_total,tasks_done,scenarios) "
            "values (:'p',:'c',:'s',:'h',nullif(:'a',''),:'tt'::int,:'td'::int,:'sc'::int) "
            "on conflict (project_id,change_id) do update set status=:'s', current_hash=:'h', approved_hash=nullif(:'a',''), "
            "tasks_total=:'tt'::int, tasks_done=:'td'::int, scenarios=:'sc'::int, updated_at=now()",
            p=project_id, c=c.change_id, s=status, h=current, a=approved or "", tt=len(c.tasks), td=c.done, sc=len(c.scenarios))
        for t in c.tasks:
            self.db.execute(
                "insert into swarm.tasks(project_id,change_id,task_id,group_title,title,verification,done) "
                "values (:'p',:'c',:'t',:'g',:'ti',:'v',:'d'::boolean) "
                "on conflict (project_id,change_id,task_id) do update set group_title=:'g', title=:'ti', verification=:'v', done=:'d'::boolean, updated_at=now()",
                p=project_id, c=c.change_id, t=t.task_id, g=t.group, ti=t.title, v=t.verification, d="true" if t.done else "false")
        ids = ",".join(f"'{t.task_id}'" for t in c.tasks) or "''"
        self.db.execute(f"delete from swarm.tasks where project_id=:'p' and change_id=:'c' and task_id not in ({ids})", p=project_id, c=c.change_id)

    # -- approvals -----------------------------------------------------------
    def record_approval(self, project_id: str, change_id: str, h: str, note: str = "") -> None:
        self.db.execute("update swarm.approvals set voided_at=now() where project_id=:'p' and change_id=:'c' and voided_at is null", p=project_id, c=change_id)
        self.db.execute("insert into swarm.approvals(project_id,change_id,artifact_hash,note) values (:'p',:'c',:'h',:'n')", p=project_id, c=change_id, h=h, n=note)

    def active_approval(self, project_id: str, change_id: str) -> dict | None:
        return self.db.one("select * from swarm.approvals where project_id=:'p' and change_id=:'c' and voided_at is null order by id desc limit 1", p=project_id, c=change_id)

    def void_approval(self, approval_id: int) -> None:
        self.db.execute("update swarm.approvals set voided_at=now() where id=:'i'::bigint", i=approval_id)

    # -- runs ------------------------------------------------------------------
    def create_run(self, project_id: str, kind: str, role: str, change_id: str | None = None, task_id: str | None = None,
                   model: str = "", effort: str = "", mode: str = "headless", branch: str = "", worktree: str = "", policy_hash: str = "") -> int:
        r = self.db.returning(
            "insert into swarm.runs(project_id,change_id,task_id,kind,role,model,effort,mode,branch,worktree,policy_hash) "
            "values (:'p',nullif(:'c',''),nullif(:'t',''),:'k',:'r',:'m',:'e',:'mo',:'b',:'w',:'ph') returning id",
            p=project_id, c=change_id or "", t=task_id or "", k=kind, r=role, m=model, e=effort, mo=mode, b=branch, w=worktree, ph=policy_hash)
        return int(r["id"])

    def update_run(self, run_id: int, **f) -> None:
        allowed = {"state", "auth_kind", "session_id", "turns", "input_tokens", "output_tokens", "cache_read_tokens",
                   "cache_creation_tokens", "cost_usd", "context_end", "retries", "quota_utilization", "progress", "summary", "model"}
        sets, vars = [], {"i": run_id}
        for k, v in f.items():
            if k not in allowed:
                raise ValueError(f"column {k} not updatable")
            sets.append(f"{k}=nullif(:'{k}','')::{ 'numeric' if k in ('cost_usd','quota_utilization') else 'bigint' if k in ('turns','input_tokens','output_tokens','cache_read_tokens','cache_creation_tokens','context_end','retries') else 'text'}")
            vars[k] = v
        if f.get("state") == "running":
            sets.append("started_at=coalesce(started_at, now())")
        if f.get("state") in ("succeeded", "failed", "cancelled", "timeout", "parked"):
            sets.append("ended_at=now()")
        self.db.execute(f"update swarm.runs set {', '.join(sets)} where id=:'i'::bigint", **vars)

    def run(self, run_id: int) -> dict | None:
        return self.db.one("select * from swarm.runs where id=:'i'::bigint", i=run_id)

    def active_runs(self, project_id: str | None = None) -> list[dict]:
        return self.db.rows("select * from swarm.runs where state in ('queued','running') and (:'p'='' or project_id=:'p') order by id", p=project_id or "")

    def running_count(self) -> int:
        return int(self.db.one("select count(*) as n from swarm.runs where state='running'")["n"])

    def assign_task(self, project_id: str, change_id: str, task_id: str, run_id: int | None, role: str | None) -> None:
        self.db.execute("update swarm.tasks set assigned_run=nullif(:'r','')::bigint, assigned_role=nullif(:'ro',''), updated_at=now() "
                        "where project_id=:'p' and change_id=:'c' and task_id=:'t'", r=run_id or "", ro=role or "", p=project_id, c=change_id, t=task_id)

    # -- events, verdicts, health, recalls -----------------------------------
    def event(self, project_id: str, type_: str, run_id: int | None = None, role: str | None = None, model: str | None = None,
              tool: str | None = None, duration_ms: int | None = None, ok: bool | None = None, detail: dict | None = None) -> None:
        self.db.execute(
            "insert into swarm.events(run_id,project_id,type,role,model,tool,duration_ms,ok,detail) "
            "values (nullif(:'r','')::bigint,:'p',:'ty',nullif(:'ro',''),nullif(:'m',''),nullif(:'to',''),nullif(:'d','')::bigint,nullif(:'ok','')::boolean,:'de'::jsonb)",
            r=run_id or "", p=project_id, ty=type_, ro=role or "", m=model or "", to=tool or "",
            d="" if duration_ms is None else int(duration_ms), ok="" if ok is None else ("true" if ok else "false"),
            de=json.dumps(sanitize(detail or {})))

    def verdict(self, run_id: int | None, project_id: str, change_id: str, passed: bool, scenarios: list, findings: list) -> None:
        self.db.execute("insert into swarm.verdicts(run_id,project_id,change_id,passed,scenarios,findings) values (nullif(:'r','')::bigint,:'p',:'c',:'ok'::boolean,:'s'::jsonb,:'f'::jsonb)",
                        r=run_id or "", p=project_id, c=change_id, ok="true" if passed else "false", s=json.dumps(scenarios), f=json.dumps(findings))

    def failed_verdicts(self, project_id: str, change_id: str) -> int:
        return int(self.db.one("select count(*) as n from swarm.verdicts where project_id=:'p' and change_id=:'c' and not passed", p=project_id, c=change_id)["n"])

    def health(self, run_id: int | None, project_id: str, change_id: str | None, ok: bool, tail: str) -> None:
        from .redact import scrub
        self.db.execute("insert into swarm.health(run_id,project_id,change_id,ok,output_tail) values (nullif(:'r','')::bigint,:'p',nullif(:'c',''),:'ok'::boolean,:'t')",
                        r=run_id or "", p=project_id, c=change_id or "", ok="true" if ok else "false", t=scrub(tail[-1500:]))

    def recall(self, run_id: int | None, project_id: str, dataset: str, query_hash: str, results: int, used: bool | None, rejected: bool = False) -> None:
        self.db.execute("insert into swarm.recalls(run_id,project_id,dataset,query_hash,results,used,rejected) values "
                        "(nullif(:'r','')::bigint,:'p',:'d',:'q',:'n'::int,nullif(:'u','')::boolean,:'rj'::boolean)",
                        r=run_id or "", p=project_id, d=dataset, q=query_hash, n=results,
                        u="" if used is None else ("true" if used else "false"), rj="true" if rejected else "false")

    def latest_verdict(self, project_id: str, change_id: str) -> dict | None:
        return self.db.one("select * from swarm.verdicts where project_id=:'p' and change_id=:'c' order by id desc limit 1", p=project_id, c=change_id)

    def set_progress(self, run_id: int, text: str) -> None:
        from .redact import scrub
        self.db.execute("update swarm.runs set progress=:'t' where id=:'i'::bigint", t=scrub(text[-4000:]), i=run_id)
