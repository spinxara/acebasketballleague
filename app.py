import hmac
import json
import os
import random
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO
from threading import Lock
from urllib.parse import urlparse
from uuid import UUID, uuid4

import certifi
from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit
from PIL import Image, ImageOps, UnidentifiedImageError

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ""
CAPTAIN_PASSWORD = os.environ.get("CAPTAIN_PASSWORD") or ""
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=10)
_login_attempts = {}
_login_lock = Lock()

RULES_URL = (
    "https://docs.google.com/document/d/"
    "1fIlVY1edEn2_5AAxF6eNV0D72vtWwOF4CamZVsxT8q0/edit?usp=sharing"
)
YOUTUBE_URL = "https://www.youtube.com/channel/UCZ6oGz5C9yV2RgsykYvAOyA"
INSTAGRAM_URL = "https://www.instagram.com/la_ace_basketball/"
MAINTAINER_NAME = "Dae Young Roh"
MAINTAINER_KAKAO = "spinxara"
# Split so the address is never rendered as plain text; the footer and About
# page reassemble it in the browser.
MAINTAINER_EMAIL_USER = "spinxara"
MAINTAINER_EMAIL_DOMAIN = "gmail.com"
SITE_URL = os.environ.get("SITE_URL", "https://acebasketballteam.com").rstrip("/")
WWW_HOST = "www.acebasketballteam.com"
PUBLIC_SITEMAP_PATHS = (
    "/",
    "/ko",
    "/home",
    "/about",
    "/rules",
    "/season-results",
    "/member-stats",
    "/player-stats",
    "/team-matchups",
    "/team-moments",
)
HREFLANG_PATHS = frozenset({"/", "/ko"})

SPONSORS = [
    {
        "name": "Clan H. Hahn, MD",
        "featured": True,
    },
    {
        "name": "AD-VISOR Creative",
        "url": "https://www.ad-visorcreative.com/",
        "logo": "sponsors/ad-visor-creative.png",
    },
]

PUBLIC_NAV = [
    {"id": "home", "label": "Home", "endpoint": "home"},
    {"id": "about", "label": "About", "endpoint": "about"},
    {
        "id": "stats",
        "label": "Stats",
        "children": [
            {"id": "season-results", "label": "Season Results", "endpoint": "season_results"},
            {"id": "member-stats", "label": "Member Stats", "endpoint": "member_stats"},
            {"id": "player-stats", "label": "Player Stats by Season", "endpoint": "player_stats"},
            {"id": "team-matchups", "label": "Team Matchups", "endpoint": "team_matchups"},
        ],
    },
    {"id": "team-moments", "label": "Moments", "endpoint": "team_moments"},
]

ADMIN_NAV = [
    {"id": "dashboard", "label": "Dashboard", "endpoint": "admin_dashboard"},
    {
        "id": "preseason",
        "label": "Preseason",
        "children": [
            {"id": "players", "label": "Players", "endpoint": "admin_players"},
            {"id": "seasons", "label": "Seasons", "endpoint": "admin_seasons"},
            {"id": "draft", "label": "Draft Room", "endpoint": "admin_draft"},
            {"id": "roster", "label": "Roster", "endpoint": "admin_roster"},
        ],
    },
    {
        "id": "season",
        "label": "Season",
        "children": [
            {"id": "games", "label": "Games", "endpoint": "admin_games"},
        ],
    },
    {
        "id": "postseason",
        "label": "Postseason",
        "children": [
            {"id": "tournament", "label": "Tournament", "endpoint": "admin_tournament"},
        ],
    },
    {
        "id": "others",
        "label": "Others",
        "children": [
            {"id": "moments", "label": "Team Moments", "endpoint": "admin_moments"},
        ],
    },
]

ADMIN_DRAFT_NAV_ITEM = {
    "id": "draft",
    "label": "Draft Room",
    "endpoint": "admin_draft",
}


def session_admin_role():
    role = session.get("admin_role")
    if role in {"admin", "captain"}:
        return role
    # Legacy sessions set only is_admin before roles existed.
    if session.get("is_admin"):
        return "admin"
    return None


def is_admin_session():
    return session_admin_role() is not None


def is_full_admin_session():
    return session_admin_role() == "admin"


def is_captain_session():
    return session_admin_role() == "captain"


def captain_may_access(path):
    return path == "/admin/draft" or path.startswith("/admin/draft/")


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.remote_addr or "unknown"


def login_is_blocked(ip):
    cutoff = datetime.now() - LOGIN_WINDOW
    with _login_lock:
        recent = [stamp for stamp in _login_attempts.get(ip, []) if stamp > cutoff]
        if recent:
            _login_attempts[ip] = recent
        else:
            _login_attempts.pop(ip, None)
        return len(recent) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(ip):
    with _login_lock:
        _login_attempts.setdefault(ip, []).append(datetime.now())


def clear_failed_logins(ip):
    with _login_lock:
        _login_attempts.pop(ip, None)


def _password_equals(submitted, expected):
    if not expected:
        return False
    secret = str(app.config["SECRET_KEY"]).encode("utf-8")
    guessed = hmac.new(secret, (submitted or "").encode("utf-8"), "sha256").digest()
    target = hmac.new(secret, expected.encode("utf-8"), "sha256").digest()
    return hmac.compare_digest(guessed, target)


def resolve_login_role(submitted):
    admin_ok = _password_equals(submitted, ADMIN_PASSWORD)
    captain_ok = _password_equals(submitted, CAPTAIN_PASSWORD)
    if admin_ok:
        return "admin"
    if captain_ok:
        return "captain"
    return None


def safe_admin_next(value, role=None):
    role = role or session_admin_role()
    default = (
        url_for("admin_draft") if role == "captain" else url_for("admin_dashboard")
    )
    if not isinstance(value, str):
        return default
    path = urlparse(value).path
    if not (path.startswith("/admin") and not path.startswith("/admin/login")):
        return default
    if role == "captain" and not captain_may_access(path):
        return url_for("admin_draft")
    return path


def admin_socket_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not is_admin_session():
            emit("system_message", {"message": "Please log in to use admin tools."})
            return
        return handler(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals():
    path = request.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    logo_url = SITE_URL + url_for("static", filename="logo.png")
    admin_nav = ADMIN_NAV
    if is_captain_session():
        admin_nav = [ADMIN_DRAFT_NAV_ITEM]
    hreflang_alternates = None
    if path in HREFLANG_PATHS:
        hreflang_alternates = [
            {"lang": "en", "href": SITE_URL + "/"},
            {"lang": "ko", "href": SITE_URL + "/ko"},
            {"lang": "x-default", "href": SITE_URL + "/"},
        ]
    return {
        "public_nav": PUBLIC_NAV,
        "admin_nav": admin_nav,
        "rules_url": RULES_URL,
        "youtube_url": YOUTUBE_URL,
        "instagram_url": INSTAGRAM_URL,
        "sponsors": sorted(SPONSORS, key=lambda sponsor: not sponsor.get("featured")),
        "last_updated": "September 14, 2026",
        "current_year": datetime.now().year,
        "maintainer_name": MAINTAINER_NAME,
        "maintainer_kakao": MAINTAINER_KAKAO,
        "maintainer_email_user": MAINTAINER_EMAIL_USER,
        "maintainer_email_domain": MAINTAINER_EMAIL_DOMAIN,
        "is_admin": is_admin_session(),
        "is_full_admin": is_full_admin_session(),
        "is_captain": is_captain_session(),
        "site_url": SITE_URL,
        "canonical_url": SITE_URL + path,
        "logo_url": logo_url,
        "hreflang_alternates": hreflang_alternates,
        "organization_schema": {
            "@context": "https://schema.org",
            "@type": "SportsOrganization",
            "name": "ACE Basketball League",
            "sport": "Basketball",
            "url": SITE_URL + "/",
            "logo": logo_url,
            "sameAs": [YOUTUBE_URL, INSTAGRAM_URL],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "1219 Los Angeles St",
                "addressLocality": "Glendale",
                "addressRegion": "CA",
                "postalCode": "91204",
                "addressCountry": "US",
            },
            "areaServed": "Los Angeles",
            "contactPoint": {
                "@type": "ContactPoint",
                "contactType": "Website maintainer",
                "name": MAINTAINER_NAME,
                "url": SITE_URL + "/about",
            },
        },
    }


@app.before_request
def redirect_www_host():
    host = (request.host or "").split(":")[0].lower()
    if host != WWW_HOST:
        return None
    target = SITE_URL + (request.full_path or "/")
    if target.endswith("?"):
        target = target[:-1]
    return redirect(target, code=301)


@app.before_request
def require_admin_for_admin_pages():
    if not request.path.startswith("/admin"):
        return None
    if request.endpoint in {"admin_login", "admin_logout"}:
        return None
    if not is_admin_session():
        return redirect(url_for("admin_login", next=request.path))
    if is_captain_session() and not captain_may_access(request.path):
        return redirect(url_for("admin_draft"))
    return None


TEAM_NAMES = ["NPS", "KCN", "BK"]
PROBABILITY_BLEND = 0.8

team_percentages = {
    "NPS": 50,
    "KCN": 35,
    "BK": 15
}

default_season_results = {
    "NPS": {"wins": 5, "losses": 31},
    "KCN": {"wins": 24, "losses": 12},
    "BK": {"wins": 25, "losses": 11}
}

SEED_LABELS = [1, 2, 3]
DRAFT_TEAM_COUNT = 3

shared_state = {
    "is_running": False,
    "latest_result": None,
    "team_percentages": team_percentages,
    "seed_probabilities": [],
    "season_results": default_season_results,
    "history": [],
    "draft": {
        "started": False,
        "completed": False,
        "captains": {},
        "teams": {"1": [], "2": [], "3": []},
        "player_pool": [],
        "available_players": [],
        "pick_sequence": [],
        "current_pick_index": 0,
        "current_seed": None,
        "last_pick": None,
        "roster_saved": False,
        "roster_saved_season": None,
        "message": "Select 3 captains and start the draft."
    }
}


def weighted_seeding(team_weights):
    teams = list(team_weights.keys())
    weights = list(team_weights.values())
    result = []

    while teams:
        chosen = random.choices(teams, weights=weights, k=1)[0]
        result.append(chosen)

        idx = teams.index(chosen)
        teams.pop(idx)
        weights.pop(idx)

    return result


def rounded_percentages(raw_percentages):
    floors = {team: int(value) for team, value in raw_percentages.items()}
    remaining = 100 - sum(floors.values())
    remainders = sorted(
        raw_percentages.items(),
        key=lambda item: (item[1] - int(item[1]), item[0]),
        reverse=True
    )

    for team, _ in remainders[:remaining]:
        floors[team] += 1

    return floors


def calculate_percentages_from_results(season_results):
    total_losses = sum(result["losses"] for result in season_results.values())
    if total_losses <= 0:
        raise ValueError("Total losses must be greater than 0.")

    equal_probability = 100 / len(TEAM_NAMES)
    equal_blend = 1 - PROBABILITY_BLEND
    raw_percentages = {}

    for team in TEAM_NAMES:
        loss_probability = (season_results[team]["losses"] / total_losses) * 100
        raw_percentages[team] = (
            loss_probability * PROBABILITY_BLEND
            + equal_probability * equal_blend
        )

    return rounded_percentages(raw_percentages)


