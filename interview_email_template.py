# interview_email_template.py
"""
Email templates for interview scheduling.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from link_auth import with_candidate_token


def generate_interview_slots_email(
    candidate_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    interview_id: str,
    outreach_id: str,
    date: datetime,
    time_slots: List[Dict[str, Any]],
    base_url: str,
    company_name: str,
    round_name: str = "Interview",
    interviewer_email: str = None
) -> Dict[str, str]:
    """
    Generate personalized interview scheduling email with time slots.
    
    Args:
        candidate_data: Dictionary with candidate information
        jd_data: Dictionary with job description information
        interview_id: UUID of the interview record
        date: Date of the interview
        time_slots: List of available time slots
        base_url: Base URL for confirmation links
        company_name: Company name
        round_name: Name of the interview round (e.g., "Technical Round", "HR Round")
    
    Returns:
        Dictionary with 'subject' and 'body' keys
    """
    candidate_name = candidate_data.get('candidate_name', 'Candidate')
    cand_email = (candidate_data.get("email") or "").strip()
    role = jd_data.get('role', 'Position')
    
    # Generate slot options HTML
    slots_html = ""
    for idx, slot in enumerate(time_slots, 1):
        slot_date = slot['start_time'].strftime('%A, %B %d')
        start_time = slot['start_time'].strftime('%I:%M %p').lstrip('0')
        end_time = slot['end_time'].strftime('%I:%M %p').lstrip('0')
        slot_id = f"slot{idx}"
        
        # Signed link: only the candidate in To (outreach email) can select a slot.
        confirm_base = (
            f"{base_url}/confirm-interview/{interview_id}"
            f"?slot={slot_id}&outreach_id={outreach_id}"
        )
        confirm_url = (
            with_candidate_token(confirm_base, outreach_id, cand_email)
            if cand_email
            else confirm_base
        )
        
        slots_html += f"""
            <div class="slot-option">
                <strong>Option {idx}: {slot_date}</strong><br>
                <span>{start_time} - {end_time}</span><br>
                <a href="{confirm_url}" class="slot-button">Select This Time</a>
            </div>
        """
    
    subject = f"{round_name} Invitation - {role} at {company_name}"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                background-color: #f5f5f5;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 30px;
                border-radius: 8px;
            }}
            h2 {{
                color: #333;
                font-size: 18px;
                margin-top: 20px;
                margin-bottom: 10px;
            }}
            .slot-button {{
                display: inline-block;
                padding: 12px 30px;
                background-color: #4CAF50;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin-top: 10px;
            }}
            .slot-button:hover {{
                background-color: #45a049;
            }}
            .slot-option {{
                margin: 15px 0;
                padding: 15px;
                background-color: #f8f9fa;
                border-left: 4px solid #4CAF50;
                border-radius: 4px;
            }}
            .warning-box {{
                margin-top: 30px;
                padding: 15px;
                background-color: #fff3cd;
                border-left: 4px solid #ffc107;
                border-radius: 4px;
                font-size: 14px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e0e0e0;
                font-size: 14px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Dear {candidate_name},</p>
            
            <p>Congratulations! We were impressed with your profile and would like to invite you for an interview for the <strong>{role}</strong> position at <strong>{company_name}</strong>.</p>
            
            <h2>⏰ Available Time Slots</h2>
            <p>Please select one of the following time slots that works best for you:</p>
            
            {slots_html}
            
            <div class="warning-box">
                <strong>⚠️ Important:</strong> Please confirm your preferred time slot by clicking one of the buttons above. Slots are available on a first-come, first-served basis.
            </div>
            
            <div class="footer">
                <p>If none of these times work for you, please reply to this email and we'll try to accommodate your schedule.</p>
                {"<p><strong>Interviewer:</strong> " + interviewer_email + "</p>" if interviewer_email else ""}
                <p>We look forward to speaking with you!</p>
                <p style="margin-top: 20px; margin-bottom: 5px;">Best regards,</p>
                <p style="margin: 0;"><strong>{company_name} Recruitment Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return {
        "subject": subject,
        "body": body
    }


def generate_interviewer_approval_email(
    candidate_name: str,
    jd_title: str,
    interview_date: str,
    interview_time: str,
    interview_id: str,
    base_url: str,
    round_name: str = "Interview"
) -> Dict[str, str]:
    """
    Generate email to interviewer to approve or reject a proposed time slot.
    """
    approve_url = f"{base_url}/interviewer/response/{interview_id}?action=approve"
    reject_url = f"{base_url}/interviewer/response/{interview_id}?action=reject"
    
    subject = f"Action Required: {round_name} Request for {candidate_name}"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; text-align: center; }}
            .details {{ margin: 20px 0; padding: 20px; background-color: #e9ecef; border-radius: 5px; }}
            .actions {{ margin-top: 30px; text-align: center; }}
            .btn {{ display: inline-block; padding: 12px 24px; margin: 0 10px; text-decoration: none; border-radius: 5px; font-weight: bold; color: white; }}
            .btn-approve {{ background-color: #28a745; }}
            .btn-reject {{ background-color: #dc3545; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>{round_name} Request</h2>
            </div>
            
            <p>Hi,</p>
            
            <p>Candidate <strong>{candidate_name}</strong> has selected a time slot for the <strong>{jd_title}</strong> position.</p>
            
            <div class="details">
                <p><strong>Date:</strong> {interview_date}</p>
                <p><strong>Time:</strong> {interview_time}</p>
            </div>
            
            <p>Are you available to take this interview?</p>
            
            <div class="actions">
                <a href="{approve_url}" class="btn btn-approve">YES - Confirm Interview</a>
                <a href="{reject_url}" class="btn btn-reject">NO - Reschedule</a>
            </div>
            
            <p style="margin-top: 30px; font-size: 12px; color: #666;">
                Clicking YES will automatically send a calendar invite to both you and the candidate.<br>
                Clicking NO will allow you to propose a new time.
            </p>
        </div>
    </body>
    </html>
    """
    
    return {
        "subject": subject,
        "body": body
    }


