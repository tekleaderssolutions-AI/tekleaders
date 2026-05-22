# interview_scheduler.py
"""
Interview scheduling agent that coordinates calendar availability and candidate outreach.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import uuid
import json

from db import get_connection
from google_calendar import get_available_slots
from interview_email_template import (
    generate_interview_slots_email,
    generate_interviewer_approval_email,
    generate_reschedule_proposal_email
)
from email_sender import send_email
from config import (
    BASE_URL,
    COMPANY_NAME,
    INTERVIEWER_EMAIL,
    HR_INTERVIEWER_EMAIL,
    CALENDAR_EMAIL,
    INTERVIEW_DURATION_MINUTES,
)
from link_auth import verify_candidate_token
def _generate_default_slots(interview_date: datetime, num_slots: int) -> List[Dict[str, datetime]]:
    """
    Build fallback slots (10:00, 11:30, 2:00, 3:30) when calendar API fails.
    """
    preset_times = [
        (10, 0),
        (11, 30),
        (14, 0),
        (15, 30)
    ]
    slots = []
    for hour, minute in preset_times[:num_slots]:
        start = interview_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(minutes=INTERVIEW_DURATION_MINUTES)
        slots.append({"start_time": start, "end_time": end})
    return slots


def _fetch_time_slots(interview_date: datetime, num_slots: int) -> List[Dict[str, datetime]]:
    """
    Try fetching real Google Calendar slots, fallback to defaults on failure.
    """
    try:
        slots = get_available_slots(interview_date, num_slots)
        if slots:
            return slots
        print("[INTERVIEW SCHEDULER] Calendar returned no slots, falling back to defaults")
    except Exception as calendar_error:
        print(f"[INTERVIEW SCHEDULER] Calendar availability failed ({calendar_error}), using defaults")
    return _generate_default_slots(interview_date, num_slots)


def find_first_available_date(num_slots=3, max_days_ahead=30, excluded_dates=None):
    """
    Find the first date with available interview slots, skipping excluded dates.
    
    Args:
        num_slots: Number of slots needed (default: 3)
        max_days_ahead: Maximum days to search ahead (default: 30)
        excluded_dates: List of dates to skip (optional)
    
    Returns:
        datetime object of first available date, or None if no date found
    """
    if excluded_dates is None:
        excluded_dates = []
        
    current_date = datetime.now() + timedelta(days=1)  # Start from tomorrow
    end_date = datetime.now() + timedelta(days=max_days_ahead)
    
    while current_date <= end_date:
        # Skip weekends
        if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            current_date += timedelta(days=1)
            continue
            
        # Skip excluded dates
        if current_date.date() in excluded_dates:
            print(f"Skipping {current_date.date()} (already scheduled)")
            current_date += timedelta(days=1)
            continue
        
        try:
            slots = get_available_slots(current_date, num_slots)
            if len(slots) >= num_slots:
                return current_date
        except Exception as e:
            print(f"Error checking {current_date.date()}: {e}")
        
        current_date += timedelta(days=1)
    
    return None


def schedule_interview_for_single_candidate(
    outreach_id: str,
    num_slots: int = 3
) -> Dict[str, Any]:
    """
    Schedule interview for a single candidate (used for automatic scheduling).
    Finds the first available date automatically.
    
    Args:
        outreach_id: Outreach ID of the candidate
        num_slots: Number of time slots to offer (default: 3)
    
    Returns:
        Dictionary with scheduling result
    """
    conn = get_connection()
    
    try:
        cur = conn.cursor()
        
        # Fetch candidate and JD details
        cur.execute(
            """
            SELECT 
                co.id as outreach_id,
                co.resume_id,
                co.candidate_email,
                co.candidate_name,
                co.jd_id,
                r.canonical_json,
                m.title,
                m.canonical_json as jd_json
            FROM candidate_outreach co
            JOIN resumes r ON r.id = co.resume_id
            JOIN memories m ON m.id = co.jd_id
            WHERE co.id = %s
            """,
            [outreach_id]
        )
        
        row = cur.fetchone()
        
        if not row:
            return {"error": "Outreach record not found"}
        
        outreach_id, resume_id, email, name, jd_id, resume_json, jd_title, jd_json = row
        
        
        # Check if already scheduled
        cur.execute(
            """
            SELECT id FROM interview_schedules
            WHERE outreach_id = %s AND status NOT IN ('cancelled', 'declined')
            """,
            [outreach_id]
        )
        
        if cur.fetchone():
            return {"message": "Interview already scheduled for this candidate"}
        
        # Find first available date (allow multiple interviews per day)
        # Simply find the next business day (excluding weekends)
        interview_date = datetime.now() + timedelta(days=1)
        while interview_date.weekday() >= 5:  # Skip weekends
            interview_date += timedelta(days=1)
        
        # Fetch available time slots with fallback
        time_slots = _fetch_time_slots(interview_date, num_slots)
        if not time_slots:
            return {"error": "No available time slots found"}
        
        # Prepare data
        interview_id = str(uuid.uuid4())
        
        candidate_data = {
            "candidate_name": name,
            "email": email,
            "canonical_json": resume_json
        }
        
        jd_data = {
            "id": jd_id,
            "title": jd_title,
            "canonical_json": jd_json,
            "role": jd_json.get("role") if jd_json else "Position"
        }
        
        # Generate email with time slots
        email_content = generate_interview_slots_email(
            candidate_data=candidate_data,
            jd_data=jd_data,
            interview_id=interview_id,
            outreach_id=outreach_id,
            date=interview_date,
            time_slots=time_slots,
            base_url=BASE_URL,
            company_name=COMPANY_NAME
        )
        
        # Send email without interviewer CC'd (as requested)
        send_result = send_email(
            to_email=email,
            subject=email_content["subject"],
            html_body=email_content["body"]
        )
        
        if send_result["success"]:
            # Store interview schedule in database
            proposed_slots_data = {
                "slot1": {
                    "start": time_slots[0]['start_time'].isoformat(),
                    "end": time_slots[0]['end_time'].isoformat()
                },
                "slot2": {
                    "start": time_slots[1]['start_time'].isoformat(),
                    "end": time_slots[1]['end_time'].isoformat()
                } if len(time_slots) > 1 else None,
                "slot3": {
                    "start": time_slots[2]['start_time'].isoformat(),
                    "end": time_slots[2]['end_time'].isoformat()
                } if len(time_slots) > 2 else None
            }
            
            cur.execute(
                """
                INSERT INTO interview_schedules 
                (id, resume_id, jd_id, outreach_id, interview_date, 
                 proposed_slots, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                """,
                [
                    interview_id,
                    resume_id,
                    jd_id,
                    outreach_id,
                    interview_date.date(),
                    json.dumps(proposed_slots_data),
                    'pending'
                ]
            )
            conn.commit()
            
            return {
                "success": True,
                "interview_id": interview_id,
                "interview_date": interview_date.strftime('%Y-%m-%d'),
                "candidate_name": name,
                "email": email
            }
        else:
            return {"error": send_result["message"]}
            
    except Exception as e:
        return {"error": f"Error scheduling interview: {str(e)}"}
    finally:
        conn.close()


def schedule_interviews_for_interested_candidates(
    jd_id: str,
    interview_date: datetime,
    num_slots: int = 3
) -> Dict[str, Any]:
    """
    Schedule interviews for all interested candidates for a given JD.
    
    Args:
        jd_id: Job description ID
        interview_date: Date for the interviews
        num_slots: Number of time slots to offer (default: 3)
    
    Returns:
        Dictionary with scheduling results
    """
    conn = get_connection()
    results = []
    
    try:
        cur = conn.cursor()
        
        # Fetch JD details
        cur.execute(
            "SELECT id, title, canonical_json FROM memories WHERE id = %s",
            [jd_id]
        )
        jd_row = cur.fetchone()
        
        if not jd_row:
            return {"error": f"JD not found: {jd_id}"}
        
        jd_data = {
            "id": jd_row[0],
            "title": jd_row[1],
            "canonical_json": jd_row[2],
            "role": jd_row[2].get("role") if jd_row[2] else "Position"
        }
        
        # Fetch available time slots (fallback to defaults if Calendar fails)
        time_slots = _fetch_time_slots(interview_date, num_slots)
        if not time_slots:
            return {"error": "No available time slots found for the specified date"}
        
        # Fetch interested candidates
        cur.execute(
            """
            SELECT 
                co.id as outreach_id,
                co.resume_id,
                co.candidate_email,
                co.candidate_name,
                r.canonical_json
            FROM candidate_outreach co
            JOIN resumes r ON r.id = co.resume_id
            WHERE co.jd_id = %s 
              AND co.acknowledgement = 'interested'
              AND co.resume_id NOT IN (
                  SELECT resume_id FROM interview_schedules 
                  WHERE jd_id = %s AND status NOT IN ('cancelled', 'declined')
              )
            """,
            [jd_id, jd_id]
        )
        
        interested_candidates = cur.fetchall()
        
        if not interested_candidates:
            return {
                "message": "No interested candidates found or all have already been scheduled",
                "scheduled": 0
            }
        
        # Schedule interview for each interested candidate
        for outreach_id, resume_id, email, name, resume_json in interested_candidates:
            try:
                interview_id = str(uuid.uuid4())
                
                candidate_data = {
                    "candidate_name": name,
                    "email": email,
                    "canonical_json": resume_json
                }
                
                # Generate email with time slots
                email_content = generate_interview_slots_email(
                    candidate_data=candidate_data,
                    jd_data=jd_data,
                    interview_id=interview_id,
                    outreach_id=outreach_id,
                    date=interview_date,
                    time_slots=time_slots,
                    base_url=BASE_URL,
                    company_name=COMPANY_NAME
                )
                
                # Send email without interviewer CC'd (as requested)
                send_result = send_email(
                    to_email=email,
                    subject=email_content["subject"],
                    html_body=email_content["body"]
                )
                
                if send_result["success"]:
                    # Store interview schedule in database
                    
                    proposed_slots_data = {
                        "slot1": {
                            "start": time_slots[0]['start_time'].isoformat(),
                            "end": time_slots[0]['end_time'].isoformat()
                        },
                        "slot2": {
                            "start": time_slots[1]['start_time'].isoformat(),
                            "end": time_slots[1]['end_time'].isoformat()
                        } if len(time_slots) > 1 else None,
                        "slot3": {
                            "start": time_slots[2]['start_time'].isoformat(),
                            "end": time_slots[2]['end_time'].isoformat()
                        } if len(time_slots) > 2 else None
                    }
                    
                    cur.execute(
                        """
                        INSERT INTO interview_schedules 
                        (id, resume_id, jd_id, outreach_id, interview_date, 
                         proposed_slots, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
                        """,
                        [
                            interview_id,
                            resume_id,
                            jd_id,
                            outreach_id,
                            interview_date.date(),
                            json.dumps(proposed_slots_data),
                            'pending'
                        ]
                    )
                    conn.commit()
                    
                    results.append({
                        "resume_id": resume_id,
                        "candidate_name": name,
                        "email": email,
                        "status": "success",
                        "interview_id": interview_id
                    })
                else:
                    results.append({
                        "resume_id": resume_id,
                        "candidate_name": name,
                        "email": email,
                        "status": "error",
                        "message": send_result["message"]
                    })
                    
            except Exception as e:
                results.append({
                    "resume_id": resume_id,
                    "candidate_name": name,
                    "status": "error",
                    "message": str(e)
                })
        
        cur.close()
        
        return {
            "total": len(interested_candidates),
            "scheduled": len([r for r in results if r["status"] == "success"]),
            "failed": len([r for r in results if r["status"] == "error"]),
            "results": results
        }
        
    except Exception as e:
        return {"error": f"Error scheduling interviews: {str(e)}"}
    finally:
        conn.close()


def confirm_interview_slot(
    interview_id: str,
    slot_id: str,
    outreach_id: str | None = None,
    token: str | None = None,
) -> Dict[str, Any]:
    """
    Confirm a candidate's selected interview time slot.
    Automatically creates a Google Calendar event and blocks both participants' calendars.
    Sends final confirmation emails to both candidate and interviewer.
    
    Args:
        interview_id: UUID of the interview
        slot_id: Selected slot ID (slot1, slot2, or slot3)
        outreach_id: Optional outreach token for authorization
    
    Returns:
        Dictionary with confirmation status, event link, and meet link
    """
    from google_calendar import create_calendar_event
    from email_sender import send_email
    from datetime import datetime
    
    conn = get_connection()
    
    try:
        cur = conn.cursor()
        
        # Fetch interview details (include outreach_id to validate requester)
        cur.execute(
            """
            SELECT id, resume_id, jd_id, proposed_slots, status, outreach_id, interview_date, interview_round
            FROM interview_schedules
            WHERE id = %s
            """,
            [interview_id]
        )
        
        row = cur.fetchone()
        
        if not row:
            return {"error": "Interview not found"}
        
        interview_id_db, resume_id, jd_id, proposed_slots, status, outreach_id_db, interview_date, interview_round = row
        
        if status == 'confirmed':
            return {"error": "Interview already confirmed"}

        if not outreach_id or not token:
            return {
                "error": "Invalid link. Please use the interview email sent to you — only the invited candidate can select a time slot.",
            }

        if str(outreach_id) != str(outreach_id_db):
            return {"error": "Unauthorized: this interview invitation was not sent to you."}

        cur.execute(
            "SELECT candidate_email FROM candidate_outreach WHERE id = %s",
            [outreach_id],
        )
        outreach_row = cur.fetchone()
        if not outreach_row:
            return {"error": "Outreach record not found"}
        outreach_email = (outreach_row[0] or "").strip()
        if not verify_candidate_token(outreach_id, outreach_email, token):
            return {
                "error": "Unauthorized: only the candidate who received this email can confirm a slot.",
            }

        if slot_id not in proposed_slots or proposed_slots[slot_id] is None:
            return {"error": "Invalid slot selection"}
        
        selected_slot = proposed_slots[slot_id]
        start_time_str = selected_slot['start']
        end_time_str = selected_slot['end']
        
        # Parse datetime strings and ensure they have timezone info
        try:
            start_dt = datetime.fromisoformat(start_time_str)
            end_dt = datetime.fromisoformat(end_time_str)
            
            # If datetimes are naive (no timezone), add UTC+5:30 (Asia/Kolkata) offset
            if start_dt.tzinfo is None:
                from datetime import timezone as dt_timezone
                kolkata_tz = dt_timezone(timedelta(hours=5, minutes=30))
                start_dt = start_dt.replace(tzinfo=kolkata_tz)
                end_dt = end_dt.replace(tzinfo=kolkata_tz)
        except ValueError as ve:
            return {"error": f"Invalid datetime format in selected slot: {str(ve)}"}
        
        # Fetch candidate and JD details
        cur.execute(
            "SELECT candidate_name, email FROM resumes WHERE id = %s",
            [resume_id]
        )
        cand_row = cur.fetchone()
        if not cand_row:
            return {"error": "Candidate not found"}
        candidate_name, candidate_email = cand_row
        if (candidate_email or "").strip().lower() != outreach_email.lower():
            return {
                "error": "Unauthorized: slot confirmation must be completed by the invited candidate only.",
            }

        cur.execute(
            "SELECT title, canonical_json FROM memories WHERE id = %s",
            [jd_id]
        )
        jd_row = cur.fetchone()
        if not jd_row:
            return {"error": "JD not found"}
        jd_title, jd_json = jd_row
        
        # Update interview record to waiting_approval
        cur.execute(
            """
            UPDATE interview_schedules
            SET selected_slot = %s,
                confirmed_slot_time = %s,
                status = 'waiting_approval',
                updated_at = NOW()
            WHERE id = %s
            """,
            [slot_id, start_time_str, interview_id]
        )
        
        conn.commit()
        
        # Generate approval email for interviewer
        round_name = "HR Round" if (interview_round and interview_round == 2) else "Technical Round"
        email_content = generate_interviewer_approval_email(
            candidate_name=candidate_name,
            jd_title=jd_title,
            interview_date=start_dt.strftime('%A, %B %d, %Y'),
            interview_time=f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}",
            interview_id=interview_id,
            base_url=BASE_URL,
            round_name=round_name
        )
        
        # Send email to appropriate interviewer based on round
        interviewer_email = HR_INTERVIEWER_EMAIL if (interview_round and interview_round == 2) else INTERVIEWER_EMAIL
        send_email(
            to_email=interviewer_email,
            subject=email_content["subject"],
            html_body=email_content["body"]
        )
        
        cur.close()
        
        return {
            "success": True,
            "message": "Interview slot selected. Waiting for interviewer approval.",
            "status": "waiting_approval",
            "slot": selected_slot
        }
        
    except Exception as e:
        return {"error": f"Error confirming interview: {str(e)}"}
    finally:
        conn.close()


def approve_interview(interview_id: str) -> Dict[str, Any]:
    """
    Approve an interview slot (called by interviewer).
    Creates calendar event and sends confirmation to candidate.
    """
    from google_calendar import create_calendar_event
    from email_sender import send_email
    from datetime import datetime, timezone
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Fetch interview details
        cur.execute(
            """
            SELECT id, resume_id, jd_id, confirmed_slot_time, status, interview_round
            FROM interview_schedules
            WHERE id = %s
            """,
            [interview_id]
        )
        row = cur.fetchone()
        
        if not row:
            return {"error": "Interview not found"}
            
        interview_id_db, resume_id, jd_id, start_time_str, status, interview_round = row
        
        if status == 'scheduled':
             return {"message": "Interview already scheduled"}
             
        if not start_time_str:
            return {"error": "No slot selected to approve"}

        # Parse datetime
        try:
            if isinstance(start_time_str, str):
                start_dt = datetime.fromisoformat(start_time_str)
            else:
                # If it's already a datetime object (e.g. from Postgres TIMESTAMP column)
                start_dt = start_time_str
                
            # If naive, assume it's already in correct local time but needs timezone info for Google Calendar
            if start_dt.tzinfo is None:
                kolkata_tz = timezone(timedelta(hours=5, minutes=30))
                start_dt = start_dt.replace(tzinfo=kolkata_tz)
            
            end_dt = start_dt + timedelta(minutes=INTERVIEW_DURATION_MINUTES)
        except ValueError as ve:
            return {"error": f"Invalid datetime format: {str(ve)}"}

        # Fetch candidate and JD details
        cur.execute("SELECT candidate_name, email FROM resumes WHERE id = %s", [resume_id])
        cand_row = cur.fetchone()
        if not cand_row: return {"error": "Candidate not found"}
        candidate_name, candidate_email = cand_row
        
        cur.execute("SELECT title FROM memories WHERE id = %s", [jd_id])
        jd_row = cur.fetchone()
        if not jd_row: return {"error": "JD not found"}
        jd_title = jd_row[0]
        
        # Create Google Calendar event
        try:
            event_summary = f"Interview: {candidate_name} - {jd_title}"
            event_description = f"Scheduled interview for {candidate_name} for the {jd_title} position."
            
            # Use HR interviewer email for Round 2, otherwise use regular interviewer
            organizer = CALENDAR_EMAIL

            event = create_calendar_event(
                summary=event_summary,
                description=event_description,
                start_dt=start_dt,
                end_dt=end_dt,
                organizer_email=organizer,
                attendees_emails=[candidate_email, organizer],
                timezone="Asia/Kolkata",
                send_updates="all"
            )
            
            event_link = event.get('htmlLink')
            meet_link = event.get('hangoutLink')
            if not meet_link:
                conf = event.get('conferenceData', {})
                entry_points = conf.get('entryPoints', []) if conf else []
                if entry_points:
                    meet_link = entry_points[0].get('uri')
                    
        except Exception as e:
            return {"error": f"Failed to create calendar event: {str(e)}"}
            
        # Update status to scheduled and store feedback form link
        from config import FEEDBACK_FORM_LINK
        
        # Determine feedback link based on round
        feedback_link = FEEDBACK_FORM_LINK
        if interview_round and interview_round == 2:
            # HR Feedback Form
            feedback_link = f"{BASE_URL}/static/hr-feedback-form.html"
        
        cur.execute(
            """
            UPDATE interview_schedules
            SET status = 'scheduled',
                event_id = %s,
                event_link = %s,
                meet_link = %s,
                feedback_form_link = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            [event.get('id'), event_link, meet_link, feedback_link, interview_id]
        )
        conn.commit()
        
        # Send confirmation email to candidate
        email_subject = f"Interview Confirmed - {jd_title}"
        email_body = f"""
        <html>
        <body>
            <p>Hi {candidate_name},</p>
            <p>Your interview for <strong>{jd_title}</strong> has been confirmed by the interviewer.</p>
            <p><strong>Date:</strong> {start_dt.strftime('%A, %B %d, %Y at %I:%M %p')}</p>
            <p><strong>Link:</strong> <a href="{meet_link}">{meet_link}</a></p>
            <p>Good luck!</p>
        </body>
        </html>
        """
        
        send_email(
            to_email=candidate_email,
            subject=email_subject,
            html_body=email_body,
            cc_email=organizer  # Use the same organizer email (HR or Technical interviewer)
        )
        
        return {"success": True, "meet_link": meet_link}
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def process_reschedule_request(interview_id: str, new_date_str: str, new_time_str: str) -> Dict[str, Any]:
    """
    Process interviewer's request to reschedule.
    Sends email to candidate with new proposed time.
    """
    from email_sender import send_email
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Fetch details
        cur.execute(
            """
            SELECT resume_id, jd_id FROM interview_schedules WHERE id = %s
            """,
            [interview_id]
        )
        row = cur.fetchone()
        if not row: return {"error": "Interview not found"}
        resume_id, jd_id = row
        
        # Fetch candidate/JD
        cur.execute("SELECT candidate_name, email FROM resumes WHERE id = %s", [resume_id])
        cand_row = cur.fetchone()
        candidate_name, candidate_email = cand_row
        
        cur.execute("SELECT title FROM memories WHERE id = %s", [jd_id])
        jd_title = cur.fetchone()[0]
        
        # Update DB with new proposal
        # We'll store the new proposal in 'proposed_slots' as a special 'reschedule_proposal'
        # And update confirmed_slot_time to this new time (temporarily, pending confirmation)
        
        # Construct datetime from date and time strings
        # Input format expected: YYYY-MM-DD and HH:MM
        try:
            new_dt = datetime.strptime(f"{new_date_str} {new_time_str}", "%Y-%m-%d %H:%M")
            end_dt = new_dt + timedelta(minutes=INTERVIEW_DURATION_MINUTES)
        except ValueError:
            return {"error": "Invalid date/time format"}
            
        new_slot = {
            "start": new_dt.isoformat(),
            "end": end_dt.isoformat()
        }
        
        # Update DB
        cur.execute(
            """
            UPDATE interview_schedules
            SET status = 'pending_reschedule',
                confirmed_slot_time = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            [new_dt.isoformat(), interview_id]
        )
        conn.commit()
        
        # Send email to candidate
        email_content = generate_reschedule_proposal_email(
            candidate_name=candidate_name,
            jd_title=jd_title,
            new_date=new_dt.strftime('%A, %B %d, %Y'),
            new_time=new_dt.strftime('%I:%M %p'),
            interview_id=interview_id,
            base_url=BASE_URL,
            company_name=COMPANY_NAME
        )
        
        send_email(
            to_email=candidate_email,
            subject=email_content["subject"],
            html_body=email_content["body"]
        )
        
        return {"success": True}
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def _fetch_time_slots(date: datetime, num_slots: int = 3, calendar_email: str = None) -> List[Dict[str, datetime]]:
    """
    Fetch available time slots for a given date, with fallback to default slots.
    
    Args:
        date: Date to check
        num_slots: Number of slots needed
        calendar_email: Calendar to check (defaults to CALENDAR_EMAIL)
    
    Returns:
        List of slot dictionaries with start_time and end_time
    """
    try:
        slots = get_available_slots(date, num_slots, calendar_email=calendar_email)
        if slots and len(slots) >= num_slots:
            return slots
    except Exception as e:
        print(f"Calendar API failed for {date.date()}: {e}, using default slots")
    
    # Fallback to default slots
    return _generate_default_slots(date, num_slots)


def _find_diverse_time_slots(start_date: datetime, num_slots: int = 3, scan_days: int = 3, calendar_email: str = None) -> List[Dict[str, datetime]]:
    """
    Find slots across multiple days to give candidate date options.
    Tries to pick slots from different days.
    
    Args:
        start_date: Starting date for search
        num_slots: Number of slots to return
        scan_days: Number of days to scan
        calendar_email: Calendar to check availability (defaults to CALENDAR_EMAIL)
    """
    collected_slots = []
    current_date = start_date
    final_slots = []
    
    # scan next few days
    days_scanned = 0
    while days_scanned < scan_days:
        if current_date.weekday() < 5: # Skip weekends
            # Reuse fetch logic per day (tries calendar -> defaults)
            day_slots = _fetch_time_slots(current_date, num_slots, calendar_email=calendar_email)
            if day_slots:
                collected_slots.extend(day_slots)
        current_date += timedelta(days=1)
        days_scanned += 1
    
    # Sort by time
    collected_slots.sort(key=lambda x: x['start_time'])
    
    # Intelligent selection: Try to pick from different days first
    available_days = sorted(list(set(s['start_time'].date() for s in collected_slots)))
    
    if len(available_days) >= num_slots:
        # We have enough unique days, pick 1st slot from each of first N days
        for day in available_days[:num_slots]:
            # Find first slot for this day
            slot = next(s for s in collected_slots if s['start_time'].date() == day)
            final_slots.append(slot)
    else:
        # Not enough unique days, just take first N slots
        final_slots = collected_slots[:num_slots]
        
    return final_slots


def schedule_hr_round_interview(original_interview_id: str, num_slots: int = 3) -> Dict[str, Any]:
    """
    Schedule HR Round (Round 2) interview for a candidate who passed Round 1.
    Creates a new interview record with interview_round=2.
    
    Args:
        original_interview_id: UUID of the Round 1 interview
        num_slots: Number of time slots to offer
    
    Returns:
        Dictionary with scheduling result
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # 1. Fetch Round 1 details to verify eligibility and get data
        cur.execute("""
            SELECT 
                i.resume_id, i.jd_id, i.outreach_id,
                r.candidate_name, r.email, r.canonical_json,
                m.title, m.canonical_json as jd_json,
                i.hr_round_scheduled
            FROM interview_schedules i
            JOIN resumes r ON r.id = i.resume_id
            JOIN memories m ON m.id = i.jd_id
            WHERE i.id = %s
        """, [original_interview_id])
        
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Interview not found"}
            
        resume_id, jd_id, outreach_id, name, email, resume_json, jd_title, jd_json, already_scheduled = row
        
        if already_scheduled:
            return {"success": False, "error": "HR Round already scheduled for this candidate"}

        # 2. Check if a Round 2 interview record actually exists (double check)
        cur.execute("""
            SELECT id FROM interview_schedules 
            WHERE resume_id = %s AND jd_id = %s AND interview_round = 2 
            AND status NOT IN ('cancelled', 'declined')
        """, [resume_id, jd_id])
        
        if cur.fetchone():
            # Fix inconsistency if flag was false but record existed
            cur.execute("UPDATE interview_schedules SET hr_round_scheduled = TRUE WHERE id = %s", [original_interview_id])
            conn.commit()
            return {"success": False, "error": "HR Round already exists (status corrected)"}

        # 3. Find available slots on SAME DAY with different times
        start_date = datetime.now() + timedelta(days=1)
        while start_date.weekday() >= 5:  # ensure start is weekday
            start_date += timedelta(days=1)
            
        # For HR Round: Get multiple slots on the SAME day (different times)
        time_slots = _fetch_time_slots(start_date, num_slots, calendar_email=CALENDAR_EMAIL)
        
        if not time_slots:
            return {"success": False, "error": "No available time slots found"}

        # 4. Create new interview record for Round 2
        new_interview_id = str(uuid.uuid4())
        
        proposed_slots_data = {}
        for idx, slot in enumerate(time_slots, 1):
             proposed_slots_data[f"slot{idx}"] = {
                "start": slot['start_time'].isoformat(),
                "end": slot['end_time'].isoformat()
             }
        
        # Insert Round 2 record
        # Note: interview_date stored is the start_date we searched from, or first slot date.
        # It's less relevant now that slots are diverse, but required by schema.
        first_slot_date = time_slots[0]['start_time'].date()
        
        cur.execute("""
            INSERT INTO interview_schedules 
            (id, resume_id, jd_id, outreach_id, interview_date, 
             proposed_slots, status, interview_round, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending', 2, NOW())
        """, [
            new_interview_id, resume_id, jd_id, outreach_id, 
            first_slot_date, json.dumps(proposed_slots_data)
        ])
        
        # Mark Round 1 as having HR round scheduled
        cur.execute("""
            UPDATE interview_schedules 
            SET hr_round_scheduled = TRUE, updated_at = NOW() 
            WHERE id = %s
        """, [original_interview_id])
        
        conn.commit()
        
        # 5. Send Invite Email
        candidate_data = {
            "candidate_name": name,
            "email": email,
            "canonical_json": resume_json
        }
        
        jd_data = {
            "id": jd_id,
            "title": jd_title,
            "canonical_json": jd_json,
            "role": jd_json.get("role") if jd_json else "Position"
        }
        
        email_content = generate_interview_slots_email(
            candidate_data=candidate_data,
            jd_data=jd_data,
            interview_id=new_interview_id,
            outreach_id=outreach_id,
            date=start_date, # Passed but date header removed from template
            time_slots=time_slots,
            base_url=BASE_URL,
            company_name=COMPANY_NAME,
            round_name="HR Round",
            interviewer_email=HR_INTERVIEWER_EMAIL
        )
        
        send_result = send_email(
            to_email=email,
            subject=email_content["subject"],
            html_body=email_content["body"]
        )
        
        if send_result["success"]:
            return {
                "success": True,
                "interview_id": new_interview_id,
                "message": f"HR Round scheduled for {name}",
                "date": first_slot_date.strftime('%Y-%m-%d')
            }
        else:
            return {
                "success": True, 
                "warning": "Interview created but failed to send email", 
                "interview_id": new_interview_id
            }

    except Exception as e:
        conn.rollback()
        return {"success": False, "error": f"Error scheduling HR round: {str(e)}"}
    finally:
        conn.close()
