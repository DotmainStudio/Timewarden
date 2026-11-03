-- Swarm monitoring schema. Idempotent. Roles are created by swarm/bootstrap (see swarmlib/pg.py).
create schema if not exists swarm;

create table if not exists swarm.projects (
  project_id text primary key,
  repo_path  text,
  updated_at timestamptz not null default now()
);
create table if not exists swarm.changes (
  project_id text not null, change_id text not null,
  status text not null, current_hash text, approved_hash text,
  tasks_total int not null default 0, tasks_done int not null default 0, scenarios int not null default 0,
  title text, updated_at timestamptz not null default now(),
  primary key (project_id, change_id)
);
create table if not exists swarm.tasks (
  project_id text not null, change_id text not null, task_id text not null,
  group_title text, title text, verification text, done boolean not null default false,
  assigned_run bigint, assigned_role text, updated_at timestamptz not null default now(),
  primary key (project_id, change_id, task_id)
);
create table if not exists swarm.approvals (
  id bigserial primary key, project_id text not null, change_id text not null,
  artifact_hash text not null, approved_at timestamptz not null default now(), voided_at timestamptz, note text
);
create table if not exists swarm.runs (
  id bigserial primary key, project_id text not null, change_id text, task_id text,
  kind text not null check (kind in ('plan','implement','review','explore','hotfix')),
  role text not null, model text, effort text, mode text not null default 'headless',
  state text not null default 'queued' check (state in ('queued','running','succeeded','failed','cancelled','timeout','parked')),
  auth_kind text, branch text, worktree text, session_id text, policy_hash text,
  started_at timestamptz, ended_at timestamptz, created_at timestamptz not null default now(),
  turns int, input_tokens bigint, output_tokens bigint, cache_read_tokens bigint, cache_creation_tokens bigint,
  cost_usd numeric(12,6), context_end bigint, retries int not null default 0, quota_utilization numeric(6,3),
  progress text, summary text
);
create index if not exists runs_project_state on swarm.runs (project_id, state);
create table if not exists swarm.events (
  id bigserial primary key, run_id bigint references swarm.runs(id) on delete cascade, ts timestamptz not null default now(),
  project_id text not null, type text not null, role text, model text, tool text, duration_ms bigint, ok boolean, detail jsonb not null default '{}'
);
create index if not exists events_run on swarm.events (run_id, ts);
create table if not exists swarm.verdicts (
  id bigserial primary key, run_id bigint, project_id text not null, change_id text not null,
  passed boolean not null, scenarios jsonb not null default '[]', findings jsonb not null default '[]', created_at timestamptz not null default now()
);
create table if not exists swarm.recalls (
  id bigserial primary key, run_id bigint, project_id text not null, dataset text, query_hash text,
  results int not null default 0, used boolean, rejected boolean not null default false, created_at timestamptz not null default now()
);
create table if not exists swarm.health (
  id bigserial primary key, run_id bigint, project_id text not null, change_id text, ok boolean not null, output_tail text, ts timestamptz not null default now()
);
create table if not exists swarm.comparisons (
  id bigserial primary key, name text not null, run_a bigint not null, run_b bigint not null, note text, created_at timestamptz not null default now()
);

-- v2: the git agent records its phases as runs of kind 'git'
do $$ begin
  if exists (select 1 from pg_constraint where conname='runs_kind_check' and conrelid='swarm.runs'::regclass) then
    alter table swarm.runs drop constraint runs_kind_check;
  end if;
  alter table swarm.runs add constraint runs_kind_check check (kind in ('plan','implement','review','explore','hotfix','git'));
end $$;

-- v3: team-mode runs
do $$ begin
  alter table swarm.runs drop constraint if exists runs_kind_check;
  alter table swarm.runs add constraint runs_kind_check check (kind in ('plan','implement','review','explore','hotfix','git','team'));
end $$;
