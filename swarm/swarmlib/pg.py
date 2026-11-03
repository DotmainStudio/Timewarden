"""Postgres access through `psql` inside the stack's Postgres container (no Python driver needed on the host).

Values are passed as psql variables and interpolated by psql itself (`:'name'` = safely quoted literal), never by
string formatting. One JSON object per output line (`row_to_json`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"
READER, WRITER = "swarm_reader", "swarm_writer"


class PgError(RuntimeError):
    pass


class Pg:
    def __init__(self, db: str | None = None, user: str | None = None, container: str | None = None):
        self.container = container or os.environ.get("SWARM_PG_CONTAINER", "agents_memory_system-agents_postgres-1")
        self.db = db or os.environ.get("SWARM_PG_DB", "agents_memory")
        self.user = user or os.environ.get("SWARM_PG_USER", WRITER)

    def _run(self, sql: str, vars: dict, tuples: bool = True) -> str:
        argv = ["docker", "exec", "-i", self.container, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", self.user, "-d", self.db]
        if tuples:
            argv += ["-t", "-A"]
        for k, v in vars.items():
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", k):
                raise PgError(f"bad variable name {k!r}")
            argv += ["-v", f"{k}={'' if v is None else v}"]
        r = subprocess.run(argv, input=sql, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise PgError((r.stderr.strip().splitlines() or ["psql failed"])[-1][:300])
        return r.stdout

    def execute(self, sql: str, **vars) -> None:
        self._run(sql, vars)

    def rows(self, select_sql: str, **vars) -> list[dict]:
        """`select_sql` is a plain SELECT; each row comes back as a dict."""
        out = self._run(f"select row_to_json(t) from ({select_sql.rstrip().rstrip(';')}) t;", vars)
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def returning(self, dml_sql: str, **vars) -> dict | None:
        """`dml_sql` is an INSERT/UPDATE ... RETURNING ...; returns the first row."""
        out = self._run(f"with x as ({dml_sql.rstrip().rstrip(';')}) select row_to_json(x) from x limit 1;", vars)
        lines = [l for l in out.splitlines() if l.strip()]
        return json.loads(lines[0]) if lines else None

    def one(self, select_sql: str, **vars) -> dict | None:
        r = self.rows(select_sql, **vars)
        return r[0] if r else None


def admin(db: str | None = None) -> Pg:
    """Superuser connection (bootstrap and tests only)."""
    return Pg(db=db or "agents_memory", user=os.environ.get("SWARM_PG_ADMIN", "agents"))


def apply_schema(db: Pg, with_roles: bool = True, reader_password: str | None = None) -> None:
    sql = SCHEMA.read_text()
    db._run(sql, {}, tuples=False)
    if with_roles:
        grant_roles(db, reader_password)


def grant_roles(db: Pg, reader_password: str | None = None) -> None:
    """swarm_writer: DML on swarm.*; swarm_reader: SELECT only on swarm.*. Roles are cluster-wide; grants per database."""
    db._run(f"""
    do $$ begin
      if not exists (select 1 from pg_roles where rolname='{WRITER}') then create role {WRITER} login; end if;
      if not exists (select 1 from pg_roles where rolname='{READER}') then create role {READER} login; end if;
    end $$;
    grant connect on database {db.db} to {WRITER}, {READER};
    grant usage on schema swarm to {WRITER}, {READER};
    revoke all on all tables in schema swarm from {WRITER}, {READER};
    grant select, insert, update, delete on all tables in schema swarm to {WRITER};
    grant usage, select on all sequences in schema swarm to {WRITER};
    grant select on all tables in schema swarm to {READER};
    alter role {READER} set default_transaction_read_only = on;
    alter role {READER} set statement_timeout = '15s';
    """, {}, tuples=False)
    if reader_password:   # the panel connects over TCP and needs a password; the value is never printed
        db._run("alter role swarm_reader password :'pw';", {"pw": reader_password}, tuples=False)
