#!/usr/bin/env python3
"""
Check Calendar Setup (installed-app OAuth flow)

This script uses the installed-app (desktop) OAuth flow to obtain user
credentials and saves a `token.json` file. It can:
 - check free/busy for a calendar
 - create an event (and attempt to create a Meet link)

Usage (from project root):
  python check_calendar_setup.py check --days 1
  python check_calendar_setup.py create --candidate candidate@example.com --start "2025-12-02T14:00" --duration 60

Make sure `credentials.json` (OAuth client for desktop) is present in the project root.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import uuid
from google.auth import transport
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scopes for installed app - allow event creation and checking availability
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",  # Check availability
    "https://www.googleapis.com/auth/calendar.events"    # Create events
]

TOKEN_PATH = Path('token.json')
CREDENTIALS_PATH = Path('credentials.json')

from dotenv import load_dotenv
load_dotenv()
DEFAULT_INTERVIEWER = os.environ.get('CALENDAR_EMAIL', os.environ.get('INTERVIEWER_EMAIL', 'recruit@tekleaders.io'))


def get_service(token_path: Path = TOKEN_PATH, credentials_path: Path = CREDENTIALS_PATH):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(f"Missing OAuth credentials file: {credentials_path}")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    return service


def check_freebusy(service, calendar_id: str, days: int = 1):
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    end = now + datetime.timedelta(days=days)

    body = {
        'timeMin': now.isoformat(),
        'timeMax': end.isoformat(),
        'items': [{'id': calendar_id}],
    }
    fb = service.freebusy().query(body=body).execute()
    return fb.get('calendars', {}).get(calendar_id, {}).get('busy', [])


def create_event(service, organizer: str, attendees: list, start: datetime.datetime, end: datetime.datetime, summary: str, description: str = ''):
    event_body = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': end.isoformat(), 'timeZone': 'UTC'},
        'attendees': [{'email': e} for e in attendees],
        'conferenceData': {
            'createRequest': {
                'requestId': f"meet-{uuid.uuid4().hex[:16]}",
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        }
    }

    try:
        event = service.events().insert(calendarId=organizer, body=event_body, conferenceDataVersion=1, sendUpdates='all').execute()
        return event
    except HttpError as e:
        detail = getattr(e, 'content', None)
        print(f"Google Calendar API error creating event: {e}")
        if detail:
            try:
                print('Details:', detail.decode() if isinstance(detail, bytes) else str(detail))
            except Exception:
                print('Details:', str(detail))
        # Retry without conferenceData
        print('Retrying without conferenceData...')
        event_body.pop('conferenceData', None)
        event = service.events().insert(calendarId=organizer, body=event_body, sendUpdates='all').execute()
        return event


def parse_iso(v: str) -> datetime.datetime:
    try:
        dt = datetime.datetime.fromisoformat(v)
    except Exception:
        try:
            dt = datetime.datetime.strptime(v, '%Y-%m-%dT%H:%M')
        except Exception:
            dt = datetime.datetime.strptime(v, '%Y-%m-%d')

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    p_check = sub.add_parser('check')
    p_check.add_argument('--days', type=int, default=1)
    p_check.add_argument('--calendar', default=DEFAULT_INTERVIEWER)

    p_create = sub.add_parser('create')
    p_create.add_argument('--candidate', required=True)
    p_create.add_argument('--start', required=True)
    p_create.add_argument('--duration', type=int, default=60)
    p_create.add_argument('--organizer', default=DEFAULT_INTERVIEWER)
    p_create.add_argument('--summary', default='Interview')
    p_create.add_argument('--description', default='')

    args = parser.parse_args()
    service = get_service()

    if args.cmd == 'check':
        busy = check_freebusy(service, args.calendar, args.days)
        if not busy:
            print('Calendar is free for the period')
        else:
            print('Busy blocks:')
            for b in busy:
                print(' -', b)

    elif args.cmd == 'create':
        start = parse_iso(args.start)
        end = start + datetime.timedelta(minutes=args.duration)
        attendees = [args.candidate, args.organizer]
        print('Creating event...')
        event = create_event(service, args.organizer, attendees, start, end, args.summary, args.description)
        print('Event created:')
        print('  ID:', event.get('id'))
        print('  Link:', event.get('htmlLink'))
        print('  Meet:', event.get('hangoutLink') or event.get('conferenceData'))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
