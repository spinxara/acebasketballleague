# ACE Basketball League Site

A Flask and Socket.IO app for the ACE basketball league: public season stats, team moments, and an admin draft room for weighted seed picks and a live snake draft.

Live site: https://acebasketballteam.com

`https://www.acebasketballteam.com` redirects to that address.

## Features

### Public site

- Marketing landings at `/` (English) and `/ko` (Korean): hero, when/where, season overview, and contact. Logo in the header returns to `/`.
- Guidebook hub at `/home` (nav label Home): rules, what’s included, social links, and sponsor logos.
- About page with the Sunday schedule, Glendale court, and a Korean introduction that links to `/ko`.
- Top navigation: Home (`/home`), About, Stats, and Moments. Stats opens Season Results, Member Stats, Player Stats by Season, and Team Matchups. Those pages also show a section bar for the same links.
- Season results, member stats, player stats by season, and team matchups (loaded from Supabase).
- Team moments photo gallery.
- League game rules (version 3.1), linked from the home page and the footer.
- Sponsor row on the home page and a "Supported by" line in the footer. Names, links, and logos live in `SPONSORS` in `app.py`.

### Admin

- Password-protected login at `/admin` (`ADMIN_PASSWORD` for full access, `CAPTAIN_PASSWORD` for draft-only captain access).
- Draft room at `/admin/draft` with shared real-time state over Socket.IO.
- Weighted seed picking for NPS, KCN, and BK.
- Settings menu to calculate odds from last-season win rates or enter captain-agreed percentages.
- Seed history with a maximum of 100 runs before clearing history is required.
- Three-team snake draft. The player pool is active members (`non_member = false`) from the Players table (mark people active before drafting). Roster size follows that list; team count stays fixed at 3.

```text
1 -> 2 -> 3 -> 3 -> 2 -> 1 -> 1 -> 2 -> 3 -> 3 -> 2 -> 1 ...
```

- One-level undo for the most recent draft pick.
- Full draft reset for choosing new captains and restarting (reloads the active player pool).
- Team moments upload and delete (JPEG, PNG, WEBP, or GIF; 10MB max; optional 280-character caption).
- Players page to list, add, and update league members and non-members (`active` / `non_member` / comments) in Supabase.
- Seasons page to add seasons and edit status (`planned` / `active` / `completed`), dates, winners/runner-ups, MIP, notes, and season page links.
- Roster page to view a season’s `team_members`, move players between NPS/KCN/BK, add/remove players, and clear a season roster (initial roster still comes from Draft Room).
- Games page to save one Sunday: six `game_results` (winner, no score) and `player_played_games` lineups, then `refresh_all_stats`.
- Placeholder pages for dashboard, games, and tournament (not wired yet).

Visiting `/draft` redirects to `/admin/draft`.

## Project Structure

```text
.
├── app.py                      # Flask / Socket.IO app
├── requirements.txt
├── runtime.txt                 # Python 3.12.8
├── templates/
│   ├── public/                 # Public league pages
│   └── admin/                  # Login, draft, players, seasons, moments, placeholders
├── static/                     # CSS, JS, and sponsor logos in static/sponsors/
└── supabase/
    ├── team_moments.sql                      # Team Moments table and storage bucket
    ├── players.sql                           # League players table and seed
    ├── players_drop_display_name_unique.sql  # Drop unique name constraint if present
    ├── players_rename_guest_to_non_member.sql
    ├── team_members_add_player_id.sql        # Link team_members to players.id
    ├── team_members_player_id_unique.sql     # Unique on (season, player_id), not name
    ├── player_stats_add_player_id.sql        # Link stats / played-games to players.id
    └── players_seed_non_members.sql          # Seed (NM) non-members and re-link
```

Older files such as `app_v1.00.py` and `advanced_random_order.py` are leftover experiments and are not used by the current app.

## Requirements

- Python 3.12.8
- Flask, Flask-SocketIO, python-dotenv, certifi, and Pillow
- A `.env` file (see below)
- A Render web service for the public site

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Copy these into a `.env` file in the project root. `.env` is gitignored.

```bash
SECRET_KEY=change-this
ADMIN_PASSWORD=your-admin-password
CAPTAIN_PASSWORD=your-captain-password
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_API_KEY=your-supabase-anon-or-service-key
SESSION_COOKIE_SECURE=false
FLASK_DEBUG=false
PORT=5055
SITE_URL=https://acebasketballteam.com
```

| Variable | Required | Notes |
| --- | --- | --- |
| `SECRET_KEY` | Yes in production | Flask session signing. Default is `change-this`. |
| `ADMIN_PASSWORD` | Yes for full admin | Full admin access (all `/admin` pages). Login as admin fails if this is empty. |
| `CAPTAIN_PASSWORD` | Yes for captain access | Draft-room-only access. Captain login fails if this is empty. |
| `SUPABASE_URL` | Yes for stats and moments | Project URL with no trailing slash. |
| `SUPABASE_API_KEY` | Yes for stats and moments | Supabase API key used for REST and storage. |
| `SESSION_COOKIE_SECURE` | No | Set `true` when serving over HTTPS. |
| `FLASK_DEBUG` | No | Set `true` only for local development. |
| `PORT` | No | Defaults to `5055`. |
| `SITE_URL` | No | Canonical public URL with no trailing slash. Defaults to `https://acebasketballteam.com`. |

Without Supabase credentials, public stats and team moments pages load with an error. Seed picking and draft still work.

## Run Locally

```bash
python3 app.py
```

The app listens on:

```text
http://localhost:5055
```

Landing: `http://localhost:5055/`
Korean landing: `http://localhost:5055/ko`
Guidebook: `http://localhost:5055/home`
Admin: `http://localhost:5055/admin`

## Render

