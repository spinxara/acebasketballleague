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
from datetime import datetime, timedelta
from functools import wraps
from threading import Lock
from urllib.parse import urlparse

import certifi
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ""
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=10)
_login_attempts = {}
_login_lock = Lock()

RULES_URL = (
    "https://docs.google.com/document/d/"
    "1fIlVY1edEn2_5AAxF6eNV0D72vtWwOF4CamZVsxT8q0/edit?usp=sharing"
)

PUBLIC_NAV = [
    {"id": "home", "label": "Home", "endpoint": "home"},
    {"id": "season-results", "label": "Season Results", "endpoint": "season_results"},
    {"id": "member-stats", "label": "Member Stats", "endpoint": "member_stats"},
    {"id": "player-stats", "label": "Player Stats by Season", "endpoint": "player_stats"},
    {"id": "team-matchups", "label": "Team Matchups", "endpoint": "team_matchups"},
]

ADMIN_NAV = [
    {"id": "dashboard", "label": "Dashboard", "endpoint": "admin_dashboard"},
    {"id": "draft", "label": "Draft Room", "endpoint": "admin_draft"},
    {"id": "roster", "label": "Roster", "endpoint": "admin_roster"},
    {"id": "games", "label": "Games", "endpoint": "admin_games"},
    {"id": "tournament", "label": "Tournament", "endpoint": "admin_tournament"},
]


def is_admin_session():
    return bool(session.get("is_admin"))


def client_ip():
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"


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


def password_matches(submitted):
    if not ADMIN_PASSWORD:
        return False
    secret = str(app.config["SECRET_KEY"]).encode("utf-8")
    guessed = hmac.new(secret, (submitted or "").encode("utf-8"), "sha256").digest()
    expected = hmac.new(secret, ADMIN_PASSWORD.encode("utf-8"), "sha256").digest()
    return hmac.compare_digest(guessed, expected)


def safe_admin_next(value):
    if not isinstance(value, str):
        return url_for("admin_dashboard")
    path = urlparse(value).path
    if path.startswith("/admin") and not path.startswith("/admin/login"):
        return path
    return url_for("admin_dashboard")


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
    return {
        "public_nav": PUBLIC_NAV,
        "admin_nav": ADMIN_NAV,
        "rules_url": RULES_URL,
        "last_updated": "September 14, 2026",
        "current_year": datetime.now().year,
        "is_admin": is_admin_session(),
    }


@app.before_request
def require_admin_for_admin_pages():
    if not request.path.startswith("/admin"):
        return None
    if request.endpoint in {"admin_login", "admin_logout"}:
        return None
    if is_admin_session():
        return None
    return redirect(url_for("admin_login", next=request.path))


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

ALL_PLAYERS = [
    "Alex Hahn",
    "Allen 기준 Lee",
    "Boum Soo Kim",
    "Brian 병훈 Paek",
    "Clan Hahn",
    "Dae Young Roh",
    "David 민형 Jin",
    "Donggyu Lee",
    "Dongjun Min",
    "Edward 에디 Kim",
    "Eric 형승 Lim",
    "Johann Lee",
    "Mike Hong",
    "Min Hun 민훈 Paik",
    "Minwoo Cho",
    "Peter 석현 Yeon",
    "Quinn 규현 Chung",
    "Sangmin Moon",
    "Shawn White",
    "Tenzing Sherpa",
    "Tong Young Ko"
]

SEED_LABELS = [1, 2, 3]
TEAM_SIZE = 7

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
        "available_players": ALL_PLAYERS[:],
        "pick_sequence": [],
        "current_pick_index": 0,
        "current_seed": None,
        "last_pick": None,
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


def build_pick_sequence(team_count, rounds):
    sequence = []
    forward = list(range(1, team_count + 1))
    backward = list(range(team_count, 0, -1))

    for round_number in range(rounds):
        sequence.extend(forward if round_number % 2 == 0 else backward)

    return sequence


def reset_draft_state(message="Draft reset."):
    shared_state["draft"] = {
        "started": False,
        "completed": False,
        "captains": {},
        "teams": {"1": [], "2": [], "3": []},
        "available_players": ALL_PLAYERS[:],
        "pick_sequence": [],
        "current_pick_index": 0,
        "current_seed": None,
        "last_pick": None,
        "message": message
    }


def emit_draft_state():
    socketio.emit("draft_state", shared_state["draft"])


SEASON_COLUMNS = "season,status,season_winner,tournament_winner,mip_award,season_page"
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


def supabase_request(path, method="GET", body=None):
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    api_key = os.environ.get("SUPABASE_API_KEY", "")
    if not supabase_url or not api_key:
        raise RuntimeError("Supabase is not configured.")

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        f"{supabase_url}/rest/v1/{path}",
        data=data,
        headers=headers,
        method=method,
    )

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(request, timeout=15, context=ssl_context) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        exc.read()
        raise RuntimeError(f"Supabase request failed ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach Supabase.") from exc


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
    if "complete" in value or value in {"done", "finished"}:
        return "status-complete"
    if any(token in value for token in ("progress", "active", "current", "ongoing")):
        return "status-active"
    return "status-neutral"


