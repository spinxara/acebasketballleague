-- Run in the Supabase SQL editor if players already exists with a unique display_name.
-- Identity is players.id (uuid); duplicate display names are allowed.

alter table players
  drop constraint if exists players_display_name_key;
