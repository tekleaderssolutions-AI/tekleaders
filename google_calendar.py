# google_calendar.py
"""
Google Calendar integration for fetching interviewer availability.
Supports both service account (server-to-server) and installed-app OAuth flows.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import os
import time
import uuid
from urllib.parse import quote
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    GOOGLE_CALENDAR_CREDENTIALS_PATH,
    CALENDAR_EMAIL,
    INTERVIEW_DURATION_MINUTES,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REFRESH_TOKEN,
    GOOGLE_OAUTH_CLIENT_PATH,
    CALENDAR_AUTH_MODE,
)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",  # Check availability
    "https://www.googleapis.com/auth/calendar.events"    # Create events
]
TOKEN_PATH = Path("token.json")
OAUTH_CLIENT_PATH = Path(GOOGLE_OAUTH_CLIENT_PATH or "oauth_client.json")


def _oauth_env_configured() -> bool:
    return bool(
        (GOOGLE_OAUTH_REFRESH_TOKEN or "").strip()
        and (GOOGLE_OAUTH_CLIENT_ID or "").strip()
        and (GOOGLE_OAUTH_CLIENT_SECRET or "").strip()
    )


def calendar_auth_is_service_account() -> bool:
    """True when using SA (Meet links often missing). False when OAuth as recruit@."""
    mode = (CALENDAR_AUTH_MODE or "auto").lower()
    if mode == "oauth":
        return False
    if mode == "service_account":
        return True
    if _oauth_env_configured() or TOKEN_PATH.exists():
        return False
    return _credentials_are_service_account()


def _get_oauth_credentials():
    """
    OAuth as recruit@ — required for Google Meet on calendar events.
    Uses .env refresh token (Render) or oauth_client.json + token.json (local).
    """
    if _oauth_env_configured():
        creds = Credentials(
            None,
            refresh_token=(GOOGLE_OAUTH_REFRESH_TOKEN or "").strip(),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=(GOOGLE_OAUTH_CLIENT_ID or "").strip(),
            client_secret=(GOOGLE_OAUTH_CLIENT_SECRET or "").strip(),
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not OAUTH_CLIENT_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {OAUTH_CLIENT_PATH}. Run: python setup_calendar_oauth.py"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _get_service_account_calendar_service():
    creds_path = Path(GOOGLE_CALENDAR_CREDENTIALS_PATH or "credentials.json")
    if not creds_path.exists():
        raise FileNotFoundError(f"Missing service account JSON: {creds_path}")
    peek = json.loads(creds_path.read_text(encoding="utf-8"))
    if peek.get("type") != "service_account":
        raise ValueError(f"{creds_path} is not a service account JSON")
    credentials = service_account.Credentials.from_service_account_file(
        str(creds_path),
        scopes=[
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )
    return build("calendar", "v3", credentials=credentials)


def get_calendar_service():
    """
    Prefer OAuth (recruit@) for Google Meet. Service account is fallback for free/busy only.
    Set CALENDAR_AUTH_MODE=oauth in .env after running setup_calendar_oauth.py.
    """
    mode = (CALENDAR_AUTH_MODE or "auto").lower()
    try_oauth = mode == "oauth" or (
        mode == "auto" and (_oauth_env_configured() or TOKEN_PATH.exists())
    )

    if try_oauth:
        try:
            creds = _get_oauth_credentials()
            print("[CALENDAR] Auth: OAuth (recruit@) — Google Meet enabled")
            return build("calendar", "v3", credentials=creds)
        except Exception as oauth_error:
            if mode == "oauth":
                raise Exception(
                    f"Calendar OAuth required for Meet links. Run setup_calendar_oauth.py. ({oauth_error})"
                ) from oauth_error
            print(f"[CALENDAR] OAuth failed ({oauth_error}); falling back to service account")

    print(
        "[CALENDAR] Auth: service account — Meet may be missing. "
        "Set CALENDAR_AUTH_MODE=oauth after setup_calendar_oauth.py"
    )
    return _get_service_account_calendar_service()


def get_available_slots(date: datetime, num_slots: int = 3, calendar_email: str = None) -> List[Dict[str, Any]]:
    """
    Fetch available time slots for a given date.
    
    Args:
        date: The date to check availability (datetime object)
        num_slots: Number of time slots to return (default: 3)
        calendar_email: Email of the calendar to check (defaults to CALENDAR_EMAIL / recruit@tekleaders.io)
    
    Returns:
        List of dictionaries with 'start_time' and 'end_time' datetime objects
    """
    try:
        service = get_calendar_service()
        
        # Use provided calendar email or default to INTERVIEWER_EMAIL
        target_calendar = calendar_email or CALENDAR_EMAIL
        
        # Define working hours (9 AM to 5 PM)
        start_of_day = date.replace(hour=9, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(hour=17, minute=0, second=0, microsecond=0)
        
        # Query free/busy information
        body = {
            "timeMin": start_of_day.isoformat() + 'Z',
            "timeMax": end_of_day.isoformat() + 'Z',
            "items": [{"id": target_calendar}],
            "timeZone": "Asia/Kolkata"
        }
        
        freebusy_result = service.freebusy().query(body=body).execute()
        busy_times = freebusy_result['calendars'][target_calendar].get('busy', [])
        
        # Convert busy times to datetime objects
        busy_periods = []
        for busy in busy_times:
            busy_start = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
            busy_end = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
            busy_periods.append((busy_start, busy_end))
        
        # Find available slots
        available_slots = []
        current_time = start_of_day
        slot_duration = timedelta(minutes=INTERVIEW_DURATION_MINUTES)
        
        while current_time + slot_duration <= end_of_day and len(available_slots) < num_slots:
            slot_end = current_time + slot_duration
            
            # Check if this slot overlaps with any busy period
            is_available = True
            for busy_start, busy_end in busy_periods:
                if (current_time < busy_end and slot_end > busy_start):
                    is_available = False
                    # Jump to the end of this busy period
                    current_time = busy_end
                    break
            
            if is_available:
                available_slots.append({
                    'start_time': current_time,
                    'end_time': slot_end
                })
                # Move to next potential slot (30 minutes after this one starts)
                current_time += timedelta(minutes=30)
            
        return available_slots
        
    except HttpError as error:
        raise Exception(f"Google Calendar API error: {error}")
    except Exception as e:
        raise Exception(f"Error fetching available slots: {str(e)}")


def format_time_slot(slot: Dict[str, Any]) -> str:
    """
    Format a time slot for display in email.
    
    Args:
        slot: Dictionary with 'start_time' and 'end_time'
    
    Returns:
        Formatted string like "2:00 PM - 3:00 PM"
    """
    start = slot['start_time']
    end = slot['end_time']
    return f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}"


def _credentials_are_service_account() -> bool:
    creds_path = Path(GOOGLE_CALENDAR_CREDENTIALS_PATH or "credentials.json")
    if not creds_path.exists():
        return False
    try:
        peek = json.loads(creds_path.read_text(encoding="utf-8"))
        return peek.get("type") == "service_account"
    except Exception:
        return False


def _http_error_reason(error: HttpError) -> str:
    try:
        data = json.loads(error.content.decode())
        errs = data.get("error", {}).get("errors", []) or []
        if errs:
            return str(errs[0].get("reason", ""))
    except Exception:
        pass
    return ""


def extract_meet_link(event: Dict[str, Any]) -> Optional[str]:
    """Pull Google Meet URL from an event resource."""
    if not event:
        return None
    link = event.get("hangoutLink")
    if link:
        return link
    conf = event.get("conferenceData") or {}
    for ep in conf.get("entryPoints") or []:
        uri = (ep.get("uri") or "").strip()
        if uri and ep.get("entryPointType") in ("video", "more", None):
            return uri
    return None


def _to_utc_gcal(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_add_to_calendar_url(
    *,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    details: str = "",
    location: str = "",
) -> str:
    """Public Google Calendar 'Add event' link for candidates."""
    dates = f"{_to_utc_gcal(start_dt)}/{_to_utc_gcal(end_dt)}"
    params = (
        f"action=TEMPLATE&text={quote(title)}&dates={dates}"
        f"&details={quote(details)}&location={quote(location)}"
    )
    return f"https://calendar.google.com/calendar/render?{params}"


def _meet_create_request() -> Dict[str, Any]:
    return {
        "createRequest": {
            "requestId": f"meet-{uuid.uuid4().hex[:16]}",
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _fetch_event(service, calendar_id: str, event_id: str) -> Dict[str, Any]:
    return (
        service.events()
        .get(calendarId=calendar_id, eventId=event_id, conferenceDataVersion=1)
        .execute()
    )


def ensure_event_has_meet(service, calendar_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Google Meet is provisioned asynchronously; re-fetch and patch if missing.
    """
    event_id = event.get("id")
    if not event_id:
        return event

    meet = extract_meet_link(event)
    if meet:
        return event

    # Try attaching Meet (service accounts on shared calendars often need a patch)
    try:
        event = (
            service.events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body={"conferenceData": _meet_create_request()},
                conferenceDataVersion=1,
            )
            .execute()
        )
        meet = extract_meet_link(event)
        if meet:
            print(f"[CALENDAR] Meet link attached: {meet}")
            return event
    except HttpError as patch_err:
        print(f"[CALENDAR] Patch Meet failed: {patch_err}")

    for attempt in range(5):
        time.sleep(1.5 if attempt else 0.5)
        try:
            event = _fetch_event(service, calendar_id, event_id)
        except Exception as fetch_err:
            print(f"[CALENDAR] Re-fetch event failed: {fetch_err}")
            break
        meet = extract_meet_link(event)
        if meet:
            print(f"[CALENDAR] Meet ready after poll ({attempt + 1}): {meet}")
            return event
        conf = event.get("conferenceData") or {}
        status = (conf.get("createRequest") or {}).get("status", {}).get("statusCode")
        if status == "failure":
            print(f"[CALENDAR] Meet provisioning failed: {conf}")
            break

    print("[CALENDAR] No Meet link on event; calendar htmlLink will be used in email.")
    return event


