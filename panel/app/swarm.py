"""Swarm page data: change board, active agents and their tasks, pending work, verdicts, health, efficiency.
READ-ONLY: connects as `swarm_reader` (select-only on schema swarm); there are no write endpoints."""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from . import config, pg

BOARD = ["awaiting_approval", "approved", "in_progress", "review", "done", "parked", "needs_attention", "draft"]


def connect() -> psycopg.Connection:
    return psycopg.connect(**config.SWARM_PG, autocommit=True, connect_timeout=5, row_factory=dict_row,
                           options="-c default_transaction_read_only=on -c statement_timeout=15000")


def q(sql: str, *args) -> list[dict]:
    with connect() as con, con.cursor() as cur:
        cur.execute(sql, args or None)
        return [{k: pg.fmt(v) if not isinstance(v, (int, float, bool, type(None))) else v for k, v in r.items()} for r in cur.fetchall()]


def quota_risk(utilization: float | None) -> str:
    """Quota-risk indicator from the subscription's own utilisation figure (0-1) reported by Claude Code."""
    if utilization is None:
        return "unknown"
    return "high" if utilization >= 0.85 else "medium" if utilization >= 0.6 else "low"


def board() -> dict:
    rows = q("select project_id, change_id, status, title, tasks_total, tasks_done, scenarios, updated_at from swarm.changes order by project_id, change_id")
    cols = {s: [] for s in BOARD}
    for r in rows:
        cols.setdefault(r["status"], []).append(r)
    return {"columns": cols, "total": len(rows)}


def agents() -> dict:
    active = q("""select r.id, r.project_id, r.change_id, r.task_id, r.role, r.model, r.effort, r.state, r.kind, r.started_at, r.progress,
                         t.title as task_title, r.turns, r.input_tokens, r.output_tokens
                  from swarm.runs r left join swarm.tasks t on t.project_id=r.project_id and t.change_id=r.change_id and t.task_id=r.task_id
                  where r.state in ('queued','running') order by r.id""")
    recent = q("""select r.id, r.project_id, r.change_id, r.task_id, r.role, r.model, r.state, r.kind, r.started_at, r.ended_at, r.turns,
                         r.input_tokens, r.output_tokens, r.summary
                  from swarm.runs r where r.state not in ('queued','running') order by r.id desc limit 30""")
    quota = q("select max(quota_utilization) as u from swarm.runs where created_at > now() - interval '5 hours'")
    u = float(quota[0]["u"]) if quota and quota[0]["u"] is not None else None
    return {"active": active, "recent": recent, "quota_utilization": u, "quota_risk": quota_risk(u)}


def pending() -> list[dict]:
    return q("""select t.project_id, t.change_id, t.task_id, t.group_title, t.title, t.verification, c.status as change_status,
                       t.assigned_run, t.assigned_role
                from swarm.tasks t join swarm.changes c using (project_id, change_id)
                where not t.done and c.status <> 'done' order by t.project_id, t.change_id, t.task_id""")


def run_detail(run_id: int) -> dict:
    return {
        "run": (q("select * from swarm.runs where id=%s", run_id) or [None])[0],
        "events": q("select ts, type, role, model, tool, duration_ms, ok, detail from swarm.events where run_id=%s order by id desc limit 100", run_id),
        "health": q("select ts, ok, output_tail from swarm.health where run_id=%s order by id desc limit 10", run_id),
        "recalls": q("select dataset, results, used, rejected from swarm.recalls where run_id=%s order by id", run_id),
    }


def verdicts(limit: int = 30) -> list[dict]:
    return q("select id, project_id, change_id, passed, scenarios, findings, created_at from swarm.verdicts order by id desc limit %s", limit)


def health_history(limit: int = 40) -> list[dict]:
    return q("select ts, project_id, change_id, ok, run_id from swarm.health order by id desc limit %s", limit)


def efficiency() -> dict:
    by_role = q("""select role, count(*) as runs, coalesce(sum(input_tokens),0) as input_tokens, coalesce(sum(output_tokens),0) as output_tokens,
                          coalesce(sum(cache_read_tokens),0) as cache_read, coalesce(sum(cache_creation_tokens),0) as cache_creation,
                          round(avg(turns)::numeric,1) as avg_turns, round(avg(context_end)::numeric,0) as avg_context_end,
                          coalesce(sum(retries),0) as retries, count(*) filter (where state in ('failed','timeout','parked')) as bad
                   from swarm.runs where state not in ('queued','running') group by role order by role""")
    for r in by_role:
        tot = (r["input_tokens"] or 0) + (r["cache_read"] or 0) + (r["cache_creation"] or 0)
        r["cache_read_share"] = round((r["cache_read"] or 0) / tot, 3) if tot else 0
    models = q("select model, count(*) as runs from swarm.runs where model is not null and model <> '' group by model order by runs desc")
    recalls = q("""select r.run_id, count(*) as recalls, count(*) filter (where used) as used, count(*) filter (where rejected) as rejected
                   from swarm.recalls r group by r.run_id order by r.run_id desc limit 30""")
    for r in recalls:
        r["flag"] = "unused" if r["recalls"] - r["rejected"] > 0 and r["used"] == 0 else "ok"
    runs = q("""select id, project_id, change_id, role, model, effort, state, turns, input_tokens, output_tokens, cache_read_tokens, policy_hash, cost_usd
                from swarm.runs where state not in ('queued','running') order by id desc limit 40""")
    return {"by_role": by_role, "models": models, "recalls": recalls, "runs": runs}


def compare(a: int, b: int) -> dict:
    rows = q("select id, role, model, effort, state, turns, input_tokens, output_tokens, cache_read_tokens, cost_usd, policy_hash from swarm.runs where id in (%s,%s)", a, b)
    by = {r["id"]: r for r in rows}
    if a not in by or b not in by:
        raise pg.QueryRejected("run not found")
    return {"a": by[a], "b": by[b]}