def parse_season_results(data):
    if not data or "season_results" not in data:
        raise ValueError("Please enter season results first.")

    wins_by_team = {}
    for team in TEAM_NAMES:
        team_result = data["season_results"].get(team)
        if not team_result:
            raise ValueError(f"Missing season result for {team}.")

        try:
            wins = int(team_result["wins"])
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"Please enter valid wins for {team}.")

        if wins < 0:
            raise ValueError("Wins cannot be negative.")

        wins_by_team[team] = wins

    total_wins = sum(wins_by_team.values())
    team_count = len(TEAM_NAMES)
    if total_wins <= 0:
        raise ValueError("Total wins must be greater than 0.")
    if (total_wins * 2) % team_count != 0:
        raise ValueError("Wins must match a balanced season where every team played the same number of games.")

    games_per_team = (total_wins * 2) // team_count
    season_results = {}
    for team, wins in wins_by_team.items():
        if wins > games_per_team:
            raise ValueError(f"{team} cannot have more wins than the inferred {games_per_team}-game season.")
        season_results[team] = {
            "wins": wins,
            "losses": games_per_team - wins
        }

    return season_results


def parse_manual_percentages(data):
    if not data or "team_percentages" not in data:
        raise ValueError("Please enter manual probabilities first.")

    manual_percentages = {}
    for team in TEAM_NAMES:
        try:
            percentage = int(data["team_percentages"][team])
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"Please enter a valid probability for {team}.")

        if percentage <= 0:
            raise ValueError("Each team must have a probability greater than 0.")

        manual_percentages[team] = percentage

    if sum(manual_percentages.values()) != 100:
        raise ValueError("Manual probabilities must add up to 100%.")

    return manual_percentages


def apply_team_percentages(new_percentages, season_results=None):
    team_percentages.clear()
    team_percentages.update(new_percentages)
    shared_state["team_percentages"] = team_percentages
    shared_state["seed_probabilities"] = build_seed_probability_matrix(team_percentages)
    if season_results is not None:
        shared_state["season_results"] = season_results


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th') }"


def build_seed_probability_matrix(team_weights):
    seed_totals = {
        team: {ordinal(seed): 0 for seed in range(1, len(team_weights) + 1)}
        for team in team_weights
    }

    def add_probabilities(remaining_weights, seed_number, path_probability):
        total_weight = sum(remaining_weights.values())
        if total_weight <= 0:
            return

        for team, weight in remaining_weights.items():
            pick_probability = path_probability * (weight / total_weight)
            seed_totals[team][ordinal(seed_number)] += pick_probability * 100

            next_weights = dict(remaining_weights)
            next_weights.pop(team)
            if next_weights:
                add_probabilities(next_weights, seed_number + 1, pick_probability)

    add_probabilities(team_weights, 1, 1)

    return [
        {
            "team": team,
            "weight": weight,
            "seeds": [
                {
                    "seed": ordinal(seed),
                    "probability": round(seed_totals[team][ordinal(seed)], 2)
                }
                for seed in range(1, len(team_weights) + 1)
            ]
        }
        for team, weight in team_weights.items()
    ]


shared_state["seed_probabilities"] = build_seed_probability_matrix(team_percentages)


def build_result_payload():
    result = weighted_seeding(team_percentages)
    rows = []
    for i, team in enumerate(result, start=1):
        rows.append({
            "seed": ordinal(i),
            "team": team,
            "weight": team_percentages[team]
        })

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "rows": rows
    }
    return payload


def build_pick_sequence(team_count, pick_count):
    if pick_count <= 0:
        return []

    sequence = []
    forward = list(range(1, team_count + 1))
    backward = list(range(team_count, 0, -1))
    round_number = 0

    while len(sequence) < pick_count:
        sequence.extend(forward if round_number % 2 == 0 else backward)
        round_number += 1

    return sequence[:pick_count]


def draft_idle_message(pool):
    if not pool:
        return "No active players. Mark league members active on the Players page first."
    if len(pool) < DRAFT_TEAM_COUNT:
        return f"Need at least {DRAFT_TEAM_COUNT} active players to draft. Currently {len(pool)}."
    return "Select 3 captains and start the draft."


def draft_player_label(player):
    name = (player.get("display_name") or "").strip()
    comments = (player.get("comments") or "").strip()
    if comments:
        return f"{name} — {comments}"
    return name


def find_draft_player(players, player_id):
    player_id = (player_id or "").strip()
    if not player_id:
        return None
    for player in players or []:
        if player.get("id") == player_id:
            return player
    return None


def reset_draft_state(message=None):
    pool = load_draft_players()
    shared_state["draft"] = {
        "started": False,
        "completed": False,
        "captains": {},
        "teams": {"1": [], "2": [], "3": []},
        "player_pool": pool[:],
        "available_players": pool[:],
        "pick_sequence": [],
        "current_pick_index": 0,
        "current_seed": None,
        "last_pick": None,
        "roster_saved": False,
        "roster_saved_season": None,
        "message": message if message is not None else draft_idle_message(pool),
    }


def refresh_draft_pool_if_idle():
    draft = shared_state["draft"]
    if draft.get("started"):
        return
    pool = load_draft_players()
    draft["player_pool"] = pool[:]
    draft["available_players"] = pool[:]
    draft["message"] = draft_idle_message(pool)


def emit_draft_state():
    socketio.emit("draft_state", shared_state["draft"])


def season_starting_month(quarter):
    return QUARTER_STARTING_MONTH.get(quarter)


def load_draft_season_options():
    """Compact season list for the Save to roster dropdown."""
    try:
        seasons = load_season_records()
    except Exception:
        return []

    def option_sort_key(row):
        status = (row.get("status") or "").strip().lower()
        # Prefer planned/active seasons near the top for draft save.
        status_rank = 0 if status in {"planned", "active"} else 1
        return (status_rank, *season_sort_key(row))

    seasons = sorted(seasons, key=option_sort_key)
    return [
        {
            "season": row["season"],
            "status": row.get("status") or "",
            "status_label": row.get("status_label") or "",
        }
        for row in seasons
        if row.get("season")
    ]


def parse_seed_team_map(data):
    if not data or "seed_teams" not in data:
        raise ValueError("Map each seed to NPS, KCN, or BK.")

    raw = data.get("seed_teams") or {}
    mapping = {}
    for seed in SEED_LABELS:
        team = str(raw.get(str(seed)) or raw.get(seed) or "").strip().upper()
        if team not in TEAM_NAMES:
            raise ValueError(f"Seed {seed} must be mapped to NPS, KCN, or BK.")
        mapping[str(seed)] = team

    if len(set(mapping.values())) != DRAFT_TEAM_COUNT:
        raise ValueError("Each of NPS, KCN, and BK must be used exactly once.")
    return mapping


def build_team_member_rows(draft, season_label, seed_teams):
    quarter, year = parse_season_label(season_label)
    if not quarter or year is None:
        raise ValueError("Choose a valid season.")
    starting_month = season_starting_month(quarter)
    if starting_month is None:
        raise ValueError("Choose a valid season.")

    rows = []
    seen_player_ids = set()
    for seed in SEED_LABELS:
        seed_key = str(seed)
        season_team = seed_teams[seed_key]
        members = draft.get("teams", {}).get(seed_key) or []
        if not members:
            raise ValueError(f"Seed {seed} has no players to save.")
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("Draft teams are missing player details.")
            player_id = str(member.get("id") or "").strip()
            display_name = (member.get("display_name") or "").strip()
            if not player_id or not display_name:
                raise ValueError("Every drafted player needs an id and display name.")
            if player_id in seen_player_ids:
                raise ValueError(f"{display_name} appears on more than one team.")
            seen_player_ids.add(player_id)
            rows.append({
                "season_team": season_team,
                "player": display_name,
                "player_id": player_id,
                "season": season_label,
                "season_year": year,
                "season_starting_month": starting_month,
            })
    return rows


def team_members_exist_for_season(season_label):
    encoded = urllib.parse.quote(str(season_label), safe="")
    payload = supabase_request(
        f"team_members?select=id&season=eq.{encoded}&limit=1"
    )
    rows = parse_supabase_json(payload, empty=[])
    return isinstance(rows, list) and len(rows) > 0


def roster_form_error_message(exc):
    message = str(exc)
    if "RLS" in message or "row-level security" in message.lower():
        return (
            "Supabase blocked the write. Run supabase/team_members_admin_policies.sql "
            "in the SQL editor, then try again."
        )
    if "uq_team_members" in message.lower() or (
        "duplicate key" in message.lower() and "team_members" in message.lower()
    ):
        return (
            "That player is already on this season roster (unique on season + player_id). "
            "If you still see a name-based conflict, run "
            "supabase/team_members_player_id_unique.sql in the SQL editor."
        )
    if "team_members" in message.lower() and "not found" in message.lower():
        return "The team_members table is not set up yet."
    return message


def normalize_team_member_row(row):
    player = (row.get("player") or "").strip()
    season = (row.get("season") or "").strip()
    if not player or not season:
        return None
    season_team = (row.get("season_team") or "").strip()
    player_id = str(row.get("player_id") or "").strip() or None
    return {
        "id": row.get("id"),
        "season_team": season_team,
        "player": player,
        "player_id": player_id,
        "season": season,
        "season_year": row.get("season_year"),
        "season_starting_month": row.get("season_starting_month"),
        "created_at": row.get("created_at") or "",
    }


def load_team_members(season=None):
    order = "season_team.asc,player.asc"
    if season:
        encoded = urllib.parse.quote(str(season), safe="")
        payload = supabase_request(
            f"team_members?select={TEAM_MEMBERS_COLUMNS}"
            f"&season=eq.{encoded}&order={order}"
        )
        rows = parse_supabase_json(payload, empty=[])
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Supabase response.")
    else:
        rows = fetch_supabase_rows(
            "team_members",
            TEAM_MEMBERS_COLUMNS,
            order=f"season_year.desc,season_starting_month.desc,{order}",
        )

    members = []
    for row in rows:
        normalized = normalize_team_member_row(row)
        if normalized:
            members.append(normalized)
    return members


def group_roster_by_team(rows):
    groups = {team: [] for team in TEAM_NAMES}
    other = {}
    for row in rows:
        team = (row.get("season_team") or "").strip()
        if team in groups:
            groups[team].append(row)
        else:
            label = team or "—"
            other.setdefault(label, []).append(row)

    ordered = [(team, groups[team]) for team in TEAM_NAMES]
    for team in sorted(other.keys()):
        ordered.append((team, other[team]))
    return ordered


def pick_default_roster_season(seasons, rostered_seasons):
    if not seasons:
        return ""
    preferred = [
        row for row in seasons
        if (row.get("status") or "").strip().lower() in {"planned", "active"}
    ]
    for candidate in preferred + seasons:
        label = candidate.get("season") or ""
        if label and label in rostered_seasons:
            return label
    return seasons[0].get("season") or ""


def team_member_season_fields(season_label):
    quarter, year = parse_season_label(season_label)
    if not quarter or year is None:
        raise ValueError("Choose a valid season.")
    starting_month = season_starting_month(quarter)
    if starting_month is None:
        raise ValueError("Choose a valid season.")
    return year, starting_month


