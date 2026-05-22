# mailing_agent.py
"""
Personalized recruitment emails — OpenAI only. Never includes match % in body.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from config import BASE_URL, COMPANY_NAME, OPENAI_API_KEY, OPENAI_CHAT_MODEL
from link_auth import with_candidate_token

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _reload_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def _api_key() -> str:
    _reload_env()
    key = (os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing in hiring/.env")
    return key


def _chat_model() -> str:
    _reload_env()
    return os.environ.get("OPENAI_CHAT_MODEL", OPENAI_CHAT_MODEL or "gpt-4o-mini")


def _as_list(items: Any, limit: int = 8) -> List[str]:
    if not items:
        return []
    out: List[str] = []
    if isinstance(items, str):
        for part in items.replace(";", ",").split(","):
            s = part.strip()
            if s:
                out.append(s)
    elif isinstance(items, list):
        for item in items[:limit]:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("title", "name", "skill", "company"):
                    if item.get(key):
                        out.append(str(item[key]).strip())
                        break
    return out[:limit]


def _experience_summary(canonical: Dict[str, Any]) -> str:
    we = canonical.get("work_experience") or canonical.get("experience") or []
    if not isinstance(we, list):
        return "Not specified"
    parts: List[str] = []
    for job in we[:4]:
        if not isinstance(job, dict):
            continue
        title = job.get("title") or ""
        company = job.get("company") or ""
        if title and company:
            parts.append(f"{title} at {company}")
        elif title:
            parts.append(title)
    return "; ".join(parts) if parts else "Not specified"


def _build_html_email(
    *,
    candidate_name: str,
    email_body_text: str,
    outreach_id: str,
    candidate_email: str,
) -> str:
    interested_base = f"{BASE_URL}/acknowledge/{outreach_id}?response=interested"
    not_interested_base = f"{BASE_URL}/acknowledge/{outreach_id}?response=not_interested"
    interested_link = with_candidate_token(interested_base, outreach_id, candidate_email)
    not_interested_link = with_candidate_token(not_interested_base, outreach_id, candidate_email)
    body_html = (email_body_text or "").replace("\n", "<br>")

    return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #2563eb; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 30px 20px; background-color: #f9fafb; }}
        .buttons {{ text-align: center; margin: 30px 0; }}
        .btn {{ display: inline-block; padding: 12px 30px; margin: 0 10px; text-decoration: none; border-radius: 5px; font-weight: bold; }}
        .btn-primary {{ background-color: #10b981; color: white; }}
        .btn-secondary {{ background-color: #6b7280; color: white; }}
        .footer {{ text-align: center; padding: 20px; color: #6b7280; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>{COMPANY_NAME}</h2>
            <p>Recruitment Team</p>
        </div>
        <div class="content">
            <p>Dear {candidate_name},</p>
            {body_html}
            <div class="buttons">
                <a href="{interested_link}" class="btn btn-primary">✓ Yes, I'm Interested</a>
                <a href="{not_interested_link}" class="btn btn-secondary">✗ Not Interested</a>
            </div>
            <p>Best regards,<br>
            {COMPANY_NAME} Recruitment Team</p>
        </div>
        <div class="footer">
            <p>This is an automated email from {COMPANY_NAME}. Please do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
"""


