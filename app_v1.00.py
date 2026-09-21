from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import random
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this"
socketio = SocketIO(app, cors_allowed_origins="*")

team_percentages = {
    "NPS": 50,
    "KCN": 35,
    "BK": 15
}

shared_state = {
    "is_running": False,
    "latest_result": None,
    "history": []
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

def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th') }"

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

@app.route("/")
def index():
    return render_template("index.html")

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

@socketio.on("clear_history")
def handle_clear_history():
    shared_state["latest_result"] = None
    shared_state["history"] = []
    socketio.emit("state_init", shared_state)
    socketio.emit("system_message", {"message": "History cleared."})

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5050, debug=True)