SEASON_COLUMNS = (
    "season,status,season_start_date,season_end_date,season_winner,season_runnerup,"
    "tournament_date,tournament_winner,tournament_runnerup,mip_award,notes,"
    "created_at,updated_at,season_page"
)
MEMBER_STATS_COLUMNS = (
    "player,total_games,total_wins,total_win_rates,total_seasons,"
    "season_titles,season_runnerups,tournament_titles,tournament_runnerups"
)
PLAYER_SEASON_COLUMNS = (
    "season,player,season_team,season_games,season_wins,season_win_rates,comments"
)
TEAM_MATCHUP_COLUMNS = (
    "season,team,comp_team,total_games,wins_by_team,team_win_rate,team_members"
)
TEAM_MOMENTS_COLUMNS = "id,caption,storage_path,original_filename,created_at"
PLAYERS_COLUMNS = "id,display_name,non_member,active,comments,created_at"
TEAM_MEMBERS_COLUMNS = (
    "id,season_team,player,player_id,season,season_year,"
    "season_starting_month,created_at"
)
GAME_RESULTS_COLUMNS = "id,game_number,away_team,home_team,winner_team,season,date"
RECENT_SUNDAY_LIMIT = 12
TEAM_MOMENTS_BUCKET = "team-moments"
PLAYER_STATUS_FILTERS = ("all", "active", "inactive", "non_member")
# Matches seasons_status_check in Supabase: planned | active | completed
SEASON_STATUSES = ("planned", "active", "completed")
SEASON_STATUS_FILTERS = ("all",) + SEASON_STATUSES
SEASON_QUARTERS = ("Jan-Mar", "Apr-Jun", "Jul-Sep", "Oct-Dec")
MAX_MOMENT_BYTES = 10 * 1024 * 1024
MAX_MOMENT_EDGE = 1920
MAX_MOMENT_CAPTION = 280
ALL_SEASONS_VALUE = "all"
TEAM_COLOR_CLASSES = {
    "bk": "team-bk",
    "ubrg": "team-bk",
    "ckd": "team-bk",
    "mmt": "team-bk",
    "karu": "team-bk",
    "kcn": "team-kcn",
    "zoo": "team-kcn",
    "nps": "team-nps",
    "nwo": "team-nps",
    "guest": "team-guest",
}
SEASON_LABEL_RE = re.compile(r"^([A-Za-z-]+)\s+(\d{4})$")
QUARTER_WEIGHT = {
    "Oct-Dec": 4,
    "Jul-Sep": 3,
    "Apr-Jun": 2,
    "Jan-Mar": 1,
}
QUARTER_STARTING_MONTH = {
    "Jan-Mar": 1,
    "Apr-Jun": 4,
    "Jul-Sep": 7,
    "Oct-Dec": 10,
}


def supabase_config():
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    api_key = os.environ.get("SUPABASE_API_KEY", "")
    if not supabase_url or not api_key:
        raise RuntimeError("Supabase is not configured.")
    return supabase_url, api_key


def supabase_http(url, method="GET", data=None, headers=None, timeout=15):
    request_headers = dict(headers or {})
    http_request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(
            http_request, timeout=timeout, context=ssl_context
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            if "team_moments" in body:
                raise RuntimeError("The Team Moments table is not set up yet.") from exc
            if "players" in body:
                raise RuntimeError("The players table is not set up yet.") from exc
            if "seasons" in body:
                raise RuntimeError("The seasons table is not set up yet.") from exc
            if "team_members" in body:
                raise RuntimeError("The team_members table is not set up yet.") from exc
            if "player_played_games" in body:
                raise RuntimeError("The player_played_games table is not set up yet.") from exc
            if "game_results" in body:
                raise RuntimeError("The game_results table is not set up yet.") from exc
            raise RuntimeError("Supabase table or file was not found.") from exc
        detail = ""
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                detail = (parsed.get("message") or parsed.get("error") or "").strip()
        except json.JSONDecodeError:
            detail = (body or "").strip()[:240]
        if detail:
            raise RuntimeError(f"Supabase request failed ({exc.code}): {detail}") from exc
        raise RuntimeError(f"Supabase request failed ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach Supabase.") from exc


def supabase_request(path, method="GET", body=None, extra_headers=None):
    supabase_url, api_key = supabase_config()
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    payload = supabase_http(
        f"{supabase_url}/rest/v1/{path}",
        method=method,
        data=data,
        headers=headers,
    )
    return payload.decode("utf-8")


def fetch_supabase_rows(table, columns, order=None):
    params = {"select": columns}
    if order:
        params["order"] = order

    payload = supabase_request(f"{table}?{urllib.parse.urlencode(params)}")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Unexpected Supabase response.") from exc

    if not isinstance(data, list):
        raise RuntimeError("Unexpected Supabase response.")
    return data


def call_supabase_rpc(function_name):
    supabase_request(f"rpc/{function_name}", method="POST", body={})


def parse_supabase_json(payload, empty=None):
    if not payload:
        return empty
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Unexpected Supabase response.") from exc


def insert_supabase_row(table, row):
    payload = supabase_request(
        table,
        method="POST",
        body=row,
        extra_headers={"Prefer": "return=representation"},
    )
    data = parse_supabase_json(payload)
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError("Unexpected Supabase response.")


def insert_supabase_rows(table, rows):
    if not rows:
        return []
    payload = supabase_request(
        table,
        method="POST",
        body=rows,
        extra_headers={"Prefer": "return=representation"},
    )
    data = parse_supabase_json(payload, empty=[])
    if isinstance(data, list):
        return data
    raise RuntimeError("Unexpected Supabase response.")


def update_supabase_row(table, row_id, patch):
    return update_supabase_row_by(table, "id", row_id, patch)


def update_supabase_row_by(table, column, value, patch):
    encoded_column = urllib.parse.quote(str(column), safe="")
    encoded_value = urllib.parse.quote(str(value), safe="")
    payload = supabase_request(
        f"{table}?{encoded_column}=eq.{encoded_value}",
        method="PATCH",
        body=patch,
        extra_headers={"Prefer": "return=representation"},
    )
    data = parse_supabase_json(payload, empty=[])
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        "No matching row was updated. Check Supabase RLS write policies for this table."
    )


def delete_supabase_row(table, row_id):
    return delete_supabase_row_by(table, "id", row_id)


def delete_supabase_row_by(table, column, value):
    encoded_column = urllib.parse.quote(str(column), safe="")
    encoded_value = urllib.parse.quote(str(value), safe="")
    payload = supabase_request(
        f"{table}?{encoded_column}=eq.{encoded_value}",
        method="DELETE",
        extra_headers={"Prefer": "return=representation"},
    )
    data = parse_supabase_json(payload, empty=[])
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        "No matching row was deleted. Check Supabase RLS write policies for this table."
    )


def storage_object_url(storage_path):
    supabase_url, _api_key = supabase_config()
    encoded = urllib.parse.quote(storage_path, safe="/")
    return f"{supabase_url}/storage/v1/object/{TEAM_MOMENTS_BUCKET}/{encoded}"


def public_moment_url(storage_path):
    supabase_url, _api_key = supabase_config()
    encoded = urllib.parse.quote(storage_path, safe="/")
    return f"{supabase_url}/storage/v1/object/public/{TEAM_MOMENTS_BUCKET}/{encoded}"


def upload_moment_object(storage_path, data, content_type):
    _supabase_url, api_key = supabase_config()
    supabase_http(
        storage_object_url(storage_path),
        method="POST",
        data=data,
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
            "x-upsert": "false",
        },
        timeout=45,
    )


def delete_moment_object(storage_path):
    _supabase_url, api_key = supabase_config()
    try:
        supabase_http(
            storage_object_url(storage_path),
            method="DELETE",
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
            },
        )
    except RuntimeError as exc:
        if "not found" not in str(exc).lower() and "(404)" not in str(exc):
            raise


def parse_season_label(label):
    if not label or not isinstance(label, str):
        return "", None
    match = SEASON_LABEL_RE.match(label.strip())
    if not match:
        return "", None
    return match.group(1), int(match.group(2))


def season_sort_key(row):
    quarter, year = parse_season_label(row.get("season") or "")
    year_key = -year if year is not None else 1
    quarter_key = -QUARTER_WEIGHT.get(quarter, -1)
    return (year_key, quarter_key)


def season_status_class(status):
    value = (status or "").strip().lower()
    if value == "completed" or "complete" in value or value in {"done", "finished"}:
        return "status-complete"
    if value == "active" or any(
        token in value for token in ("progress", "current", "ongoing")
    ):
        return "status-active"
    if value in {"planned", "upcoming"}:
        return "status-neutral"
    return "status-neutral"


def normalize_season_status(value):
    status = (value or "").strip().lower()
    # Accept older UI wording; DB check constraint uses planned.
    if status == "upcoming":
        status = "planned"
    if status not in SEASON_STATUSES:
        raise ValueError("Status must be planned, active, or completed.")
    return status


def season_page_url(value):
    if not value or not isinstance(value, str):
        return ""
    url = value.strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def parse_optional_date(value, field_label):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_label} must be a valid date.") from exc


def parse_optional_text(value):
    text = (value or "").strip()
    return text or None


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def compose_season_label(quarter, year):
    quarter = (quarter or "").strip()
    year_text = (year or "").strip()
    if quarter not in SEASON_QUARTERS:
        raise ValueError("Choose a valid season quarter.")
    try:
        year_value = int(year_text)
    except ValueError as exc:
        raise ValueError("Season year must be a 4-digit year.") from exc
    if year_value < 2000 or year_value > 2100:
        raise ValueError("Season year must be between 2000 and 2100.")
    return f"{quarter} {year_value}"


def load_season_records():
    rows = fetch_supabase_rows("seasons", SEASON_COLUMNS)
    rows.sort(key=season_sort_key)
    seasons = []
    for row in rows:
        season = (row.get("season") or "").strip()
        if not season:
            continue
        status = (row.get("status") or "").strip().lower()
        seasons.append({
            "season": season,
            "status": status,
            "status_label": status.title() if status else "",
            "season_start_date": (row.get("season_start_date") or "")[:10],
            "season_end_date": (row.get("season_end_date") or "")[:10],
            "season_winner": (row.get("season_winner") or "").strip(),
            "season_runnerup": (row.get("season_runnerup") or "").strip(),
            "tournament_date": (row.get("tournament_date") or "")[:10],
            "tournament_winner": (row.get("tournament_winner") or "").strip(),
            "tournament_runnerup": (row.get("tournament_runnerup") or "").strip(),
            "mip_award": (row.get("mip_award") or "").strip(),
            "notes": (row.get("notes") or "").strip(),
            "season_page": (row.get("season_page") or "").strip(),
            "season_page_url": season_page_url(row.get("season_page")),
            "status_class": season_status_class(status),
        })
    return seasons


def filter_seasons(seasons, status):
    if status in SEASON_STATUSES:
        return [row for row in seasons if row["status"] == status]
    return seasons


def season_payload_from_values(
    status,
    season_start_date,
    season_end_date,
    season_winner,
    season_runnerup,
    tournament_date,
    tournament_winner,
    tournament_runnerup,
    mip_award,
    notes,
    season_page,
):
    return {
        "status": status,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
        "season_winner": season_winner,
        "season_runnerup": season_runnerup,
        "tournament_date": tournament_date,
        "tournament_winner": tournament_winner,
        "tournament_runnerup": tournament_runnerup,
        "mip_award": mip_award,
        "notes": notes,
        "season_page": season_page,
    }


