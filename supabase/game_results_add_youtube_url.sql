-- Run in the Supabase SQL editor.
-- Optional YouTube link for each game. Blank means no video yet.

alter table game_results add column if not exists youtube_url text;
