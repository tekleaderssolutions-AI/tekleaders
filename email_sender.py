# email_sender.py
"""
SMTP email sending functionality using Gmail.
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Union

from config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    FROM_EMAIL,
    REPLY_TO_EMAIL,
    get_default_cc_emails,
)

logger = logging.getLogger(__name__)


def _merge_cc_recipients(
    to_email: str,
    cc_email: Optional[str] = None,
    cc_emails: Optional[Union[List[str], str]] = None,
) -> List[str]:
    """Default team CC + optional extras; never duplicate To."""
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
        for part in cc_emails.split(","):
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
    Always CCs EMAIL_CC_LIST from config (Raghavendra, Sajida, Janaki by default).
    """
    try:
        email_body = html_body or body
        cc_list = _merge_cc_recipients(to_email, cc_email=cc_email, cc_emails=cc_emails)

        print(f"[EMAIL DEBUG] Attempting to send email to {to_email}")
        print(f"[EMAIL DEBUG] SMTP config: host={SMTP_HOST}, port={SMTP_PORT}, user={SMTP_USER}")
        print(f"[EMAIL DEBUG] Subject: {subject}")
        print(f"[EMAIL DEBUG] CC: {cc_list}")

        msg = MIMEMultipart("mixed")
        msg["From"] = FROM_EMAIL
        if REPLY_TO_EMAIL:
            msg["Reply-To"] = REPLY_TO_EMAIL

        recipients = [to_email.strip()]
        msg["To"] = to_email.strip()
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
            recipients.extend(cc_list)

        msg["Subject"] = subject

        html_part = MIMEText(email_body, "html")
        msg.attach(html_part)

        if attachment_data and attachment_filename:
            from email.mime.application import MIMEApplication

            pdf_part = MIMEApplication(attachment_data, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename=attachment_filename
            )
            msg.attach(pdf_part)
            print(f"[EMAIL DEBUG] Attached PDF: {attachment_filename}")

        print(f"[EMAIL DEBUG] Connecting to {SMTP_HOST}:{SMTP_PORT}")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        print(f"[EMAIL DEBUG] Logging in as {SMTP_USER}")
        server.login(SMTP_USER, SMTP_PASSWORD)

        print(f"[EMAIL DEBUG] Sending to recipients: {recipients}")
        server.send_message(msg, to_addrs=recipients)
        server.quit()

        cc_msg = f" (CC: {', '.join(cc_list)})" if cc_list else ""
        print(f"[EMAIL DEBUG] Email sent successfully to {to_email}{cc_msg}")
        return {
            "success": True,
            "message": f"Email sent successfully to {to_email}{cc_msg}",
        }

    except Exception as e:
        print(f"[EMAIL DEBUG ERROR] Failed to send email to {to_email}: {str(e)}")
        logger.error(f"Email sending error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to send email to {to_email}: {str(e)}",
        }
