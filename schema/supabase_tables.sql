-- Supabase table definitions for the backend metadata store

create table if not exists jobs (
  id bigserial primary key,
  name text not null,
  description text,
  annual_budget text,
  primary_skills text,
  target_keywords text,
  industry text,
  location text not null,
  min_experience text,
  connection_degree text,
  employee_count text,
  status text not null,
  created_at timestamptz not null default now()
);

create table if not exists pipelines (
  session_id bigint primary key references jobs(id) on delete cascade,
  status text not null,
  error text,
  started_at timestamptz,
  finished_at timestamptz
);
