-- Run after player_stats_add_player_id.sql when unmatched (NM) names remain.
-- Inserts non-member players using the exact stats display names (including " (NM)"),
-- then re-backfills player_stats_by_season.player_id.

insert into players (display_name, non_member, active)
select v.display_name, true, false
from (
  values
    ('Boum Soo Kim (NM)'),
    ('David Lim (NM)'),
    ('Dongjun Min (NM)'),
    ('Evan Ghang (NM)'),
    ('Fateen Mukarram (NM)'),
    ('Jay (NM)'),
    ('Jay Lim (NM)'),
    ('Johann Lee (NM)'),
    ('Julius Chung (NM)'),
    ('Kevin (NM)'),
    ('Richard (NM)'),
    ('Sam (NM)'),
    ('Sean (NM)'),
    ('Unknown Guest (NM)'),
    ('Yoon Yi Kim (NM)'),
    ('Younghoon Park (NM)')
) as v(display_name)
where not exists (
  select 1 from players p where p.display_name = v.display_name
);

update player_stats_by_season pss
set player_id = p.id
from players p
where pss.player_id is null
  and pss.player = p.display_name;

-- Also link other legacy tables if those names appear there.
update player_played_games ppg
set player_id = p.id
from players p
where ppg.player_id is null
  and ppg.name = p.display_name;

update player_stats_total pst
set player_id = p.id
from players p
where pst.player_id is null
  and pst.player = p.display_name;

select player, season
from player_stats_by_season
where player_id is null
order by player, season;