def generate_reschedule_proposal_email(
    candidate_name: str,
    jd_title: str,
    new_date: str,
    new_time: str,
    interview_id: str,
    base_url: str,
    company_name: str
) -> Dict[str, str]:
    """
    Generate email to candidate with interviewer's proposed new time.
    Candidate can either confirm or request a different time.
    """
    accept_url = f"{base_url}/candidate/accept-reschedule/{interview_id}"
    decline_url = f"{base_url}/candidate/decline-reschedule/{interview_id}"
    
    subject = f"Interview Reschedule Request - {jd_title} at {company_name}"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .details {{ margin: 20px 0; padding: 20px; background-color: #e3f2fd; border-radius: 5px; border-left: 4px solid #2196f3; }}
            .actions {{ margin-top: 30px; text-align: center; }}
            .btn {{ display: inline-block; padding: 12px 24px; margin: 0 10px; text-decoration: none; border-radius: 5px; font-weight: bold; color: white; }}
            .btn-confirm {{ background-color: #28a745; }}
            .btn-decline {{ background-color: #dc3545; }}
            .btn-confirm:hover {{ background-color: #218838; }}
            .btn-decline:hover {{ background-color: #c82333; }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Dear {candidate_name},</p>
            
            <p>Regarding your interview for the <strong>{jd_title}</strong> position.</p>
            
            <p>The interviewer has requested to reschedule the interview to the following time:</p>
            
            <div class="details">
                <p><strong>New Date:</strong> {new_date}</p>
                <p><strong>New Time:</strong> {new_time}</p>
            </div>
            
            <p>Please let us know if this new time works for you:</p>
            
            <div class="actions">
                <a href="{accept_url}" class="btn btn-confirm">✓ Confirm New Time</a>
                <a href="{decline_url}" class="btn btn-decline">✗ Request Different Time</a>
            </div>
            
            <p style="margin-top: 30px; font-size: 14px; color: #666;">
                If you click "Request Different Time", we will send you alternative time slots to choose from.
            </p>
            
            <p>Best regards,<br>{company_name} Recruitment Team</p>
        </div>
    </body>
    </html>
    """
    
    return {
        "subject": subject,
        "body": body
    }