def parse_season_fields(form, prefix=""):
    if prefix:
        status = normalize_season_status(form.get(f"status[{prefix}]"))
        season_start_date = parse_optional_date(
            form.get(f"season_start_date[{prefix}]"), "Season start date"
        )
        season_end_date = parse_optional_date(
            form.get(f"season_end_date[{prefix}]"), "Season end date"
        )
        tournament_date = parse_optional_date(
            form.get(f"tournament_date[{prefix}]"), "Tournament date"
        )
        season_winner = parse_optional_text(form.get(f"season_winner[{prefix}]"))
        season_runnerup = parse_optional_text(form.get(f"season_runnerup[{prefix}]"))
        tournament_winner = parse_optional_text(form.get(f"tournament_winner[{prefix}]"))
        tournament_runnerup = parse_optional_text(
            form.get(f"tournament_runnerup[{prefix}]")
        )
        mip_award = parse_optional_text(form.get(f"mip_award[{prefix}]"))
        notes = parse_optional_text(form.get(f"notes[{prefix}]"))
        season_page = parse_optional_text(form.get(f"season_page[{prefix}]"))
    else:
        status = normalize_season_status(form.get("status"))
        season_start_date = parse_optional_date(
            form.get("season_start_date"), "Season start date"
        )
        season_end_date = parse_optional_date(
            form.get("season_end_date"), "Season end date"
        )
        tournament_date = parse_optional_date(
            form.get("tournament_date"), "Tournament date"
        )
        season_winner = parse_optional_text(form.get("season_winner"))
        season_runnerup = parse_optional_text(form.get("season_runnerup"))
        tournament_winner = parse_optional_text(form.get("tournament_winner"))
        tournament_runnerup = parse_optional_text(form.get("tournament_runnerup"))
        mip_award = parse_optional_text(form.get("mip_award"))
        notes = parse_optional_text(form.get("notes"))
        season_page = parse_optional_text(form.get("season_page"))

    return season_payload_from_values(
        status,
        season_start_date,
        season_end_date,
        season_winner,
        season_runnerup,
        tournament_date,
        tournament_winner,
        tournament_runnerup,
        mip_award,
        notes,
        season_page,
    )


def parse_new_season_form(form):
    season = compose_season_label(form.get("season_quarter"), form.get("season_year"))
    payload = parse_season_fields(form)
    now = utc_now_iso()
    payload["season"] = season
    payload["created_at"] = now
    payload["updated_at"] = now
    return payload


def parse_bulk_season_rows(form):
    rows = []
    for season in form.getlist("season_key"):
        season = (season or "").strip()
        if not season:
            continue
        quarter, year = parse_season_label(season)
        if not quarter or year is None:
            raise ValueError("One of the season labels is invalid.")
        payload = parse_season_fields(form, prefix=season)
        payload["season"] = season
        payload["updated_at"] = utc_now_iso()
        rows.append(payload)
    return rows


def season_form_error_message(exc):
    message = str(exc)
    if "(409)" in message:
        return "A season with that label already exists."
    if "seasons_status_check" in message:
        return "Status must be planned, active, or completed."
    if "RLS write policies" in message:
        return (
            "Supabase blocked the write. Run supabase/seasons_admin_policies.sql "
            "in the SQL editor, then try again."
        )
    if "seasons" in message.lower() and "not found" in message.lower():
        return "The seasons table is not set up yet."
    return message


def season_row_changed(current, payload):
    def norm_text(value):
        return (value or "").strip() or None

    def norm_date(value):
        text = (value or "").strip()
        return text[:10] if text else None

    return (
        current["status"] != payload["status"]
        or norm_date(current["season_start_date"]) != payload["season_start_date"]
        or norm_date(current["season_end_date"]) != payload["season_end_date"]
        or norm_text(current["season_winner"]) != payload["season_winner"]
        or norm_text(current["season_runnerup"]) != payload["season_runnerup"]
        or norm_date(current["tournament_date"]) != payload["tournament_date"]
        or norm_text(current["tournament_winner"]) != payload["tournament_winner"]
        or norm_text(current["tournament_runnerup"]) != payload["tournament_runnerup"]
        or norm_text(current["mip_award"]) != payload["mip_award"]
        or norm_text(current["notes"]) != payload["notes"]
        or norm_text(current["season_page"]) != payload["season_page"]
    )


def stat_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_win_rate(value):
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def format_fraction_win_rate(value):
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "—"
    if 0 <= rate <= 1:
        rate *= 100
    return f"{rate:.1f}%"


def load_member_stats():
    # The totals table is derived, so ask Supabase to rebuild it before reading.
    # A stale read is better than a failed page, so refresh errors are ignored.
    try:
        call_supabase_rpc("refresh_player_totals")
    except RuntimeError:
        pass

    rows = fetch_supabase_rows(
        "player_stats_total",
        MEMBER_STATS_COLUMNS,
        order="player.asc",
    )
    return [
        {
            "player": row.get("player") or "—",
            "total_games": stat_count(row.get("total_games")),
            "total_wins": stat_count(row.get("total_wins")),
            "win_rate": format_win_rate(row.get("total_win_rates")),
            "total_seasons": stat_count(row.get("total_seasons")),
            "season_titles": stat_count(row.get("season_titles")),
            "season_runnerups": stat_count(row.get("season_runnerups")),
            "tournament_titles": stat_count(row.get("tournament_titles")),
            "tournament_runnerups": stat_count(row.get("tournament_runnerups")),
        }
        for row in rows
    ]


def team_badge_class(team):
    value = (team or "").strip().lower()
    return TEAM_COLOR_CLASSES.get(value, "team-other")


def player_season_sort_key(row):
    team = row.get("season_team") or ""
    guest_key = 1 if team == "Guest" else 0
    return (guest_key, team.lower(), (row.get("player") or "").lower())


def load_player_season_stats():
    rows = fetch_supabase_rows("player_stats_by_season", PLAYER_SEASON_COLUMNS)
    players = []
    seasons = set()

    for row in rows:
        season = (row.get("season") or "").strip()
        if season:
            seasons.add(season)
        team = (row.get("season_team") or "").strip()
        players.append({
            "season": season,
            "player": row.get("player") or "—",
            "season_team": team or "—",
            "team_class": team_badge_class(team),
            "season_games": stat_count(row.get("season_games")),
            "season_wins": stat_count(row.get("season_wins")),
            "win_rate": format_win_rate(row.get("season_win_rates")),
            "comments": (row.get("comments") or "").strip(),
        })

    season_list = sorted(seasons, key=lambda label: season_sort_key({"season": label}))
    players.sort(key=lambda row: (*season_sort_key(row), *player_season_sort_key(row)))
    return season_list, players


def matchup_sort_key(row):
    team = row.get("team") or ""
    guest_key = 1 if team == "Guest" else 0
    return (guest_key, team.lower(), (row.get("comp_team") or "").lower())


def load_team_matchups():
    rows = fetch_supabase_rows("team_matchup_strength", TEAM_MATCHUP_COLUMNS)
    matchups = []
    seasons = set()

    for row in rows:
        season = (row.get("season") or "").strip()
        if season:
            seasons.add(season)
        team = (row.get("team") or "").strip()
        opponent = (row.get("comp_team") or "").strip()
        matchups.append({
            "season": season,
            "team": team or "—",
            "team_class": team_badge_class(team),
            "comp_team": opponent or "—",
            "comp_team_class": team_badge_class(opponent),
            "total_games": stat_count(row.get("total_games")),
            "wins_by_team": stat_count(row.get("wins_by_team")),
            "win_rate": format_fraction_win_rate(row.get("team_win_rate")),
            "team_members": (row.get("team_members") or "").strip(),
        })

    season_list = sorted(seasons, key=lambda label: season_sort_key({"season": label}))
    matchups.sort(key=lambda row: (*season_sort_key(row), *matchup_sort_key(row)))
    return season_list, matchups


def format_moment_date(value):
    if not value:
        return ""
    text = str(value).replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    return stamp.strftime("%B %d, %Y").replace(" 0", " ")


def prepare_moment_image(file_storage):
    filename = (file_storage.filename or "").strip()
    if not filename:
        raise ValueError("Please choose at least one photo.")

    raw = file_storage.read()
    if not raw:
        raise ValueError(f"{filename} is empty.")
    if len(raw) > MAX_MOMENT_BYTES:
        raise ValueError(f"{filename} is larger than 10MB.")

    suffix = os.path.splitext(filename)[1].lower()
    jpeg_formats = {"JPEG", "JPG", "MPO"}
    jpeg_suffixes = {".jpg", ".jpeg", ".jpe"}

    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            format_name = (source.format or "").upper()
            save_as_jpeg = format_name in jpeg_formats or suffix in jpeg_suffixes
            if format_name not in {"JPEG", "JPG", "MPO", "PNG", "WEBP", "GIF"} and not save_as_jpeg:
                raise ValueError(f"{filename} must be a JPEG, PNG, WEBP, or GIF.")
            if format_name == "GIF" and getattr(source, "is_animated", False) and not save_as_jpeg:
                return raw, "image/gif", ".gif"

            image = ImageOps.exif_transpose(source)
            if max(image.size) > MAX_MOMENT_EDGE:
                image.thumbnail((MAX_MOMENT_EDGE, MAX_MOMENT_EDGE), Image.Resampling.LANCZOS)

            output = BytesIO()
            if save_as_jpeg:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                try:
                    image.save(output, format="JPEG", quality=88, optimize=True)
                except OSError:
                    output.seek(0)
                    output.truncate(0)
                    image.save(output, format="JPEG", quality=88)
                return output.getvalue(), "image/jpeg", ".jpg"
            if format_name == "PNG":
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="PNG", optimize=True)
                return output.getvalue(), "image/png", ".png"
            if format_name == "WEBP":
                image.save(output, format="WEBP", quality=85, method=6)
                return output.getvalue(), "image/webp", ".webp"
            image.save(output, format="GIF")
            return output.getvalue(), "image/gif", ".gif"
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"{filename} is not a valid image.") from exc


def load_players():
    rows = fetch_supabase_rows(
        "players",
        PLAYERS_COLUMNS,
        order="display_name.asc",
    )
    players = []
    for row in rows:
        display_name = (row.get("display_name") or "").strip()
        if not display_name:
            continue
        comments = (row.get("comments") or "").strip()
        players.append({
            "id": row.get("id") or "",
            "display_name": display_name,
            "non_member": bool(row.get("non_member")),
            "active": bool(row.get("active")),
            "comments": comments,
        })
    return players


def load_draft_players():
    """Active league members (non_member = false) for the draft pool."""
    try:
        players = load_players()
    except Exception:
        return []
    return [
        {
            "id": player["id"],
            "display_name": player["display_name"],
            "comments": player.get("comments") or "",
        }
        for player in players
        if player["active"] and not player["non_member"] and player.get("id")
    ]


def parse_player_form(form):
    display_name = (form.get("display_name") or "").strip()
    non_member = form.get("non_member") in ("on", "1", "true")
    active = form.get("active") in ("on", "1", "true")
    comments = (form.get("comments") or "").strip() or None
    return display_name, non_member, active, comments


