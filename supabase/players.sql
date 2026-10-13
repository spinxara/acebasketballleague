-- Run this first in the Supabase SQL editor.
-- Creates the league-level players table and seeds current members.

create table if not exists players (
  id uuid primary key default gen_random_uuid(),
  display_name text not null,
  non_member boolean not null default false,
  active boolean not null default true,
  comments text,
  created_at timestamptz not null default now()
);

create index if not exists players_active_non_member_idx
  on players (active, non_member);

alter table players enable row level security;

drop policy if exists "public read players" on players;
create policy "public read players"
  on players for select using (true);

drop policy if exists "anon write players" on players;
create policy "anon write players"
  on players for all using (true) with check (true);

-- Seed once by name so re-running this file does not duplicate the initial roster.
-- Admin may still add intentional duplicate display names (identity is players.id).
insert into players (display_name, non_member, active)
select v.display_name, v.non_member, v.active
from (
  values
    ('Alex Hahn', false, false),
    ('Allen 기준 Lee', false, false),
    ('Bernard Ilwoo Shim', false, false),
    ('Boum Soo Kim', false, false),
    ('Brian 병훈 Paek', false, false),
    ('Clan Hahn', false, false),
    ('Dae Young Roh', false, false),
    ('David 민형 Jin', false, false),
    ('Denny 분도 Kim', false, false),
    ('Donggyu Lee', false, false),
    ('Dongjun Min', false, false),
    ('Edward 성준 Lee', false, false),
    ('Edward 에디 Kim', false, false),
    ('Eric 형승 Lim', false, false),
    ('Henry 형석 Lee', false, false),
    ('Hobeen Baek', false, false),
    ('Johann Lee', false, false),
    ('Jong 종근 Yoo', false, false),
    ('JongHyun Han', false, false),
    ('Mark 마크 Jung', false, false),
    ('Mike Hong', false, false),
    ('Min Hun 민훈 Paik', false, false),
    ('Minsoo 민수 Park', false, false),
    ('Minwoo Cho', false, false),
    ('Peter 석현 Yeon', false, false),
    ('Peter 정욱 Shin', false, false),
    ('Quinn 규현 Chung', false, false),
    ('Ryan 규호 Choi', false, false),
    ('Sangmin Moon', false, false),
    ('Shawn White', false, false),
    ('Sungjun 성준 Hong', false, false),
    ('Tenzing Sherpa', false, false),
    ('Tom 언호 Lee', false, false),
    ('Tong Young Ko', false, false)
) as v(display_name, non_member, active)
where not exists (
  select 1 from players p where p.display_name = v.display_name
);
