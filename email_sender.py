# email_sender.py
"""
SMTP email sending functionality using Gmail.
"""
import os
import smtplib
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Union

from dotenv import load_dotenv

from config import get_default_cc_emails

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _reload_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def _smtp_settings() -> dict[str, Any]:
    """Read SMTP settings after .env reload (avoids stale module-level config)."""
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", "recruit@tekleaders.io"),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_email": os.environ.get("FROM_EMAIL", os.environ.get("SMTP_USER", "recruit@tekleaders.io")),
        "reply_to": os.environ.get("REPLY_TO_EMAIL", ""),
    }


def _merge_cc_recipients(
    to_email: str,
    cc_email: Optional[str] = None,
    cc_emails: Optional[Union[List[str], str]] = None,
) -> List[str]:
    """Default team CC + optional extras; never duplicate To."""
    _reload_env()
    to_norm = (to_email or "").strip().lower()
    merged: List[str] = []
    seen: set[str] = set()

    def add(addr: Optional[str]) -> None:
        if not addr:
            return
        norm = addr.strip().lower()
        if not norm or norm == to_norm or norm in seen:
            return
        seen.add(norm)
        merged.append(norm)

    for addr in get_default_cc_emails():
        add(addr)
    if isinstance(cc_emails, str):
        for part in cc_emails.replace(";", ",").split(","):
            add(part)
    elif cc_emails:
        for addr in cc_emails:
            add(addr)
    add(cc_email)
    return merged


def send_email(
    to_email: str,
    subject: str,
    html_body: str = None,
    body: str = None,
    cc_email: Optional[str] = None,
    cc_emails: Optional[Union[List[str], str]] = None,
    attachment_data: Optional[bytes] = None,
    attachment_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email via Gmail SMTP.
    Always CCs team list (Raghavendra, Sajida, Janaki) plus any extras.
    Uses sendmail() with explicit envelope recipients so CC actually delivers.
    """
    try:
        _reload_env()
        cfg = _smtp_settings()
        email_body = html_body or body
        if not email_body:
            return {"success": False, "message": "Email body is empty"}

        cc_list = _merge_cc_recipients(to_email, cc_email=cc_email, cc_emails=cc_emails)
        to_addr = to_email.strip()
        from_addr = (cfg["from_email"] or cfg["user"]).strip()

        # SMTP envelope must list every recipient (To + Cc); headers alone are not enough.
        envelope_recipients: List[str] = [to_addr]
        for cc in cc_list:
            if cc not in envelope_recipients:
                envelope_recipients.append(cc)

        print(f"[EMAIL DEBUG] Attempting to send email to {to_addr}")
        print(f"[EMAIL DEBUG] SMTP: {cfg['host']}:{cfg['port']} user={cfg['user']}")
        print(f"[EMAIL DEBUG] Subject: {subject}")
        print(f"[EMAIL DEBUG] Cc header: {cc_list}")
        print(f"[EMAIL DEBUG] Envelope recipients: {envelope_recipients}")

        msg = MIMEMultipart("mixed")
        msg["From"] = from_addr
        if cfg["reply_to"]:
            msg["Reply-To"] = cfg["reply_to"]
        msg["To"] = to_addr
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg["Subject"] = subject

        html_part = MIMEText(email_body, "html", "utf-8")
        msg.attach(html_part)

        if attachment_data and attachment_filename:
            from email.mime.application import MIMEApplication

            pdf_part = MIMEApplication(attachment_data, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename=attachment_filename
            )
            msg.attach(pdf_part)
            print(f"[EMAIL DEBUG] Attached PDF: {attachment_filename}")

        print(f"[EMAIL DEBUG] Connecting to {cfg['host']}:{cfg['port']}")
        server = smtplib.SMTP(cfg["host"], cfg["port"])
        server.starttls()
        print(f"[EMAIL DEBUG] Logging in as {cfg['user']}")
        server.login(cfg["user"], cfg["password"])

        # sendmail = reliable multi-recipient delivery (To + Cc on envelope)
        server.sendmail(from_addr, envelope_recipients, msg.as_string())
        server.quit()

        cc_msg = f" (CC: {', '.join(cc_list)})" if cc_list else ""
        print(f"[EMAIL DEBUG] Email sent successfully to {to_addr}{cc_msg}")
        return {
            "success": True,
            "message": f"Email sent successfully to {to_addr}{cc_msg}",
            "cc": cc_list,
            "envelope_recipients": envelope_recipients,
        }

    except Exception as e:
        print(f"[EMAIL DEBUG ERROR] Failed to send email to {to_email}: {str(e)}")
        logger.error(f"Email sending error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to send email to {to_email}: {str(e)}",
        }