def parse_bulk_player_rows(form):
    rows = []
    for player_id in form.getlist("player_id"):
        player_id = (player_id or "").strip()
        if not player_id:
            continue
        try:
            UUID(str(player_id))
        except ValueError as exc:
            raise ValueError("One of the players could not be found.") from exc

        display_name = (form.get(f"display_name[{player_id}]") or "").strip()
        if not display_name:
            raise ValueError("Every player needs a display name.")

        non_member = form.get(f"non_member[{player_id}]") in ("on", "1", "true")
        active = form.get(f"active[{player_id}]") in ("on", "1", "true")
        comments = (form.get(f"comments[{player_id}]") or "").strip() or None
        rows.append({
            "id": player_id,
            "display_name": display_name,
            "non_member": non_member,
            "active": active,
            "comments": comments,
        })
    return rows


def filter_players(players, status):
    if status == "active":
        return [player for player in players if player["active"]]
    if status == "inactive":
        return [player for player in players if not player["active"]]
    if status == "non_member":
        return [player for player in players if player["non_member"]]
    return players


def player_form_error_message(exc):
    message = str(exc)
    if "players" in message.lower() and "not found" in message.lower():
        return "The players table is not set up yet."
    return message


def load_team_moments():
    rows = fetch_supabase_rows(
        "team_moments",
        TEAM_MOMENTS_COLUMNS,
        order="created_at.desc",
    )
    moments = []
    for row in rows:
        storage_path = (row.get("storage_path") or "").strip()
        if not storage_path:
            continue
        moments.append({
            "id": row.get("id") or "",
            "caption": (row.get("caption") or "").strip(),
            "storage_path": storage_path,
            "original_filename": (row.get("original_filename") or "").strip(),
            "image_url": public_moment_url(storage_path),
            "created_label": format_moment_date(row.get("created_at")),
        })
    return moments


def fetch_moment_by_id(moment_id):
    encoded = urllib.parse.quote(str(moment_id), safe="")
    payload = supabase_request(
        f"team_moments?id=eq.{encoded}&select={TEAM_MOMENTS_COLUMNS}"
    )
    rows = parse_supabase_json(payload, empty=[])
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected Supabase response.")
    return rows[0] if rows else None


@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /draft\n"
        "\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in PUBLIC_SITEMAP_PATHS:
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_URL}{path}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response("\n".join(lines) + "\n", mimetype="application/xml")


@app.route("/")
def landing():
    return render_template("public/landing.html", active="landing")


@app.route("/home")
def home():
    return render_template("public/home.html", active="home")


@app.route("/ko")
def korean_landing():
    return render_template("public/ko.html", active="landing")


@app.route("/about")
def about():
    return render_template("public/about.html", active="about")


@app.route("/rules")
def league_rules():
    return render_template("public/rules.html", active="rules")


@app.route("/season-results")
def season_results():
    load_error = None
    seasons = []
    try:
        seasons = load_season_records()
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "public/season_results.html",
        active="season-results",
        seasons=seasons,
        load_error=load_error,
    )


@app.route("/member-stats")
def member_stats():
    load_error = None
    players = []
    try:
        players = load_member_stats()
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "public/member_stats.html",
        active="member-stats",
        players=players,
        load_error=load_error,
    )


@app.route("/player-stats")
def player_stats():
    load_error = None
    seasons = []
    players = []
    selected_season = (request.args.get("season") or "").strip()

    try:
        seasons, all_players = load_player_season_stats()
        if seasons:
            if selected_season not in seasons:
                selected_season = seasons[0]
            players = [row for row in all_players if row["season"] == selected_season]
        else:
            selected_season = ""
    except RuntimeError as exc:
        load_error = str(exc)
        selected_season = ""

    return render_template(
        "public/player_stats.html",
        active="player-stats",
        seasons=seasons,
        selected_season=selected_season,
        players=players,
        load_error=load_error,
    )


@app.route("/team-moments")
def team_moments():
    load_error = None
    moments = []
    try:
        moments = load_team_moments()
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "public/team_moments.html",
        active="team-moments",
        moments=moments,
        load_error=load_error,
    )


@app.route("/team-matchups")
def team_matchups():
    load_error = None
    seasons = []
    matchups = []
    selected_season = (request.args.get("season") or "").strip()
    show_all = False

    try:
        seasons, all_matchups = load_team_matchups()
        if seasons:
            show_all = selected_season == ALL_SEASONS_VALUE
            if show_all:
                selected_season = ALL_SEASONS_VALUE
                matchups = all_matchups
            else:
                if selected_season not in seasons:
                    selected_season = seasons[0]
                matchups = [row for row in all_matchups if row["season"] == selected_season]
        else:
            selected_season = ""
    except RuntimeError as exc:
        load_error = str(exc)
        selected_season = ""

    return render_template(
        "public/team_matchups.html",
        active="team-matchups",
        seasons=seasons,
        selected_season=selected_season,
        show_all=show_all,
        matchups=matchups,
        load_error=load_error,
    )


@app.route("/draft")
def draft_room():
    return redirect(url_for("admin_draft"))


@app.route("/admin/draft")
def admin_draft():
    draft_players = load_draft_players()
    draft_seasons = load_draft_season_options()
    return render_template(
        "admin/draft.html",
        active="draft",
        draft_players=draft_players,
        draft_seasons=draft_seasons,
    )


@app.route("/admin")
def admin_dashboard():
    return render_template(
        "admin/in_progress.html",
        active="dashboard",
        page_title="Dashboard",
        page_summary="Overview of what captains and admins will manage for each season.",
        future_job=(
            "Season status, recent unsynced work, and shortcuts to roster, "
            "games, and tournament entry."
        ),
    )


@app.route("/admin/players", methods=["GET", "POST"])
def admin_players():
    status = (request.args.get("status") or "all").strip().lower()
    if status not in PLAYER_STATUS_FILTERS:
        status = "all"

    if request.method == "POST":
        display_name, non_member, active, comments = parse_player_form(request.form)
        if not display_name:
            flash("Display name is required.", "error")
            return redirect(url_for("admin_players", status=status))

        try:
            insert_supabase_row(
                "players",
                {
                    "display_name": display_name,
                    "non_member": non_member,
                    "active": active,
                    "comments": comments,
                },
            )
        except RuntimeError as exc:
            flash(player_form_error_message(exc), "error")
            return redirect(url_for("admin_players", status=status))

        flash(f"Added {display_name}.", "success")
        return redirect(url_for("admin_players", status=status))

    load_error = None
    players = []
    try:
        players = filter_players(load_players(), status)
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "admin/players.html",
        active="players",
        players=players,
        load_error=load_error,
        status=status,
        status_filters=PLAYER_STATUS_FILTERS,
    )