The public site is a Render web service. Attach both custom domains:

- `acebasketballteam.com`
- `www.acebasketballteam.com`

Requests to the `www` host redirect to the same path on `https://acebasketballteam.com`. Localhost and the `onrender.com` service URL are left as they are.

On the Render service, set `SESSION_COOKIE_SECURE=true`. Set `SITE_URL` only if the public URL should differ from the default.

## Search

Public pages include a description, canonical URL, share tags, and SportsOrganization structured data (name, Glendale address, and social profiles). `/` and `/ko` are the marketing landings and include `hreflang` alternates (`en`, `ko`, `x-default`). `/robots.txt` allows public pages and blocks `/admin` and `/draft`. `/sitemap.xml` lists the public URLs, including `/`, `/ko`, `/home`, and `/about`. Admin pages send `noindex, nofollow`.

After deploy:

1. In Google Search Console, add a domain property for `acebasketballteam.com`, verify it with a DNS record at the domain registrar, and submit `https://acebasketballteam.com/sitemap.xml`.
2. Use URL Inspection on `https://acebasketballteam.com/ko` and request indexing.
3. Put `https://acebasketballteam.com` in the Instagram bio and the YouTube channel About section.

Indexing usually takes days to a few weeks.

## How To Use

### Public pages

Open `/` for the English landing or `/ko` for Korean. Use Home (`/home`), About, Stats, and Moments in the top nav for the guidebook. Inside Stats, the section bar stays on Season Results, Member Stats, Player Stats by Season, and Team Matchups. Game rules are on `/home` and in the footer. Stats pages read from Supabase; member totals are refreshed via the `refresh_player_totals` RPC when that function exists.

### Sponsors

Add or edit entries in `SPONSORS` in `app.py`. Each sponsor can have a name, an optional URL, an optional logo path under `static/`, and `featured: True` to show it first. The home page shows a logo when one is set, otherwise the name. Every sponsor name also appears in the footer. Current sponsors are Clan H. Hahn, MD and AD-VISOR Creative.

### Admin login

1. Go to `/admin` and enter `ADMIN_PASSWORD` (full access) or `CAPTAIN_PASSWORD` (draft room only).
2. Captains are redirected to `/admin/draft` and cannot open other admin pages.
3. Login is rate-limited: 5 failed attempts per IP in 10 minutes.

### Seed picking

1. Open **Draft Room**.
2. Click **Run Seed** to generate weighted seed results.
3. Use **Settings** to calculate odds from wins or enter manual percentages.
4. Clear history when the 100-run limit is reached.

### Player draft

1. Select one captain for each of the three seeds.
2. Click **Start Draft**.
3. Click an available player name when that seed is on the clock.
4. Use **Undo Last Pick** to revert the most recent pick.
5. Use **Reset Draft** to clear the draft and start over.

Draft state is shared live with everyone connected. Seed and draft socket events require an admin or captain session.

### Players

1. Open **Players** in admin.
2. Add a member or non-member with display name, optional comments, and active/non_member flags.
3. Filter by All, Active, Inactive, or Non-member.
4. Edit any rows, then click **Save all changes** once. Deactivate instead of deleting.

### Team moments

1. Open **Team Moments** in admin.
2. Upload one or more photos with an optional shared caption.
3. Delete a moment to remove it from storage and the gallery.

## Supabase

Public stats pages expect these tables (or views):

- `seasons`
- `player_stats_total` (refreshed by `refresh_player_totals` when available)
- `player_stats_by_season`
- `team_matchup_strength`
- `team_moments`
- `players` (league members and non-members; draft pool = `active` and not `non_member`)
- `team_members` (per-season roster; created from Draft Room, managed on Roster)

Team Moments also uses a public `team-moments` storage bucket. To create the table, policies, and bucket, run `supabase/team_moments.sql` in the Supabase SQL editor.

To add the league members table and link season rosters / stats:

1. Run `supabase/players.sql` (creates `players` and seeds current members; identity is `id`, duplicate display names are allowed; column is `non_member`, not `guest`).
2. If `players` already had a unique name constraint, run `supabase/players_drop_display_name_unique.sql`.
3. If `players` still has a `guest` column, run `supabase/players_rename_guest_to_non_member.sql`.
4. Run `supabase/team_members_add_player_id.sql` (adds nullable `player_id` on `team_members`).
5. Run `supabase/team_members_player_id_unique.sql` (replaces name-based `uq_team_members` with unique `(season, player_id)` so duplicate display names can share a season).
6. Run `supabase/player_stats_add_player_id.sql` (adds nullable `player_id` on `player_played_games`, `player_stats_by_season`, and `player_stats_total`; backfills by name match).
7. If unmatched `(NM)` names remain, run `supabase/players_seed_non_members.sql` (inserts those display names as `non_member = true`, then re-backfills).

For Seasons admin writes (add / edit / delete), run `supabase/seasons_admin_policies.sql` so RLS allows the API key to modify the existing `seasons` table.

For Draft Room “Save to roster” and Roster admin writes (insert/update/delete on `team_members`), run `supabase/team_members_admin_policies.sql` so RLS allows the API key to modify roster rows.

For Games admin writes (`game_results` and `player_played_games`), run `supabase/games_admin_policies.sql`.

## Notes

- The Render service must stay running for the public site and for Google to crawl it.
- After a completed draft, use **Save to roster** on the Draft Room page to write NPS/KCN/BK members into `team_members` for a chosen season. Use the **Roster** admin page afterward for mid-season trades, adds/removals, or clearing a season so Draft can save again. Use **Games** to enter a Sunday (six games and lineups). Tournament and dashboard admin pages are still placeholders. Seasons metadata is managed on the Seasons admin page.

## Maintainer

Dae Young Roh (spinxara@gmail.com)
