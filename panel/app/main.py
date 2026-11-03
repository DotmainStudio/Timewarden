"""Memory inspector (Cognee): internal READ-ONLY UI. Listens on loopback."""
from __future__ import annotations

import collections
import os
from pathlib import Path

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import cognee_client as cognee
from . import config, dockerapi, kb, observer, otel, pg, resources, storage, swarm, usage, vectors

app = FastAPI(title="Memory Inspector", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def seguridad(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host not in config.ALLOWED_HOSTS:  # anti DNS-rebinding
        return JSONResponse({"error": "host not allowed"}, status_code=421)
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                               "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(pg.QueryRejected)
async def _rejected(_, exc):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(psycopg.Error)
async def _pgerr(_, exc):
    msg = (str(exc).splitlines() or ["database error"])[0][:300]
    return JSONResponse({"error": msg}, status_code=400 if isinstance(exc, psycopg.errors.SyntaxError) else 502)


@app.exception_handler(cognee.CogneeUnavailable)
async def _cogerr(_, exc):
    return JSONResponse({"error": f"Cognee is not responding: {exc}"}, status_code=502)


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # one failed component must not take down the summary
        return {"ok": False, "error": str(exc)[:160]}


def _mcp_health() -> dict:
    try:
        r = httpx.get(f"{config.COGNEE_MCP_URL}/health", timeout=4, headers={"Host": "localhost"})  # the MCP rejects other Hosts
        return {"ok": r.status_code == 200}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)[:120]}


@app.get("/api/overview")
def overview():
    reg = observer.registry()
    states = collections.Counter(r["status"] for r in reg)
    fl = otel.files()
    obs = observer.summary()
    ds = safe(lambda: cognee.get("/api/v1/datasets"))
    sess = safe(lambda: cognee.get("/api/v1/sessions"))
    return {
        "cognee": cognee.health(), "mcp": _mcp_health(), "postgres": safe(pg.overview), "observer": observer.health(),
        "collector": {"ok": bool(fl), "files": len(fl), "bytes": sum(f["bytes"] for f in fl),
                      "latest_file": max((f["modified"] for f in fl), default=None)},
        "registry": {"total": len(reg), "states": dict(states)},
        "datasets": len(ds) if isinstance(ds, list) else None,
        "sessions": len((sess or {}).get("sessions", [])) if isinstance(sess, dict) and "sessions" in sess else None,
        "observer_usage": {"by_day": obs.get("by_day", [])[-14:], "total": obs.get("total", {})},
        "otel_usage": {"by_day": otel.summary(days=14)["by_day"], "total": otel.summary(days=14)["total"]},
    }


# -- Swarm (read-only, role swarm_reader) --------------------------------------
@app.get("/api/swarm/board")
def swarm_board():
    return swarm.board()


@app.get("/api/swarm/agents")
def swarm_agents():
    return swarm.agents()


@app.get("/api/swarm/pending")
def swarm_pending():
    return swarm.pending()


@app.get("/api/swarm/runs/{run_id}")
def swarm_run(run_id: int):
    return swarm.run_detail(run_id)


@app.get("/api/swarm/verdicts")
def swarm_verdicts():
    return {"verdicts": swarm.verdicts(), "health": swarm.health_history()}


@app.get("/api/swarm/efficiency")
def swarm_efficiency():
    return swarm.efficiency()


@app.get("/api/swarm/compare")
def swarm_compare(a: int, b: int):
    return swarm.compare(a, b)