@app.route("/admin/players/bulk-update", methods=["POST"])
def admin_bulk_update_players():
    status = (request.args.get("status") or request.form.get("status") or "all")
    status = status.strip().lower()
    if status not in PLAYER_STATUS_FILTERS:
        status = "all"

    try:
        rows = parse_bulk_player_rows(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_players", status=status))

    if not rows:
        flash("No players to update.", "error")
        return redirect(url_for("admin_players", status=status))

    try:
        current_by_id = {player["id"]: player for player in load_players()}
        updated_count = 0
        for row in rows:
            current = current_by_id.get(row["id"])
            if not current:
                flash("That player could not be found.", "error")
                return redirect(url_for("admin_players", status=status))

            current_comments = current["comments"] or None
            if (
                current["display_name"] == row["display_name"]
                and current["non_member"] == row["non_member"]
                and current["active"] == row["active"]
                and current_comments == row["comments"]
            ):
                continue

            updated = update_supabase_row(
                "players",
                row["id"],
                {
                    "display_name": row["display_name"],
                    "non_member": row["non_member"],
                    "active": row["active"],
                    "comments": row["comments"],
                },
            )
            if not updated:
                flash("That player could not be found.", "error")
                return redirect(url_for("admin_players", status=status))
            updated_count += 1
    except RuntimeError as exc:
        flash(player_form_error_message(exc), "error")
        return redirect(url_for("admin_players", status=status))

    if updated_count:
        flash(
            f"Updated {updated_count} player{'s' if updated_count != 1 else ''}.",
            "success",
        )
    else:
        flash("No changes to save.", "success")
    return redirect(url_for("admin_players", status=status))


@app.route("/admin/seasons", methods=["GET", "POST"])
def admin_seasons():
    status = (request.args.get("status") or "all").strip().lower()
    if status not in SEASON_STATUS_FILTERS:
        status = "all"

    if request.method == "POST":
        try:
            payload = parse_new_season_form(request.form)
            insert_supabase_row("seasons", payload)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_seasons", status=status))
        except RuntimeError as exc:
            flash(season_form_error_message(exc), "error")
            return redirect(url_for("admin_seasons", status=status))

        flash(f"Added {payload['season']}.", "success")
        return redirect(url_for("admin_seasons", status=status))

    load_error = None
    seasons = []
    try:
        seasons = filter_seasons(load_season_records(), status)
    except RuntimeError as exc:
        load_error = str(exc)

    current_year = datetime.now(timezone.utc).year
    return render_template(
        "admin/seasons.html",
        active="seasons",
        seasons=seasons,
        load_error=load_error,
        status=status,
        status_filters=SEASON_STATUS_FILTERS,
        season_statuses=SEASON_STATUSES,
        season_quarters=SEASON_QUARTERS,
        default_year=current_year,
    )


@app.route("/admin/seasons/bulk-update", methods=["POST"])
def admin_bulk_update_seasons():
    status = (request.args.get("status") or request.form.get("status") or "all")
    status = status.strip().lower()
    if status not in SEASON_STATUS_FILTERS:
        status = "all"

    try:
        rows = parse_bulk_season_rows(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_seasons", status=status))

    if not rows:
        flash("No seasons to update.", "error")
        return redirect(url_for("admin_seasons", status=status))

    try:
        current_by_season = {
            row["season"]: row for row in load_season_records()
        }
        updated_count = 0
        for row in rows:
            current = current_by_season.get(row["season"])
            if not current:
                flash("That season could not be found.", "error")
                return redirect(url_for("admin_seasons", status=status))

            if not season_row_changed(current, row):
                continue

            patch = {
                key: value
                for key, value in row.items()
                if key != "season"
            }
            updated = update_supabase_row_by("seasons", "season", row["season"], patch)
            if not updated:
                flash("That season could not be found.", "error")
                return redirect(url_for("admin_seasons", status=status))
            updated_count += 1
    except RuntimeError as exc:
        flash(season_form_error_message(exc), "error")
        return redirect(url_for("admin_seasons", status=status))

    if updated_count:
        flash(
            f"Updated {updated_count} season{'s' if updated_count != 1 else ''}.",
            "success",
        )
    else:
        flash("No changes to save.", "success")
    return redirect(url_for("admin_seasons", status=status))


@app.route("/admin/seasons/delete", methods=["POST"])
def admin_delete_season():
    status = (request.args.get("status") or request.form.get("status") or "all")
    status = status.strip().lower()
    if status not in SEASON_STATUS_FILTERS:
        status = "all"

    season = (request.form.get("season") or "").strip()
    confirm_season = (request.form.get("confirm_season") or "").strip()
    if not season:
        flash("Season label is required to delete.", "error")
        return redirect(url_for("admin_seasons", status=status))
    if confirm_season != season:
        flash("Delete cancelled. Type the season label exactly to confirm.", "error")
        return redirect(url_for("admin_seasons", status=status))

    try:
        delete_supabase_row_by("seasons", "season", season)
    except RuntimeError as exc:
        flash(season_form_error_message(exc), "error")
        return redirect(url_for("admin_seasons", status=status))

    flash(f"Deleted {season}.", "success")
    return redirect(url_for("admin_seasons", status=status))


@app.route("/admin/roster")
def admin_roster():
    load_error = None
    seasons = []
    members = []
    available_players = []
    season = (request.args.get("season") or "").strip()

    try:
        seasons = load_season_records()
        known_seasons = {row["season"] for row in seasons}
        if season and season not in known_seasons:
            flash("That season is not in the seasons list.", "error")
            season = ""

        if not season:
            all_members = load_team_members()
            rostered_seasons = {row["season"] for row in all_members}
            season = pick_default_roster_season(seasons, rostered_seasons)

        if season:
            members = load_team_members(season)
            rostered_player_ids = {
                row["player_id"] for row in members if row.get("player_id")
            }
            rostered_names = {
                (row["player"] or "").strip().lower() for row in members
            }
            players = load_players()
            available_players = [
                player
                for player in players
                if player.get("id")
                and player["id"] not in rostered_player_ids
                and player["display_name"].strip().lower() not in rostered_names
            ]
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "admin/roster.html",
        active="roster",
        seasons=seasons,
        season=season,
        members=members,
        roster_groups=group_roster_by_team(members),
        team_names=TEAM_NAMES,
        available_players=available_players,
        load_error=load_error,
        member_count=len(members),
    )


@app.route("/admin/roster/update-team", methods=["POST"])
def admin_roster_update_team():
    season = (request.form.get("season") or "").strip()
    member_id = (request.form.get("member_id") or "").strip()
    season_team = (request.form.get("season_team") or "").strip().upper()

    if not member_id:
        flash("Roster member is required.", "error")
        return redirect(url_for("admin_roster", season=season or None))
    if season_team not in TEAM_NAMES:
        flash("Team must be NPS, KCN, or BK.", "error")
        return redirect(url_for("admin_roster", season=season or None))

    try:
        updated = update_supabase_row(
            "team_members",
            member_id,
            {"season_team": season_team},
        )
        if not updated:
            flash("That roster member could not be found.", "error")
            return redirect(url_for("admin_roster", season=season or None))
        player_name = (updated.get("player") or "Player").strip() or "Player"
        flash(f"Moved {player_name} to {season_team}.", "success")
    except RuntimeError as exc:
        flash(roster_form_error_message(exc), "error")

    return redirect(url_for("admin_roster", season=season or None))


@app.route("/admin/roster/remove", methods=["POST"])
def admin_roster_remove():
    season = (request.form.get("season") or "").strip()
    member_id = (request.form.get("member_id") or "").strip()

    if not member_id:
        flash("Roster member is required.", "error")
        return redirect(url_for("admin_roster", season=season or None))

    try:
        deleted = delete_supabase_row("team_members", member_id)
        player_name = ""
        if isinstance(deleted, dict):
            player_name = (deleted.get("player") or "").strip()
        flash(
            f"Removed {player_name or 'player'} from the roster.",
            "success",
        )
    except RuntimeError as exc:
        flash(roster_form_error_message(exc), "error")

    return redirect(url_for("admin_roster", season=season or None))


@app.route("/admin/roster/add", methods=["POST"])
def admin_roster_add():
    season = (request.form.get("season") or "").strip()
    player_id = (request.form.get("player_id") or "").strip()
    season_team = (request.form.get("season_team") or "").strip().upper()

    if not season:
        flash("Season is required.", "error")
        return redirect(url_for("admin_roster"))
    if season_team not in TEAM_NAMES:
        flash("Team must be NPS, KCN, or BK.", "error")
        return redirect(url_for("admin_roster", season=season))
    if not player_id:
        flash("Choose a player to add.", "error")
        return redirect(url_for("admin_roster", season=season))

    try:
        UUID(str(player_id))
    except ValueError:
        flash("That player could not be found.", "error")
        return redirect(url_for("admin_roster", season=season))

    try:
        known_seasons = {row["season"] for row in load_season_records()}
        if season not in known_seasons:
            flash("That season is not in the seasons list.", "error")
            return redirect(url_for("admin_roster"))

        players_by_id = {player["id"]: player for player in load_players()}
        player = players_by_id.get(player_id)
        if not player:
            flash("That player could not be found.", "error")
            return redirect(url_for("admin_roster", season=season))

        existing = load_team_members(season)
        if any(row.get("player_id") == player_id for row in existing):
            flash(f"{player['display_name']} is already on this season roster.", "error")
            return redirect(url_for("admin_roster", season=season))

        year, starting_month = team_member_season_fields(season)
        insert_supabase_row(
            "team_members",
            {
                "season_team": season_team,
                "player": player["display_name"],
                "player_id": player_id,
                "season": season,
                "season_year": year,
                "season_starting_month": starting_month,
            },
        )
        flash(f"Added {player['display_name']} to {season_team}.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except RuntimeError as exc:
        flash(roster_form_error_message(exc), "error")

    return redirect(url_for("admin_roster", season=season))


@app.route("/admin/roster/clear", methods=["POST"])
def admin_roster_clear():
    season = (request.form.get("season") or "").strip()
    confirm_season = (request.form.get("confirm_season") or "").strip()

    if not season:
        flash("Season is required to clear the roster.", "error")
        return redirect(url_for("admin_roster"))
    if confirm_season != season:
        flash("Clear cancelled. Type the season label exactly to confirm.", "error")
        return redirect(url_for("admin_roster", season=season))

    try:
        if not team_members_exist_for_season(season):
            flash(f"No roster rows to clear for {season}.", "success")
            return redirect(url_for("admin_roster", season=season))

        delete_supabase_row_by("team_members", "season", season)
        flash(
            f"Cleared the roster for {season}. Draft Room can save to this season again.",
            "success",
        )
    except RuntimeError as exc:
        flash(roster_form_error_message(exc), "error")

    return redirect(url_for("admin_roster", season=season))


def canonical_player_id(value):
    try:
        return str(UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError):
        return ""


def default_game_date(value=None):
    text = (value or "").strip()
    if text:
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        except ValueError:
            pass
    today = datetime.now().date()
    days_since_sunday = (today.weekday() + 1) % 7
    return (today - timedelta(days=days_since_sunday)).isoformat()


def pick_default_games_season(seasons):
    for status in ("active", "planned"):
        for row in seasons:
            if (row.get("status") or "").strip().lower() == status and row.get("season"):
                return row["season"]
    for row in seasons:
        if row.get("season"):
            return row["season"]
    return ""


def sunday_rotation_from_first(away, home):
    """Games 2–3 follow game 1: the sitting team is away next, and the previous away team is home next. Games 4–6 repeat 1–3."""
    if away not in TEAM_NAMES or home not in TEAM_NAMES or away == home:
        raise ValueError("Game 1 needs two different teams.")
    games = []
    for _ in range(3):
        games.append((away, home))
        sitter = next(team for team in TEAM_NAMES if team not in (away, home))
        away, home = sitter, away
    return tuple(games * 2)


def games_player_label(player):
    name = (player.get("display_name") or "").strip()
    comments = (player.get("comments") or "").strip()
    return {
        "id": canonical_player_id(player.get("id")),
        "name": name,
        "non_member": bool(player.get("non_member")),
        "comments": comments,
    }


def games_roster_and_guests(members, players):
    labeled = []
    by_id = {}
    by_name = {}
    for player in players:
        entry = games_player_label(player)
        if not entry["id"] or not entry["name"]:
            continue
        labeled.append(entry)
        by_id[entry["id"]] = player
        by_name.setdefault(entry["name"].strip().lower(), entry["id"])

    roster = []
    roster_ids = set()
    roster_team_by_id = {}
    for member in members:
        team = (member.get("season_team") or "").strip().upper()
        if team not in TEAM_NAMES:
            continue
        player_id = canonical_player_id(member.get("player_id"))
        if not player_id:
            player_id = by_name.get((member.get("player") or "").strip().lower(), "")
        if not player_id or player_id not in by_id or player_id in roster_ids:
            continue
        roster_ids.add(player_id)
        roster_team_by_id[player_id] = team
        entry = games_player_label(by_id[player_id])
        entry["team"] = team
        roster.append(entry)

    roster.sort(key=lambda row: (row["team"], row["name"].lower()))
    guests = []
    for entry in labeled:
        if entry["id"] in roster_ids:
            continue
        guests.append(entry)
    guests.sort(key=lambda row: row["name"].lower())
    return roster, guests, by_id, roster_team_by_id


def load_season_game_results(season):
    encoded = urllib.parse.quote(str(season), safe="")
    payload = supabase_request(
        "game_results?select="
        f"{GAME_RESULTS_COLUMNS}&season=eq.{encoded}&order=date.desc,game_number.asc"
    )
    rows = parse_supabase_json(payload, empty=[])
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected Supabase response.")
    return rows


def group_recent_sundays(rows, limit=RECENT_SUNDAY_LIMIT):
    grouped = {}
    order = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        if day not in grouped:
            if len(order) >= limit:
                continue
            grouped[day] = []
            order.append(day)
        grouped[day].append({
            "game_number": stat_count(row.get("game_number")),
            "away_team": (row.get("away_team") or "").strip(),
            "home_team": (row.get("home_team") or "").strip(),
            "winner_team": (row.get("winner_team") or "").strip(),
        })
    sundays = []
    for day in order:
        games = sorted(grouped[day], key=lambda item: item["game_number"])
        sundays.append({"date": day, "games": games})
    return sundays


def games_exist_for_date(season, day):
    encoded_season = urllib.parse.quote(str(season), safe="")
    start = urllib.parse.quote(f"{day}T00:00:00+00:00", safe="")
    next_day = (datetime.strptime(day, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    end = urllib.parse.quote(f"{next_day}T00:00:00+00:00", safe="")
    payload = supabase_request(
        "game_results?select=id"
        f"&season=eq.{encoded_season}&date=gte.{start}&date=lt.{end}&limit=1"
    )
    rows = parse_supabase_json(payload, empty=[])
    return isinstance(rows, list) and len(rows) > 0


def parse_sunday_games_form(form, players_by_id, roster_team_by_id):
    season = (form.get("season") or "").strip()
    quarter, year = parse_season_label(season)
    if not quarter or year is None:
        raise ValueError("Choose a valid season.")
    day = (form.get("date") or "").strip()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Choose a valid game date.") from exc

    try:
        payload = json.loads(form.get("payload") or "")
    except json.JSONDecodeError as exc:
        raise ValueError("The Sunday form was incomplete. Reload the page and try again.") from exc
    games = payload.get("games") if isinstance(payload, dict) else None
    if not isinstance(games, list) or len(games) != 6:
        raise ValueError("A Sunday needs all six games.")

    def game_sort_key(game):
        try:
            return int(game.get("game_number"))
        except (TypeError, ValueError, AttributeError):
            return 0

    ordered = sorted(games, key=game_sort_key)
    normalized = []
    for expected, game in enumerate(ordered, start=1):
        if not isinstance(game, dict):
            raise ValueError(f"Game {expected} is incomplete.")
        try:
            number = int(game.get("game_number"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Game {expected} is incomplete.") from exc
        if number != expected:
            raise ValueError("Games must be numbered 1 through 6.")
        away = str(game.get("away_team") or "").strip().upper()
        home = str(game.get("home_team") or "").strip().upper()
        winner = str(game.get("winner_team") or "").strip().upper()
        if away not in TEAM_NAMES or home not in TEAM_NAMES or away == home:
            raise ValueError(f"Game {expected} needs two different teams.")
        if winner not in {away, home}:
            raise ValueError(f"Pick a winner for game {expected}.")
        lineup_rows = game.get("players")
        if not isinstance(lineup_rows, list):
            raise ValueError(f"Game {expected} is missing a lineup.")

        seen = set()
        lineup = []
        counts = {away: 0, home: 0}
        for entry in lineup_rows:
            if not isinstance(entry, dict):
                raise ValueError(f"Game {expected} has an invalid lineup.")
            player_id = canonical_player_id(entry.get("player_id"))
            if not player_id or player_id not in players_by_id:
                raise ValueError(f"Game {expected} has a player who is not in the players list.")
            playing_team = str(entry.get("playing_team") or "").strip().upper()
            if playing_team not in {away, home}:
                raise ValueError(
                    f"Game {expected} has a player on a team that is not playing."
                )
            if player_id in seen:
                raise ValueError(f"Game {expected} lists a player twice.")
            seen.add(player_id)
            counts[playing_team] += 1
            player = players_by_id[player_id]
            lineup.append({
                "name": (player.get("display_name") or "").strip(),
                "playing_team": playing_team,
                "season": season,
                "guest": roster_team_by_id.get(player_id) != playing_team,
                "player_id": player_id,
            })
        if counts[away] < 1 or counts[home] < 1:
            raise ValueError(f"Game {expected} needs at least one player on each team.")
        normalized.append({
            "game_number": number,
            "away_team": away,
            "home_team": home,
            "winner_team": winner,
            "season": season,
            "date": f"{day}T00:00:00+00:00",
            "lineup": lineup,
        })

    matchups = tuple((game["away_team"], game["home_team"]) for game in normalized)
    expected = sunday_rotation_from_first(
        normalized[0]["away_team"], normalized[0]["home_team"]
    )
    if matchups != expected:
        raise ValueError("Games 2–6 must follow from game 1.")
    return season, day, normalized


def created_at_missing(exc):
    message = str(exc).lower()
    return "created_at" in message and "null" in message


def delete_sunday_games(game_ids):
    ids = []
    for game_id in game_ids:
        try:
            ids.append(str(int(game_id)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return
    id_filter = ",".join(ids)
    for table, column in (("player_played_games", "game_id"), ("game_results", "id")):
        try:
            supabase_request(
                f"{table}?{column}=in.({id_filter})",
                method="DELETE",
                extra_headers={"Prefer": "return=minimal"},
            )
        except RuntimeError:
            pass


def insert_game_result_row(game, created_at=None):
    row = {
        "game_number": game["game_number"],
        "away_team": game["away_team"],
        "home_team": game["home_team"],
        "winner_team": game["winner_team"],
        "season": game["season"],
        "date": game["date"],
    }
    if created_at:
        row["created_at"] = created_at
    return insert_supabase_row("game_results", row)


def save_sunday_games(games):
    created_at = None
    inserted_ids = []
    try:
        for game in games:
            try:
                saved = insert_game_result_row(game, created_at)
            except RuntimeError as exc:
                if created_at or inserted_ids or not created_at_missing(exc):
                    raise
                created_at = utc_now_iso()
                saved = insert_game_result_row(game, created_at)
            game_id = saved.get("id")
            if game_id is None:
                raise RuntimeError("Supabase did not return a game id.")
            game["id"] = game_id
            inserted_ids.append(game_id)

        player_rows = []
        for game in games:
            for player in game["lineup"]:
                player_row = {
                    "name": player["name"],
                    "playing_team": player["playing_team"],
                    "season": player["season"],
                    "game_id": game["id"],
                    "guest": player["guest"],
                    "player_id": player["player_id"],
                }
                if created_at:
                    player_row["created_at"] = created_at
                player_rows.append(player_row)
        try:
            insert_supabase_rows("player_played_games", player_rows)
        except RuntimeError as exc:
            if created_at or not created_at_missing(exc):
                raise
            created_at = utc_now_iso()
            for player_row in player_rows:
                player_row["created_at"] = created_at
            insert_supabase_rows("player_played_games", player_rows)
    except Exception:
        delete_sunday_games(inserted_ids)
        raise

    refresh_error = None
    try:
        call_supabase_rpc("refresh_all_stats")
    except RuntimeError as exc:
        refresh_error = exc
    return len(player_rows), refresh_error


def games_form_error_message(exc):
    message = str(exc)
    lowered = message.lower()
    if "row-level security" in lowered or "rls" in message:
        return (
            "Supabase blocked the write. Run supabase/games_admin_policies.sql "
            "in the SQL editor, then try again."
        )
    if "player_played_games" in lowered and "not found" in lowered:
        return "The player_played_games table is not set up yet."
    if "game_results" in lowered and "not found" in lowered:
        return "The game_results table is not set up yet."
    return message


def load_games_page(season, day):
    seasons = load_season_records()
    known = {row["season"] for row in seasons}
    if season not in known:
        season = ""
    if not season:
        season = pick_default_games_season(seasons)
    day = default_game_date(day)
    roster = []
    guests = []
    recent = []
    if season:
        members = load_team_members(season)
        players = load_players()
        roster, guests, _by_id, _roster_teams = games_roster_and_guests(members, players)
        recent = group_recent_sundays(load_season_game_results(season))
    return {
        "seasons": seasons,
        "season": season,
        "game_date": day,
        "roster": roster,
        "guests": guests,
        "recent_sundays": recent,
    }


def render_games_page(season, day, posted_payload=None, load_error=None):
    page = {
        "seasons": [],
        "season": season or "",
        "game_date": default_game_date(day),
        "roster": [],
        "guests": [],
        "recent_sundays": [],
    }
    if load_error is None:
        try:
            page = load_games_page(season, day)
        except RuntimeError as exc:
            load_error = str(exc)

    initial_payload = None
    if posted_payload:
        try:
            parsed = json.loads(posted_payload)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            initial_payload = parsed

    return render_template(
        "admin/games.html",
        active="games",
        seasons=page["seasons"],
        season=page["season"],
        game_date=page["game_date"],
        roster_players=page["roster"],
        guest_players=page["guests"],
        recent_sundays=page["recent_sundays"],
        team_names=TEAM_NAMES,
        load_error=load_error,
        initial_payload=initial_payload,
    )


@app.route("/admin/games", methods=["GET", "POST"])
def admin_games():
    if request.method == "POST":
        season = (request.form.get("season") or "").strip()
        day = (request.form.get("date") or "").strip()
        posted_payload = request.form.get("payload") or ""
        try:
            seasons = load_season_records()
            if season not in {row["season"] for row in seasons}:
                raise ValueError("That season is not in the seasons list.")
            members = load_team_members(season)
            players = load_players()
            _roster, _guests, players_by_id, roster_team_by_id = games_roster_and_guests(
                members, players
            )
            season, day, games = parse_sunday_games_form(
                request.form, players_by_id, roster_team_by_id
            )
            if games_exist_for_date(season, day):
                raise ValueError(
                    f"Games for {season} on {day} are already saved."
                )
            player_count, refresh_error = save_sunday_games(games)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_games_page(season, day, posted_payload)
        except RuntimeError as exc:
            flash(games_form_error_message(exc), "error")
            return render_games_page(season, day, posted_payload)

        flash(
            f"Saved {day}: 6 games, {player_count} played-game rows.",
            "success",
        )
        if refresh_error:
            flash(
                "Games were saved, but stats were not rebuilt. "
                "Run refresh_all_stats in Supabase.",
                "error",
            )
        return redirect(url_for("admin_games", season=season, date=day))

    return render_games_page(
        (request.args.get("season") or "").strip(),
        (request.args.get("date") or "").strip(),
    )


@app.route("/admin/moments", methods=["GET", "POST"])
def admin_moments():
    if request.method == "POST":
        files = [
            item for item in request.files.getlist("photos") if item and item.filename
        ]
        caption = (request.form.get("caption") or "").strip()
        if len(caption) > MAX_MOMENT_CAPTION:
            flash("Captions can be 280 characters or less.", "error")
            return redirect(url_for("admin_moments"))
        if not files:
            flash("Please choose at least one photo.", "error")
            return redirect(url_for("admin_moments"))

        saved = 0
        try:
            for file_storage in files:
                data, content_type, extension = prepare_moment_image(file_storage)
                storage_path = f"{uuid4().hex}{extension}"
                upload_moment_object(storage_path, data, content_type)
                try:
                    insert_supabase_row(
                        "team_moments",
                        {
                            "caption": caption or None,
                            "storage_path": storage_path,
                            "original_filename": (file_storage.filename or "")[:200],
                        },
                    )
                except RuntimeError:
                    delete_moment_object(storage_path)
                    raise
                saved += 1
        except (RuntimeError, ValueError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_moments"))

        flash(
            f"Uploaded {saved} photo{'s' if saved != 1 else ''}.",
            "success",
        )
        return redirect(url_for("admin_moments"))

    load_error = None
    moments = []
    try:
        moments = load_team_moments()
    except RuntimeError as exc:
        load_error = str(exc)

    return render_template(
        "admin/team_moments.html",
        active="moments",
        moments=moments,
        load_error=load_error,
    )


@app.route("/admin/moments/<moment_id>/delete", methods=["POST"])
def admin_delete_moment(moment_id):
    try:
        UUID(str(moment_id))
    except ValueError:
        flash("That photo could not be found.", "error")
        return redirect(url_for("admin_moments"))

    try:
        row = fetch_moment_by_id(moment_id)
        if not row:
            flash("That photo could not be found.", "error")
            return redirect(url_for("admin_moments"))
        storage_path = (row.get("storage_path") or "").strip()
        if storage_path:
            delete_moment_object(storage_path)
        delete_supabase_row("team_moments", moment_id)
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_moments"))

    flash("Photo deleted.", "success")
    return redirect(url_for("admin_moments"))


@app.errorhandler(413)
def request_too_large(_error):
    if request.path.startswith("/admin/moments"):
        flash("Those photos are too large. Each file must be 10MB or smaller.", "error")
        return redirect(url_for("admin_moments"))
    return "Request too large", 413


@app.route("/admin/tournament")
def admin_tournament():
    return render_template(
        "admin/in_progress.html",
        active="tournament",
        page_title="Tournament",
        page_summary="Enter tournament matches, winners, and play dates.",
        future_job="Create and list tournament_matches: round, match number, teams, winner, and played_at.",
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = request.values.get("next", "")
    if is_admin_session():
        return redirect(safe_admin_next(next_url))

    if request.method == "POST":
        ip = client_ip()
        if login_is_blocked(ip):
            flash("Too many failed attempts. Try again in a few minutes.")
            return render_template(
                "admin/login.html",
                active="login",
                next_url=next_url,
            ), 429

        role = resolve_login_role(request.form.get("password"))
        if role:
            clear_failed_logins(ip)
            session.clear()
            session["admin_role"] = role
            session["is_admin"] = True
            session.permanent = True
            return redirect(safe_admin_next(next_url, role=role))

        record_failed_login(ip)
        flash("Incorrect password.")

    return render_template(
        "admin/login.html",
        active="login",
        next_url=next_url,
    )


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@socketio.on("connect")
def handle_connect():
    if not is_admin_session():
        return False
    refresh_draft_pool_if_idle()
    emit("state_init", shared_state)


@socketio.on("run_seed")
@admin_socket_required
def handle_run_seed(data=None):
    count = 1

    if data and "count" in data:
        try:
            count = int(data["count"])
        except (ValueError, TypeError):
            emit("system_message", {"message": "❌ Please enter a valid number."})
            return

    if count < 1:
        emit("system_message", {"message": "❌ Number must be at least 1."})
        return

    current_history_count = len(shared_state["history"])

    if current_history_count >= 100:
        emit("system_message", {
            "message": "❌ History is already full (100 runs). Please clear history before running again."
        })
        return

    if current_history_count + count > 100:
        remaining = 100 - current_history_count
        emit("system_message", {
            "message": f"❌ You can only run {remaining} more time(s). Please clear history if you want to run more."
        })
        return

    if shared_state["is_running"]:
        emit("system_message", {"message": "Seed picking is already running."})
        return

    shared_state["is_running"] = True
    socketio.emit("seed_started", {"message": "Seed picking started."})

    new_results = []

    for _ in range(count):
        payload = build_result_payload()
        new_results.append(payload)
        shared_state["latest_result"] = payload
        shared_state["history"].insert(0, payload)

    shared_state["history"] = shared_state["history"][:100]
    shared_state["is_running"] = False

    socketio.emit("seed_result_batch", {"results": new_results})
    socketio.emit("history_updated", {"history": shared_state["history"]})


@socketio.on("calculate_probabilities")
@admin_socket_required
def handle_calculate_probabilities(data=None):
    try:
        season_results = parse_season_results(data)
        new_percentages = calculate_percentages_from_results(season_results)
    except ValueError as exc:
        emit("system_message", {"message": f"❌ {exc}", "target": "settings"})
        return

    apply_team_percentages(new_percentages, season_results)
    socketio.emit("probabilities_updated", {
        "team_percentages": shared_state["team_percentages"],
        "seed_probabilities": shared_state["seed_probabilities"],
        "season_results": shared_state["season_results"]
    })
    socketio.emit("system_message", {
        "message": "Probabilities updated from win-rate results.",
        "target": "settings"
    })


@socketio.on("set_manual_probabilities")
@admin_socket_required
def handle_set_manual_probabilities(data=None):
    try:
        new_percentages = parse_manual_percentages(data)
    except ValueError as exc:
        emit("system_message", {"message": f"❌ {exc}", "target": "settings"})
        return

    apply_team_percentages(new_percentages)
    socketio.emit("probabilities_updated", {
        "team_percentages": shared_state["team_percentages"],
        "seed_probabilities": shared_state["seed_probabilities"],
        "season_results": shared_state["season_results"]
    })
    socketio.emit("system_message", {
        "message": "Manual probabilities applied.",
        "target": "settings"
    })


@socketio.on("clear_history")
@admin_socket_required
def handle_clear_history():
    shared_state["latest_result"] = None
    shared_state["history"] = []
    socketio.emit("state_init", shared_state)
    socketio.emit("system_message", {"message": "History cleared."})


@socketio.on("start_draft")
@admin_socket_required
def handle_start_draft(data=None):
    if not data or "captains" not in data:
        emit("draft_message", {"message": "❌ Please select 3 captains."})
        return

    pool = load_draft_players()
    if len(pool) < DRAFT_TEAM_COUNT:
        emit("draft_message", {
            "message": (
                f"❌ Need at least {DRAFT_TEAM_COUNT} active members to draft. "
                f"Currently {len(pool)}."
            )
        })
        return

    captains = data["captains"]
    captain_ids = [str(captains.get(str(seed), "") or "").strip() for seed in SEED_LABELS]

    if any(not player_id for player_id in captain_ids):
        emit("draft_message", {"message": "❌ Please select all 3 captains."})
        return

    if len(set(captain_ids)) != DRAFT_TEAM_COUNT:
        emit("draft_message", {"message": "❌ Captains must be 3 different players."})
        return

    captain_players = {}
    for seed, player_id in zip(SEED_LABELS, captain_ids):
        player = find_draft_player(pool, player_id)
        if not player:
            emit("draft_message", {"message": "❌ Captains must be active members."})
            return
        captain_players[str(seed)] = player

    teams = {
        str(seed): [captain_players[str(seed)]]
        for seed in SEED_LABELS
    }
    captain_id_set = set(captain_ids)
    available_players = [
        player for player in pool if player.get("id") not in captain_id_set
    ]
    pick_sequence = build_pick_sequence(DRAFT_TEAM_COUNT, len(available_players))

    if pick_sequence:
        message = f"Draft started. Seed {pick_sequence[0]} is on the clock."
        completed = False
        current_seed = pick_sequence[0]
    else:
        message = "✅ Draft completed. Only captains were assigned."
        completed = True
        current_seed = None

    shared_state["draft"] = {
        "started": True,
        "completed": completed,
        "captains": {
            str(seed): captain_players[str(seed)]["id"] for seed in SEED_LABELS
        },
        "teams": teams,
        "player_pool": pool[:],
        "available_players": available_players,
        "pick_sequence": pick_sequence,
        "current_pick_index": 0,
        "current_seed": current_seed,
        "last_pick": None,
        "roster_saved": False,
        "roster_saved_season": None,
        "message": message,
    }

    emit_draft_state()


@socketio.on("make_draft_pick")
@admin_socket_required
def handle_make_draft_pick(data=None):
    draft = shared_state["draft"]

    if not draft["started"]:
        emit("draft_message", {"message": "❌ Start the draft first."})
        return

    if draft["completed"]:
        emit("draft_message", {"message": "Draft is already complete."})
        return

    player_id = ""
    if data:
        player_id = str(data.get("player_id") or data.get("player") or "").strip()
    if not player_id:
        emit("draft_message", {"message": "❌ No player selected."})
        return

    player = find_draft_player(draft["available_players"], player_id)
    if not player:
        emit("draft_message", {"message": "❌ That player is already taken or invalid."})
        return

    pick_index_before = draft["current_pick_index"]
    current_seed = draft["pick_sequence"][pick_index_before]
    current_seed_key = str(current_seed)
    draft["teams"][current_seed_key].append(player)
    draft["available_players"] = [
        entry for entry in draft["available_players"] if entry.get("id") != player_id
    ]

    draft["last_pick"] = {
        "player": player,
        "seed": current_seed,
        "pick_index_before": pick_index_before
    }

    draft["current_pick_index"] += 1
    label = draft_player_label(player)

    if draft["current_pick_index"] >= len(draft["pick_sequence"]) or not draft["available_players"]:
        draft["completed"] = True
        draft["current_seed"] = None
        draft["message"] = "✅ Draft completed."
    else:
        next_seed = draft["pick_sequence"][draft["current_pick_index"]]
        draft["current_seed"] = next_seed
        draft["message"] = (
            f"{label} drafted by Seed {current_seed}. "
            f"Seed {next_seed} is now on the clock."
        )

    emit_draft_state()


@socketio.on("undo_draft_pick")
@admin_socket_required
def handle_undo_draft_pick():
    draft = shared_state["draft"]

    if not draft["started"]:
        emit("draft_message", {"message": "❌ Start the draft first."})
        return

    last_pick = draft.get("last_pick")
    if not last_pick:
        emit("draft_message", {"message": "❌ There is no pick to undo."})
        return

    player = last_pick["player"]
    player_id = player.get("id") if isinstance(player, dict) else None
    seed = str(last_pick["seed"])
    pick_index_before = last_pick["pick_index_before"]

    team = draft["teams"].get(seed, [])
    draft["teams"][seed] = [
        entry for entry in team
        if not (isinstance(entry, dict) and entry.get("id") == player_id)
    ]

    if player_id and not find_draft_player(draft["available_players"], player_id):
        draft["available_players"].append(player)
        pool_order = {
            entry.get("id"): index
            for index, entry in enumerate(draft.get("player_pool") or [])
        }
        draft["available_players"].sort(
            key=lambda entry: pool_order.get(entry.get("id"), len(pool_order))
        )

    draft["completed"] = False
    draft["roster_saved"] = False
    draft["roster_saved_season"] = None
    draft["current_pick_index"] = pick_index_before
    draft["current_seed"] = draft["pick_sequence"][pick_index_before] if draft["pick_sequence"] else None
    draft["last_pick"] = None
    label = draft_player_label(player) if isinstance(player, dict) else str(player)
    draft["message"] = (
        f"↩️ Undid last pick: {label}. "
        f"Seed {draft['current_seed']} is back on the clock."
    )

    emit_draft_state()


@socketio.on("reset_draft")
@admin_socket_required
def handle_reset_draft():
    pool = load_draft_players()
    if pool and len(pool) >= DRAFT_TEAM_COUNT:
        reset_draft_state("Draft reset. Select 3 captains and start again.")
    else:
        reset_draft_state()
    emit_draft_state()


@socketio.on("save_draft_roster")
@admin_socket_required
def handle_save_draft_roster(data=None):
    draft = shared_state["draft"]

    if not draft.get("started"):
        emit("draft_message", {"message": "❌ Start and complete the draft first."})
        return
    if not draft.get("completed"):
        emit("draft_message", {"message": "❌ Finish the draft before saving the roster."})
        return
    if draft.get("roster_saved"):
        season = draft.get("roster_saved_season") or "that season"
        emit("draft_message", {
            "message": f"Roster already saved for {season}. Reset the draft to start over."
        })
        return

    season_label = ""
    if data:
        season_label = str(data.get("season") or "").strip()
    if not season_label:
        emit("draft_message", {"message": "❌ Choose which season this roster is for."})
        return

    try:
        known_seasons = {row["season"] for row in load_draft_season_options()}
        if season_label not in known_seasons:
            raise ValueError("Choose a season from the Seasons list.")
        seed_teams = parse_seed_team_map(data)
        rows = build_team_member_rows(draft, season_label, seed_teams)
        if team_members_exist_for_season(season_label):
            raise ValueError(
                f"{season_label} already has team_members rows. "
                "Clear or fix that season in Supabase before saving again."
            )
        insert_supabase_rows("team_members", rows)
    except ValueError as exc:
        emit("draft_message", {"message": f"❌ {exc}"})
        return
    except RuntimeError as exc:
        emit("draft_message", {"message": f"❌ {roster_form_error_message(exc)}"})
        return

    draft["roster_saved"] = True
    draft["roster_saved_season"] = season_label
    draft["message"] = (
        f"✅ Saved {len(rows)} team members for {season_label}."
    )
    emit_draft_state()
    emit("draft_message", {"message": draft["message"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
    )
