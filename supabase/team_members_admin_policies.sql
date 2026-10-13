-- Run in the Supabase SQL editor.
-- Allows the app API key to insert/update/delete team_members (same pattern as seasons/players).
-- Needed by Draft Room "Save to roster".

alter table team_members enable row level security;

drop policy if exists "public read team_members" on team_members;
create policy "public read team_members"
  on team_members for select using (true);

drop policy if exists "anon write team_members" on team_members;
create policy "anon write team_members"
  on team_members for all using (true) with check (true);