@app.get("/api/datasets")
def datasets():
    items = cognee.get("/api/v1/datasets") or []
    status = safe(lambda: cognee.get("/api/v1/datasets/status")) or {}
    gsum = safe(lambda: cognee.get("/api/v1/datasets/graph-summary"))
    gmap = {g["datasetId"]: g for g in gsum} if isinstance(gsum, list) else {}
    out = []
    for d in items:
        did = d["id"]
        schema = pg.dataset_schema_name(did)
        try:
            tbls = pg.tables(schema)
            rows = sum(t["rows"] or 0 for t in tbls)
        except Exception:
            tbls, rows = [], None
        cnt = safe(lambda: cognee.get(f"/api/v1/datasets/{did}/data/count")) or {}
        out.append({"id": did, "name": d["name"], "created": d.get("createdAt"), "status": status.get(did, "SIN_PROCESAR"),
                    "documents": cnt.get("count"), "nodes": gmap.get(did, {}).get("numNodes"),
                    "edges": gmap.get(did, {}).get("numEdges"), "graph_computed": gmap.get(did, {}).get("computedAt"),
                    "schema": schema, "pg_tables": len(tbls), "pg_rows": rows})
    return out


@app.get("/api/datasets/{dataset_id}/documents")
def dataset_documents(dataset_id: str):
    docs = cognee.get(f"/api/v1/datasets/{dataset_id}/data") or []
    reg = {r["data_id"]: r for r in observer.registry() if r.get("data_id")}
    return [{"id": d["id"], "name": d.get("name"), "type": d.get("extension"), "bytes": d.get("dataSize"),
             "created": d.get("createdAt"), "path": reg.get(d["id"], {}).get("path"),
             "doc_id": reg.get(d["id"], {}).get("doc_id"), "status": reg.get(d["id"], {}).get("status")} for d in docs]


def _node_label(n: dict) -> str:
    p = n.get("properties") or {}
    t = n.get("type")
    if t in ("Entity", "EntityType") and p.get("name"):
        return str(p["name"])[:60]
    if t in ("DocumentChunk", "TextSummary") and p.get("text"):
        return " ".join(str(p["text"]).split())[:50]
    if t == "TextDocument" and p.get("name"):
        return str(p["name"])[:50]
    return str(p.get("name") or n.get("label") or n.get("id"))[:50]


def _clip(v, n=500):
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + f"… (+{len(v) - n})"
    if isinstance(v, dict):
        return {k: _clip(x, n) for k, x in v.items()}
    if isinstance(v, list):
        return [_clip(x, n) for x in v[:30]]
    return v


@app.get("/api/datasets/{dataset_id}/graph")
def dataset_graph(dataset_id: str, types: str = "", max_nodes: int = Query(400, ge=20, le=3000)):
    g = cognee.get(f"/api/v1/datasets/{dataset_id}/graph", timeout=180) or {"nodes": [], "edges": []}
    nodes, edges = g.get("nodes", []), g.get("edges", [])
    type_counts = collections.Counter(n.get("type") or "?" for n in nodes)
    rel_counts = collections.Counter(e.get("label") or "?" for e in edges)
    wanted = {t for t in types.split(",") if t} or set(type_counts)
    keep = [n for n in nodes if (n.get("type") or "?") in wanted]
    ids = {n["id"] for n in keep}
    es = [e for e in edges if e["source"] in ids and e["target"] in ids]
    deg = collections.Counter()
    for e in es:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    truncated = len(keep) > max_nodes
    if truncated:
        keep = sorted(keep, key=lambda n: -deg[n["id"]])[:max_nodes]
        ids = {n["id"] for n in keep}
        es = [e for e in es if e["source"] in ids and e["target"] in ids]
    return {"stats": {"nodes": len(nodes), "edges": len(edges), "types": dict(type_counts), "relations": dict(rel_counts),
                      "shown_nodes": len(keep), "shown_edges": len(es), "truncated": truncated},
            "nodes": [{"id": n["id"], "label": _node_label(n), "type": n.get("type") or "?", "degree": deg[n["id"]],
                       "props": _clip({k: v for k, v in (n.get("properties") or {}).items() if k not in ("metadata", "topological_rank")})}
                      for n in keep],
            "edges": [{"source": e["source"], "target": e["target"], "label": e.get("label") or ""} for e in es]}


class SearchIn(BaseModel):
    dataset: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


