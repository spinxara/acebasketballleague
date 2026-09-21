import os
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import random
from datetime import datetime
from copy import deepcopy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

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
    {"id": "draft", "label": "Draft Room", "endpoint": "draft_room"},
]

ADMIN_NAV = [
    {"id": "dashboard", "label": "Dashboard", "endpoint": "admin_dashboard"},
    {"id": "roster", "label": "Roster", "endpoint": "admin_roster"},
    {"id": "games", "label": "Games", "endpoint": "admin_games"},
    {"id": "tournament", "label": "Tournament", "endpoint": "admin_tournament"},
    {"id": "login", "label": "Login", "endpoint": "admin_login"},
]


@app.context_processor
def inject_globals():
    return {
        "public_nav": PUBLIC_NAV,
        "admin_nav": ADMIN_NAV,
        "rules_url": RULES_URL,
        "last_updated": "September 14, 2026",
        "current_year": datetime.now().year,
    }


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


@app.route("/")
def home():
    return render_template("public/home.html", active="home")


@app.route("/season-results")
def season_results():
    return render_template(
        "public/in_progress.html",
        active="season-results",
        page_title="Season Results",
        page_summary=(
            "Season summaries, including champions, status, MIP awards, "
            "match results, and video recordings."
        ),
        upcoming_columns=[
            "Season",
            "Status",
            "Season Winner",
            "Tournament Winner",
            "MIP Award",
        ],
        extra_note="Match results and video recordings will also live on this page.",
    )


@app.route("/member-stats")
def member_stats():
    return render_template(
        "public/in_progress.html",
        active="member-stats",
        page_title="Member Stats",
        page_summary="Career player stats and game participation across all seasons.",
        upcoming_columns=[
            "Player",
            "Total Games",
            "Total Wins",
            "Win Rate",
            "Seasons",
            "Season Titles",
            "Season Runner-ups",
            "Tournament Titles",
            "Tournament Runner-ups",
        ],
    )


@app.route("/player-stats")
def player_stats():
    return render_template(
        "public/in_progress.html",
        active="player-stats",
        page_title="Player Stats by Season",
        page_summary="Per-season player stats, grouped by team, with guest players listed last.",
        upcoming_columns=[
            "Season",
            "Player",
            "Season Team",
            "Games",
            "Wins",
            "Win Rate",
            "Comments",
        ],
    )


@app.route("/team-matchups")
def team_matchups():
    return render_template(
        "public/in_progress.html",
        active="team-matchups",
        page_title="Team Matchups",
        page_summary="Head-to-head strength between teams for each season, including roster context.",
        upcoming_columns=[
            "Season",
            "Team",
            "Opponent",
            "Games",
            "Wins",
            "Win Rate",
            "Team Members",
        ],
    )


@app.route("/draft")
def draft_room():
    return render_template("index.html")


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


@app.route("/admin/login")
def admin_login():
    return render_template(
        "admin/in_progress.html",
        active="login",
        page_title="Login",
        page_summary="Captains and admins will sign in here before managing league data.",
        future_job="Shared password first, then individual captain accounts if needed.",
    )


@socketio.on("connect")
def handle_connect():
    emit("state_init", shared_state)


@socketio.on("run_seed")
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
def handle_clear_history():
    shared_state["latest_result"] = None
    shared_state["history"] = []
    socketio.emit("state_init", shared_state)
    socketio.emit("system_message", {"message": "History cleared."})


@socketio.on("start_draft")
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
def handle_reset_draft():
    reset_draft_state("Draft reset. Select 3 captains and start again.")
    emit_draft_state()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
    )