def _insert_event(
    service,
    calendar_id: str,
    event_body: Dict[str, Any],
    *,
    send_updates: str,
    with_conference: bool,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "calendarId": calendar_id,
        "body": event_body,
        "sendUpdates": send_updates,
    }
    if with_conference and "conferenceData" in event_body:
        kwargs["conferenceDataVersion"] = 1
    return service.events().insert(**kwargs).execute()


def create_calendar_event(
    summary: str,
    description: str,
    start_dt: datetime,
    end_dt: datetime,
    organizer_email: str,
    attendees_emails: List[str],
    timezone: str = "Asia/Kolkata",
    send_updates: str = "none"
) -> Dict[str, Any]:
    """
    Create a Google Calendar event with a Meet conference and return event data.

    Service accounts cannot add attendees without Domain-Wide Delegation. When using
    a service account on recruit@'s shared calendar, we create the event without API
    attendees (sendUpdates=none) and list guests in the description; confirmation
    email still goes to the candidate via SMTP.

    Returns event resource (dict) on success.
    """
    try:
        service = get_calendar_service()
        calendar_id = (organizer_email or CALENDAR_EMAIL).strip()
        unique_attendees = list(
            dict.fromkeys(e.strip().lower() for e in (attendees_emails or []) if e and e.strip())
        )

        use_sa = calendar_auth_is_service_account()
        if use_sa and unique_attendees:
            guest_lines = "\n".join(f"- {e}" for e in unique_attendees)
            description = (
                f"{description}\n\n"
                f"Guests (invited by email, not Calendar API — service account limit):\n{guest_lines}"
            ).strip()

        def build_body(*, include_attendees: bool) -> Dict[str, Any]:
            body: Dict[str, Any] = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
                "conferenceData": _meet_create_request(),
            }
            if include_attendees and unique_attendees:
                body["attendees"] = [
                    {"email": e, "responseStatus": "needsAction"} for e in unique_attendees
                ]
            return body

        # SA: never pass attendees to Calendar API (403 forbiddenForServiceAccounts)
        include_attendees = bool(unique_attendees) and not use_sa
        effective_send = "none" if use_sa else send_updates

        event_body = build_body(include_attendees=include_attendees)

        try:
            event = _insert_event(
                service,
                calendar_id,
                event_body,
                send_updates=effective_send,
                with_conference=True,
            )
            return ensure_event_has_meet(service, calendar_id, event)
        except HttpError as e:
            reason = _http_error_reason(e)
            if reason == "forbiddenForServiceAccounts" or "forbiddenForServiceAccounts" in str(e):
                print(
                    "[CALENDAR] Service account cannot invite attendees; "
                    "creating event on shared calendar without API guests."
                )
                event_body = build_body(include_attendees=False)
                event = _insert_event(
                    service,
                    calendar_id,
                    event_body,
                    send_updates="none",
                    with_conference=True,
                )
                return ensure_event_has_meet(service, calendar_id, event)
            if "conferenceData" in str(e):
                print(f"[CALENDAR] Meet create failed, retrying without conference: {e}")
                event_body = build_body(include_attendees=include_attendees)
                del event_body["conferenceData"]
                event = _insert_event(
                    service,
                    calendar_id,
                    event_body,
                    send_updates=effective_send,
                    with_conference=False,
                )
                return ensure_event_has_meet(service, calendar_id, event)
            error_msg = (
                f"Google Calendar API error: {e.resp.status} - "
                f"{e.content.decode() if hasattr(e, 'content') else str(e)}"
            )
            raise Exception(error_msg) from e

    except HttpError as error:
        error_msg = (
            f"Google Calendar API error: {error.resp.status} - "
            f"{error.content.decode() if hasattr(error, 'content') else str(error)}"
        )
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"Error creating calendar event: {str(e)}")

