-- Run in the Supabase SQL editor.
-- Season winner, MIP, and extra season photos are rows in team_moments.
-- Existing gallery photos stay as they are: season and photo_kind remain null.
-- photo_kind: winner | mip | season

alter table team_moments add column if not exists season text;
alter table team_moments add column if not exists photo_kind text;

alter table team_moments drop constraint if exists team_moments_photo_kind_check;
alter table team_moments add constraint team_moments_photo_kind_check
  check (photo_kind is null or photo_kind in ('winner', 'mip', 'season'));

create unique index if not exists team_moments_one_winner_per_season
  on team_moments (season)
  where photo_kind = 'winner';

create unique index if not exists team_moments_one_mip_per_season
  on team_moments (season)
  where photo_kind = 'mip';