def season_page_url(value):
    if not value or not isinstance(value, str):
        return ""
    url = value.strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def load_season_records():
    rows = fetch_supabase_rows("seasons", SEASON_COLUMNS)
    rows.sort(key=season_sort_key)
    return [
        {
            "season": row.get("season") or "",
            "status": row.get("status") or "",
            "season_winner": row.get("season_winner") or "",
            "tournament_winner": row.get("tournament_winner") or "",
            "mip_award": row.get("mip_award") or "",
            "season_page": season_page_url(row.get("season_page")),
            "status_class": season_status_class(row.get("status")),
        }
        for row in rows
    ]


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


@app.route("/")
def home():
    return render_template("public/home.html", active="home")


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
    return render_template("admin/draft.html", active="draft")


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


@app.route("/admin/roster")
def admin_roster():
    return render_template(
        "admin/in_progress.html",
        active="roster",
        page_title="Roster",
        page_summary="Assign players to NPS, KCN, and BK for a season.",
        future_job="Create and list team_members rows: season team, player, season, year, and starting month.",
    )


@app.route("/admin/games")
def admin_games():
    return render_template(
        "admin/in_progress.html",
        active="games",
        page_title="Games",
        page_summary="Record regular-season games and who played in each one.",
        future_job=(
            "Insert game_results, then player_played_games with game_id lookup "
            "and guest status from the roster."
        ),
    )


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

        if password_matches(request.form.get("password")):
            clear_failed_logins(ip)
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            return redirect(safe_admin_next(next_url))

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

    captains = data["captains"]
    captain_values = [captains.get(str(seed), "").strip() for seed in SEED_LABELS]

    if any(not name for name in captain_values):
        emit("draft_message", {"message": "❌ Please select all 3 captains."})
        return

    if len(set(captain_values)) != 3:
        emit("draft_message", {"message": "❌ Captains must be 3 different players."})
        return

    if any(name not in ALL_PLAYERS for name in captain_values):
        emit("draft_message", {"message": "❌ Invalid captain selection."})
        return

    teams = {}
    for seed in SEED_LABELS:
        captain_name = captains[str(seed)].strip()
        teams[str(seed)] = [captain_name]

    available_players = [p for p in ALL_PLAYERS if p not in captain_values]
    rounds_needed = TEAM_SIZE - 1
    pick_sequence = build_pick_sequence(team_count=3, rounds=rounds_needed)

    shared_state["draft"] = {
        "started": True,
        "completed": False,
        "captains": {str(seed): captains[str(seed)].strip() for seed in SEED_LABELS},
        "teams": teams,
        "available_players": available_players,
        "pick_sequence": pick_sequence,
        "current_pick_index": 0,
        "current_seed": pick_sequence[0] if pick_sequence else None,
        "last_pick": None,
        "message": f"Draft started. Seed {pick_sequence[0]} is on the clock." if pick_sequence else "Draft started."
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

    if not data or "player" not in data:
        emit("draft_message", {"message": "❌ No player selected."})
        return

    player = data["player"].strip()

    if player not in draft["available_players"]:
        emit("draft_message", {"message": "❌ That player is already taken or invalid."})
        return

    pick_index_before = draft["current_pick_index"]
    current_seed = draft["pick_sequence"][pick_index_before]
    current_seed_key = str(current_seed)
    draft["teams"][current_seed_key].append(player)
    draft["available_players"].remove(player)

    draft["last_pick"] = {
        "player": player,
        "seed": current_seed,
        "pick_index_before": pick_index_before
    }

    draft["current_pick_index"] += 1

    if draft["current_pick_index"] >= len(draft["pick_sequence"]) or not draft["available_players"]:
        draft["completed"] = True
        draft["current_seed"] = None
        draft["message"] = "✅ Draft completed."
    else:
        next_seed = draft["pick_sequence"][draft["current_pick_index"]]
        draft["current_seed"] = next_seed
        draft["message"] = f"{player} drafted by Seed {current_seed}. Seed {next_seed} is now on the clock."

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
    seed = str(last_pick["seed"])
    pick_index_before = last_pick["pick_index_before"]

    if player in draft["teams"].get(seed, []):
        draft["teams"][seed].remove(player)

    if player not in draft["available_players"]:
        draft["available_players"].append(player)
        draft["available_players"].sort(key=ALL_PLAYERS.index)

    draft["completed"] = False
    draft["current_pick_index"] = pick_index_before
    draft["current_seed"] = draft["pick_sequence"][pick_index_before] if draft["pick_sequence"] else None
    draft["last_pick"] = None
    draft["message"] = f"↩️ Undid last pick: {player}. Seed {draft['current_seed']} is back on the clock."

    emit_draft_state()


@socketio.on("reset_draft")
@admin_socket_required
def handle_reset_draft():
    reset_draft_state("Draft reset. Select 3 captains and start again.")
    emit_draft_state()


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