@app.post("/api/search")
def search(body: SearchIn):
    """CHUNKS retrieval: does not use an LLM and does not modify data."""
    res = cognee.post("/api/v1/search", {"searchType": "CHUNKS", "datasets": [body.dataset], "query": body.query,
                                         "topK": body.top_k}) or []
    reg = {r["data_id"]: r for r in observer.registry() if r.get("data_id")}
    items = []
    for grp in res:
        for ch in grp.get("search_result", []):
            r = reg.get(ch.get("document_id"), {})
            items.append({"score": ch.get("score"), "text": ch.get("text"), "chunk_index": ch.get("chunk_index"),
                          "document_id": ch.get("document_id"), "path": r.get("path"), "doc_id": r.get("doc_id"),
                          "status": r.get("status")})
    return {"results": items}


@app.get("/api/pg/schemas")
def pg_schemas():
    names = {pg.dataset_schema_name(d["id"]): d["name"] for d in (safe(lambda: cognee.get("/api/v1/datasets")) or [])
             if isinstance(d, dict)}
    return [{**s, "dataset": names.get(s["schema"])} for s in pg.schemas()]


@app.get("/api/pg/tables")
def pg_tables(schema: str):
    return pg.tables(schema)


@app.get("/api/pg/table")
def pg_table(schema: str, table: str, limit: int = 50, offset: int = 0):
    return pg.table_detail(schema, table, limit, offset)


class SqlIn(BaseModel):
    sql: str = Field(max_length=5000)


@app.post("/api/pg/query")
def pg_query(body: SqlIn):
    return pg.run_query(body.sql)


@app.get("/api/otel")
def otel_summary(days: int | None = Query(None, ge=1, le=365), project: str | None = None):
    return otel.summary(days, project)


@app.get("/api/observer")
def observer_summary():
    return {**observer.summary(), "health": observer.health()}


@app.get("/api/usage")
def api_usage(days: int = Query(14, ge=1, le=90), project: str | None = None):
    return usage.summary(days, project)


@app.get("/api/resources")
def api_resources():
    return {"host": resources.host(), "docker": resources.docker()}


@app.post("/api/resources/host")
def api_resources_host():
    """An on-demand measurement of the Mac (no resident process on the Mac)."""
    return resources.measure_host()


@app.get("/api/registry")
def registry():
    return observer.registry()



@app.get("/api/kb")
def kb_overview():
    """Size of the knowledge base per project/dataset and signals to decide whether to compact or delete."""
    return kb.overview()


@app.get("/api/kb/{dataset_id}")
def kb_detail(dataset_id: str):
    ds = next((d for d in (cognee.get("/api/v1/datasets") or []) if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    gsum = {g["datasetId"]: g for g in (cognee.get("/api/v1/datasets/graph-summary") or [])}
    return kb.dataset_report(ds, storage.graph_files(), gsum, kb._avg_tokens_per_call(), observer.registry())


@app.get("/api/vectors")
def all_vectors():
    out = []
    for d in cognee.get("/api/v1/datasets") or []:
        schema = pg.dataset_schema_name(d["id"])
        try:
            cols = vectors.collections(schema)
        except Exception:
            cols = []
        out.append({"dataset_id": d["id"], "dataset": d["name"], "schema": schema, "collections": cols,
                    "rows": sum(c["rows"] or 0 for c in cols), "bytes": sum(c["bytes_total"] for c in cols)})
    return out


@app.get("/api/containers")
def containers():
    return {"available": dockerapi.available(), "containers": safe(dockerapi.containers) if dockerapi.available() else []}


@app.get("/api/api-calls")
def api_calls(hours: int = Query(24, ge=1, le=720)):
    return safe(dockerapi.api_calls, hours)


@app.get("/api/tokens")
def tokens(days: int = Query(14, ge=1, le=365)):
    return {"claude_code": otel.summary(days), "observer": observer.summary(days),
            "cognee_sessions": {"stats": safe(lambda: cognee.get("/api/v1/sessions/stats")),
                                "by_model": safe(lambda: cognee.get("/api/v1/sessions/cost-by-model")),
                                "by_agent": safe(lambda: cognee.get("/api/v1/sessions/cost-by-user-agent"))}}


STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
