-- Run this after players.sql.
-- Adds nullable player_id, backfills from name match, then lists unmatched rows.

alter table team_members
  add column if not exists player_id uuid references players(id);

create index if not exists team_members_player_id_idx
  on team_members (player_id);

update team_members tm
set player_id = p.id
from players p
where tm.player_id is null
  and tm.player = p.display_name;

-- Rows still null usually mean a name spelling mismatch.
select season, player, season_team
from team_members
where player_id is null
order by season, player;
