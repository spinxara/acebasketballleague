-- Run after team_members_add_player_id.sql.
-- Roster identity is (season, player_id). Duplicate display names are allowed.
-- The player text column stays as a denormalized display label.

-- Drop the legacy name-based unique constraint / index (season, player).
alter table team_members drop constraint if exists uq_team_members;
drop index if exists uq_team_members;

-- One roster slot per player per season (keyed by players.id).
-- NULL player_id rows (unmatched legacy) are allowed multiple times in Postgres UNIQUE.
alter table team_members
  add constraint uq_team_members unique (season, player_id);

-- Confirm every current roster row is linked (manual fix if any remain null).
select season, player, season_team
from team_members
where player_id is null
order by season, player;
