-- Run in the Supabase SQL editor.
-- Allows the app API key to insert/update/delete game_results and player_played_games
-- (same pattern as seasons). Public read can stay as-is.

alter table game_results enable row level security;

drop policy if exists "public read game_results" on game_results;
create policy "public read game_results"
  on game_results for select using (true);

drop policy if exists "anon write game_results" on game_results;
create policy "anon write game_results"
  on game_results for all using (true) with check (true);

alter table player_played_games enable row level security;

drop policy if exists "public read player_played_games" on player_played_games;
create policy "public read player_played_games"
  on player_played_games for select using (true);

drop policy if exists "anon write player_played_games" on player_played_games;
create policy "anon write player_played_games"
  on player_played_games for all using (true) with check (true);
