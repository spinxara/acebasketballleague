create table if not exists team_moments (
  id uuid primary key default gen_random_uuid(),
  caption text,
  storage_path text not null,
  original_filename text,
  created_at timestamptz not null default now()
);

alter table team_moments enable row level security;

drop policy if exists "public read team moments" on team_moments;
create policy "public read team moments"
  on team_moments for select using (true);

drop policy if exists "anon write team moments" on team_moments;
create policy "anon write team moments"
  on team_moments for all using (true) with check (true);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'team-moments',
  'team-moments',
  true,
  10485760,
  array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
on conflict (id) do update
set
  public = true,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "public read team-moments" on storage.objects;
create policy "public read team-moments"
  on storage.objects for select
  using (bucket_id = 'team-moments');

drop policy if exists "anon insert team-moments" on storage.objects;
create policy "anon insert team-moments"
  on storage.objects for insert
  with check (bucket_id = 'team-moments');

drop policy if exists "anon delete team-moments" on storage.objects;
create policy "anon delete team-moments"
  on storage.objects for delete
  using (bucket_id = 'team-moments');
