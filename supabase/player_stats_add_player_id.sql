-- Run after players.sql (and preferably after team_members_add_player_id.sql).
-- Adds nullable player_id on legacy player tables, backfills from name match,
-- then lists unmatched rows for manual cleanup.

-- 1) player_played_games (name column)
alter table player_played_games
  add column if not exists player_id uuid references players(id);

create index if not exists player_played_games_player_id_idx
  on player_played_games (player_id);

update player_played_games ppg
set player_id = p.id
from players p
where ppg.player_id is null
  and ppg.name = p.display_name;

-- 2) player_stats_by_season (player column)
alter table player_stats_by_season
  add column if not exists player_id uuid references players(id);

create index if not exists player_stats_by_season_player_id_idx
  on player_stats_by_season (player_id);

update player_stats_by_season pss
set player_id = p.id
from players p
where pss.player_id is null
  and pss.player = p.display_name;

-- 3) player_stats_total (player column)
alter table player_stats_total
  add column if not exists player_id uuid references players(id);

create index if not exists player_stats_total_player_id_idx
  on player_stats_total (player_id);

update player_stats_total pst
set player_id = p.id
from players p
where pst.player_id is null
  and pst.player = p.display_name;

-- Rows still null usually mean a name spelling mismatch (often " (NM)" suffix).
-- Seed those names with players_seed_non_members.sql, then re-run the updates above
-- or run that file's backfill step.
select 'player_played_games' as source, name as player_name, season, game_id
from player_played_games
where player_id is null
order by season, name;

select 'player_stats_by_season' as source, player as player_name, season
from player_stats_by_season
where player_id is null
order by season, player;

select 'player_stats_total' as source, player as player_name
from player_stats_total
where player_id is null
order by player;
