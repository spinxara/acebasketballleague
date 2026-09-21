# ACE Seed Picking & Draft System

A Flask and Socket.IO web app for running weighted seed picks and managing a live snake draft for a small ACE league.

Live site: https://seedpicking.daeyoungroh.com/

## Features

- Weighted seed picking for three teams.
- Top-right settings menu with a win-rate based calculator and manual captain-agreed odds.
- Seed history with a maximum of 100 runs before clearing history is required.
- Real-time shared draft state using Socket.IO.
- Three-team player draft with captain selection.
- Snake draft order:

```text
1 -> 2 -> 3 -> 3 -> 2 -> 1 -> 1 -> 2 -> 3 -> 3 -> 2 -> 1 ...
```

- One-level undo for the most recent draft pick.
- Full draft reset for choosing new captains and restarting.

## Project Structure

```text
.
├── app.py                    # Main Flask/Socket.IO web server
├── templates/
│   └── index.html            # Web UI
├── seed_picking.py           # Telegram seed picking script
├── seed_picking_server.py    # Telegram bot server script
├── advanced_random_order.py  # Weighted draft order experiment
└── app_v1.00.py              # Older app version
```

## Requirements

- Python 3
- Flask
- Flask-SocketIO
- Cloudflare tunnel, if exposing the app externally

Install the Python dependencies:

```bash
pip install flask flask-socketio
```

## Run Locally

Start the Flask server:

```bash
python3 app.py
```

The app runs on:

```text
http://localhost:5050
```

## External Access

To expose the app through the configured Cloudflare tunnel, keep the Flask server running and start the tunnel:

```bash
cloudflared tunnel run seedpicking
```

## How To Use

### Seed Picking

1. Open the web app.
2. Click **Run Seed** to generate one or more weighted seed results.
3. Clear history when the 100-run limit is reached.

### Player Draft

1. Select one captain for each of the three seeds.
2. Click **Start Draft**.
3. Click an available player name when that seed is on the clock.
4. Use **Undo Last Pick** to revert the most recent pick.
5. Use **Reset Draft** to clear the draft and start over.

## Notes

- The server must remain running while the app is in use.
- Cloudflare tunnel is required for external access.
- The app is designed for real-time shared use during live drafts.

## Maintainer

Dae Young Roh