def _generate_body_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=_api_key())
    response = client.chat.completions.create(
        model=_chat_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return (response.choices[0].message.content or "").strip()


def generate_personalized_email(
    candidate_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    outreach_id: str,
    rank: int,
    ats_score: int,
) -> Dict[str, str]:
    """
    Generate a personalized recruitment email using OpenAI.
    ats_score and rank are stored in DB only — never shown in the email.
    """
    candidate_name = candidate_data.get("candidate_name", "Candidate")
    candidate_email = (candidate_data.get("email") or "").strip()
    role = jd_data.get("role") or jd_data.get("title") or "Position"

    canonical = candidate_data.get("canonical_json") or {}
    if not isinstance(canonical, dict):
        canonical = {}
    jd_canonical = jd_data.get("canonical_json") or {}
    if not isinstance(jd_canonical, dict):
        jd_canonical = {}

    skills = _as_list(canonical.get("skills"), 8)
    current_title = canonical.get("current_title") or candidate_data.get("current_title") or ""
    experience_summary = _experience_summary(canonical)
    primary_skills = _as_list(jd_canonical.get("primary_skills"), 10)
    secondary_skills = _as_list(jd_canonical.get("secondary_skills"), 6)
    responsibilities = _as_list(jd_canonical.get("responsibilities"), 5)
    location = jd_canonical.get("location") or ""

    scan_matched = _as_list(candidate_data.get("matched_skills"), 12)
    if scan_matched:
        skills = list(dict.fromkeys(scan_matched + skills))[:10]
    recruiter_note = (candidate_data.get("reason_to_select") or "").strip()

    prompt = f"""Write a personalized recruitment outreach email body (plain text, no subject line).

Company: {COMPANY_NAME}
Role: {role}
Location: {location or 'Not specified'}

Candidate:
- Name: {candidate_name}
- Current title: {current_title or 'Not specified'}
- Key skills: {', '.join(skills) if skills else 'Not specified'}
- Experience highlights: {experience_summary}

Job requirements:
- Primary skills: {', '.join(primary_skills) if primary_skills else 'Not specified'}
- Secondary skills: {', '.join(secondary_skills) if secondary_skills else 'Not specified'}
- Key responsibilities: {', '.join(responsibilities) if responsibilities else 'Not specified'}
- Skills that align with this role (from screening): {', '.join(scan_matched) if scan_matched else 'See candidate skills above'}
- Recruiter screening note (tone only, do not quote verbatim): {recruiter_note[:400] if recruiter_note else 'N/A'}

Instructions:
1. Congratulate them on being considered for this role.
2. Mention 2-3 specific skills or experiences from their background that align with the job.
3. Briefly describe the role and what makes it interesting.
4. Professional, warm, conversational tone; 200-250 words.
5. Do NOT mention match score, percentage, ATS, ranking, or any numeric fit rating.
6. Do NOT mention skill gaps, missing skills, or weaknesses — only positive alignment.
7. Do NOT use clichés like "We are pleased to inform you" or "Your profile has been shortlisted".
8. Return ONLY the email body paragraphs (no subject, no signature block — signature is added separately)."""

    role_label = role
    subject = f"Opportunity at {COMPANY_NAME} - {role_label}"

    try:
        email_body_text = _generate_body_openai(prompt)
        html_body = _build_html_email(
            candidate_name=candidate_name,
            email_body_text=email_body_text,
            outreach_id=outreach_id,
            candidate_email=candidate_email,
        )
        return {"subject": subject, "body": html_body}
    except Exception:
        interested_base = f"{BASE_URL}/acknowledge/{outreach_id}?response=interested"
        not_interested_base = f"{BASE_URL}/acknowledge/{outreach_id}?response=not_interested"
        interested_link = with_candidate_token(interested_base, outreach_id, candidate_email)
        not_interested_link = with_candidate_token(not_interested_base, outreach_id, candidate_email)
        skill_hint = ", ".join(skills[:3]) if skills else "your background"
        html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif;">
    <p>Dear {candidate_name},</p>
    <p>Thank you for your interest in opportunities with {COMPANY_NAME}. Based on your experience
    ({skill_hint}), we would like to speak with you about the <strong>{role_label}</strong> role.</p>
    <p>Please let us know if you would like to move forward:</p>
    <p>
        <a href="{interested_link}" style="background-color: #10b981; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Yes, I'm Interested</a>
        <a href="{not_interested_link}" style="background-color: #6b7280; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-left: 10px;">Not Interested</a>
    </p>
    <p>Best regards,<br>{COMPANY_NAME} Team</p>
</body>
</html>
"""
        return {"subject": subject, "body": html_body}
