from __future__ import print_function
import argparse
import datetime
import os.path
import uuid
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# SCOPES we need (events scope allows creating events and Meet links)
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Defaults - override with args or environment
HR_EMAIL = os.environ.get("HR_EMAIL", "srikanthtata8374@gmail.com")
INTERVIEWER_EMAIL = os.environ.get("CALENDAR_EMAIL", os.environ.get("INTERVIEWER_EMAIL", "recruit@tekleaders.io"))

TOKEN_PATH = 'token.json'
CREDENTIALS_PATH = 'credentials.json'


def get_service(token_path: str = TOKEN_PATH, credentials_path: str = CREDENTIALS_PATH):
    """Obtain an authenticated Google Calendar API service using installed app flow.
    Saves/loads token.json automatically.
    """
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"OAuth credentials file not found: {credentials_path}")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    return service


def check_freebusy(service, calendar_id: str, start: datetime.datetime, end: datetime.datetime):
    """Return free/busy blocks for the given calendar id between start and end datetimes."""
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": calendar_id}],
        "timeZone": "UTC"
    }
    fb = service.freebusy().query(body=body).execute()
    return fb['calendars'].get(calendar_id, {}).get('busy', [])


def create_event(
    service,
    organizer_calendar_id: str,
    attendees_emails: List[str],
    start: datetime.datetime,
    end: datetime.datetime,
    summary: str,
    description: str = "",
    send_updates: str = 'all'
):
    """Create an event on `organizer_calendar_id` and invite `attendees_emails`.
    Attempts to create a Google Meet link.
    Returns the created event resource.
    """
    attendees = [{"email": e} for e in attendees_emails]

    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        "attendees": attendees,
        "conferenceData": {
            "createRequest": {
                "requestId": f"meet-{uuid.uuid4().hex[:16]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }
    }

    try:
        event = service.events().insert(
            calendarId=organizer_calendar_id,
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates=send_updates
        ).execute()
        return event

    except HttpError as e:
        # Provide helpful debug info and try fallback (without conferenceData)
        # e.content may be bytes
        content = getattr(e, 'content', None)
        detail = None
        try:
            if content:
                detail = content.decode() if isinstance(content, bytes) else str(content)
        except Exception:
            detail = str(e)

        print(f"Google Calendar API error creating event: {e}")
        if detail:
            print("Details:", detail)

        # Retry without conferenceData
        try:
            print("Retrying event creation without conferenceData (no Meet)...")
            if 'conferenceData' in event_body:
                event_body.pop('conferenceData', None)
            event = service.events().insert(
                calendarId=organizer_calendar_id,
                body=event_body,
                sendUpdates=send_updates
            ).execute()
            return event
        except Exception as e2:
            print("Retry also failed:", str(e2))
            raise


def parse_iso_datetime(v: str) -> datetime.datetime:
    """Parse a variety of ISO datetime strings. If no timezone, assume local system timezone (naive -> use UTC)."""
    try:
        # Try fromisoformat (Python 3.7+)
        dt = datetime.datetime.fromisoformat(v)
    except Exception:
        # Fallback: try strptime common formats
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(v, fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            raise ValueError(f"Unrecognized datetime format: {v}")

    # If naive, convert to UTC (you may want to change this behavior to your timezone)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def main():
    parser = argparse.ArgumentParser(description="Simple Google Calendar helper (check freebusy, create events)")
    sub = parser.add_subparsers(dest='cmd')

    p_check = sub.add_parser('check', help='Check freebusy for INTERVIEWER_EMAIL for next N days')
    p_check.add_argument('--days', type=int, default=1, help='How many days ahead to check (default 1)')

    p_create = sub.add_parser('create', help='Create event and invite candidate + interviewer')
    p_create.add_argument('--candidate', required=True, help='Candidate email')
    p_create.add_argument('--start', required=True, help='Start datetime (ISO)')
    p_create.add_argument('--duration', type=int, default=60, help='Duration minutes (default 60)')
    p_create.add_argument('--summary', default='Interview', help='Event summary/subject')
    p_create.add_argument('--description', default='', help='Event description')
    p_create.add_argument('--organizer', default=INTERVIEWER_EMAIL, help='Organizer calendar (defaults to interviewer)')

    args = parser.parse_args()

    service = get_service()

    if args.cmd == 'check':
        now = datetime.datetime.utcnow()
        end = now + datetime.timedelta(days=args.days)
        busy = check_freebusy(service, INTERVIEWER_EMAIL, now, end)
        if not busy:
            print('Interviewer is free for the period')
        else:
            print('Busy blocks:')
            for b in busy:
                print(' -', b)

    elif args.cmd == 'create':
        candidate = args.candidate
        start = parse_iso_datetime(args.start)
        end = start + datetime.timedelta(minutes=args.duration)
        attendees = [candidate, INTERVIEWER_EMAIL]

        print('Creating event:')
        print('  Organizer:', args.organizer)
        print('  Attendees:', attendees)
        print('  Start:', start.isoformat())
        print('  End:', end.isoformat())

        try:
            event = create_event(
                service=service,
                organizer_calendar_id=args.organizer,
                attendees_emails=attendees,
                start=start,
                end=end,
                summary=args.summary,
                description=args.description,
                send_updates='all'
            )
            print('\nEvent created successfully!')
            print('Event ID:', event.get('id'))
            print('Event URL:', event.get('htmlLink'))
            print('Meet link:', event.get('hangoutLink') or event.get('conferenceData'))
        except Exception as e:
            print('Failed to create event:', str(e))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
