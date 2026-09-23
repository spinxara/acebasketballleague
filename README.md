# ACE Basketball League Site

A Flask and Socket.IO app for the ACE basketball league: public season stats, team moments, and an admin draft room for weighted seed picks and a live snake draft.

Live site: https://acebasketballteam.com

`https://www.acebasketballteam.com` redirects to that address.

## Features

### Public site

- Home page with league overview, rules, social links, and sponsor logos.
- About page with the Sunday schedule, Glendale court, and a Korean introduction.
- Top navigation: Home, About, Stats, and Moments. Stats opens Season Results, Member Stats, Player Stats by Season, and Team Matchups. Those pages also show a section bar for the same links.
- Season results, member stats, player stats by season, and team matchups (loaded from Supabase).
- Team moments photo gallery.
- League game rules (version 3.1), linked from the home page and the footer.
- Sponsor row on the home page and a "Supported by" line in the footer. Names, links, and logos live in `SPONSORS` in `app.py`.

### Admin

- Password-protected captain login at `/admin`.
- Draft room at `/admin/draft` with shared real-time state over Socket.IO.
- Weighted seed picking for NPS, KCN, and BK.
- Settings menu to calculate odds from last-season win rates or enter captain-agreed percentages.
- Seed history with a maximum of 100 runs before clearing history is required.
- Three-team snake draft:

```text
1 -> 2 -> 3 -> 3 -> 2 -> 1 -> 1 -> 2 -> 3 -> 3 -> 2 -> 1 ...
```

- One-level undo for the most recent draft pick.
- Full draft reset for choosing new captains and restarting.
- Team moments upload and delete (JPEG, PNG, WEBP, or GIF; 10MB max; optional 280-character caption).
- Placeholder pages for dashboard, roster, games, and tournament (not wired yet).

Visiting `/draft` redirects to `/admin/draft`.

## Project Structure

```text
.
├── app.py                      # Flask / Socket.IO app
├── requirements.txt
├── runtime.txt                 # Python 3.12.8
├── templates/
│   ├── public/                 # Public league pages
│   └── admin/                  # Login, draft room, moments, placeholders
├── static/                     # CSS, JS, and sponsor logos in static/sponsors/
└── supabase/
    └── team_moments.sql        # Team Moments table and storage bucket
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
| `ADMIN_PASSWORD` | Yes for admin | Shared captain password. Admin login fails if this is empty. |
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

Public pages: `http://localhost:5055/`
Admin: `http://localhost:5055/admin`

## Render

The public site is a Render web service. Attach both custom domains:

- `acebasketballteam.com`
- `www.acebasketballteam.com`

Requests to the `www` host redirect to the same path on `https://acebasketballteam.com`. Localhost and the `onrender.com` service URL are left as they are.

On the Render service, set `SESSION_COOKIE_SECURE=true`. Set `SITE_URL` only if the public URL should differ from the default.

## Search

Public pages include a description, canonical URL, share tags, and SportsOrganization structured data (name, Glendale address, and social profiles). `/robots.txt` allows those pages and blocks `/admin` and `/draft`. `/sitemap.xml` lists the public URLs, including `/about`. Admin pages send `noindex, nofollow`.

After deploy:

1. In Google Search Console, add a domain property for `acebasketballteam.com`, verify it with a DNS record at the domain registrar, and submit `https://acebasketballteam.com/sitemap.xml`.
2. Put `https://acebasketballteam.com` in the Instagram bio and the YouTube channel About section.

Indexing usually takes days to a few weeks.

## How To Use

### Public pages

Open the home page. Use Home, About, Stats, and Moments in the top nav. Inside Stats, the section bar stays on Season Results, Member Stats, Player Stats by Season, and Team Matchups. Game rules are on the home page and in the footer. Stats pages read from Supabase; member totals are refreshed via the `refresh_player_totals` RPC when that function exists.

### Sponsors

Add or edit entries in `SPONSORS` in `app.py`. Each sponsor can have a name, an optional URL, an optional logo path under `static/`, and `featured: True` to show it first. The home page shows a logo when one is set, otherwise the name. Every sponsor name also appears in the footer. Current sponsors are Clan H. Hahn, MD and AD-VISOR Creative.

### Admin login

1. Go to `/admin` and enter `ADMIN_PASSWORD`.
2. Login is rate-limited: 5 failed attempts per IP in 10 minutes.

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

Draft state is shared live with everyone connected. Seed and draft socket events require an admin session.

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

Team Moments also uses a public `team-moments` storage bucket. To create the table, policies, and bucket, run `supabase/team_moments.sql` in the Supabase SQL editor.

## Notes

- The Render service must stay running for the public site and for Google to crawl it.
- Roster, games, tournament, and dashboard admin pages are placeholders for later data-entry work.

## Maintainer

Dae Young Roh (spinxara@gmail.com)
