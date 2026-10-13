-- Run in the Supabase SQL editor.
-- Allows the app API key to insert/update/delete seasons (same pattern as players).
-- Public read can stay as-is; this adds write access needed by /admin/seasons.

alter table seasons enable row level security;

drop policy if exists "public read seasons" on seasons;
create policy "public read seasons"
  on seasons for select using (true);

drop policy if exists "anon write seasons" on seasons;
create policy "anon write seasons"
  on seasons for all using (true) with check (true);

-- Optional: remove leftover status-probe rows from local testing
delete from seasons
where season like '\_\_probe\_%' escape '\';
