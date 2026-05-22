#!/usr/bin/env python3
"""
One-time setup: sign in as recruit@tekleaders.io so interviews get Google Meet links.

1. In GCP: Credentials -> OAuth client ID -> Desktop app -> download JSON.
2. Save as oauth_client.json in this folder (NOT the service account JSON).
3. Run:  python setup_calendar_oauth.py
4. Copy the printed GOOGLE_OAUTH_* lines into .env (and Render).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

OAUTH_CLIENT = ROOT / "oauth_client.json"
TOKEN = ROOT / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
ENV_FILE = ROOT / ".env"


def _update_env(client_id: str, client_secret: str, refresh: str) -> None:
    """Write OAuth vars into .env (keeps other lines unchanged)."""
    if not ENV_FILE.is_file():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updates = {
        "CALENDAR_AUTH_MODE": "oauth",
        "GOOGLE_OAUTH_CLIENT_ID": client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": client_secret,
        "GOOGLE_OAUTH_REFRESH_TOKEN": refresh,
        "CALENDAR_EMAIL": "recruit@tekleaders.io",
    }
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Updated {ENV_FILE}")


def main() -> None:
    if not OAUTH_CLIENT.is_file():
        print("Missing oauth_client.json")
        print("Download OAuth Desktop client JSON from GCP and save as:")
        print(f"  {OAUTH_CLIENT}")
        sys.exit(1)

    peek = json.loads(OAUTH_CLIENT.read_text(encoding="utf-8"))
    if peek.get("type") == "service_account":
        print("oauth_client.json is a SERVICE ACCOUNT file.")
        print("Create an OAuth 'Desktop app' client instead. Keep SA JSON as credentials.json.")
        sys.exit(1)
    if "installed" not in peek and "web" not in peek:
        print("oauth_client.json must be OAuth client (installed or web), not service account.")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    print("Browser will open — sign in as recruit@tekleaders.io")
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nSaved {TOKEN}")

    data = json.loads(creds.to_json())
    refresh = data.get("refresh_token") or ""
    installed = peek.get("installed") or peek.get("web") or {}
    client_id = installed.get("client_id") or ""
    client_secret = installed.get("client_secret") or ""

    print("\n" + "=" * 60)
    print("Add these to hiring/.env and Render:")
    print("=" * 60)
    print("CALENDAR_AUTH_MODE=oauth")
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_secret}")
    if refresh:
        print(f"GOOGLE_OAUTH_REFRESH_TOKEN={refresh}")
    else:
        print("# No refresh_token — use token.json on this machine only")
    print("CALENDAR_EMAIL=recruit@tekleaders.io")
    print("=" * 60)

    _update_env(client_id, client_secret, refresh)
    load_dotenv(ENV_FILE, override=True)

    from google_calendar import create_calendar_event, extract_meet_link
    from datetime import datetime, timedelta, timezone

    kolkata = timezone(timedelta(hours=5, minutes=30))
    start = datetime.now(kolkata).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
    end = start + timedelta(hours=1)
    print("\nTest event with Meet...")
    event = create_calendar_event(
        summary="Hiring POC Meet test",
        description="Delete this test event",
        start_dt=start,
        end_dt=end,
        organizer_email="recruit@tekleaders.io",
        attendees_emails=["recruit@tekleaders.io"],
        timezone="Asia/Kolkata",
        send_updates="none",
    )
    meet = extract_meet_link(event)
    print("Meet link:", meet or "(not created — contact admin)")
    print("Event:", event.get("htmlLink"))


if __name__ == "__main__":
    main()
