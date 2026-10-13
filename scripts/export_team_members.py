"""Export every team_members row to team_members.csv.

The Supabase SQL editor only shows 100 rows. This script pages through the
REST API until the table is exhausted.

Run from the project root:

    python3 scripts/export_team_members.py
"""

import csv
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import certifi
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "team_members.csv"
PAGE_SIZE = 1000


def fetch_page(base_url, api_key, offset):
    end = offset + PAGE_SIZE - 1
    request = urllib.request.Request(
        f"{base_url}/rest/v1/team_members?select=*&order=id.asc",
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Range-Unit": "items",
            "Range": f"{offset}-{end}",
            "Prefer": "count=exact",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            payload = response.read().decode("utf-8")
            content_range = response.headers.get("Content-Range", "")
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return [], offset, offset
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase request failed ({exc.code}): {body}") from exc

    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise SystemExit(f"Unexpected Supabase response: {payload[:200]}")

    total = None
    if "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1]
        if total_text.isdigit():
            total = int(total_text)
    return rows, offset + len(rows), total


def main():
    load_dotenv(ROOT / ".env")
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    api_key = os.environ.get("SUPABASE_API_KEY", "")
    if not base_url or not api_key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_API_KEY in .env")

    rows = []
    offset = 0
    total = None
    while total is None or offset < total:
        page, offset, total = fetch_page(base_url, api_key, offset)
        if not page:
            break
        rows.extend(page)

    if not rows:
        print("team_members is empty.")
        return

    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
