-- Run in the Supabase SQL editor after players exists.
-- Renames players.guest -> players.non_member (values unchanged).

alter table players
  rename column guest to non_member;

drop index if exists players_active_guest_idx;

create index if not exists players_active_non_member_idx
  on players (active, non_member);
