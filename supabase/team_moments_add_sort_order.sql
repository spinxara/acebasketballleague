-- Run in the Supabase SQL editor.
-- Lower sort_order appears first on Team Moments.
-- Existing photos keep their current newest-first order.

alter table team_moments add column if not exists sort_order integer;

with ranked as (
  select id, row_number() over (order by created_at desc) as position
  from team_moments
  where sort_order is null
)
update team_moments as moments
set sort_order = ranked.position
from ranked
where moments.id = ranked.id;
