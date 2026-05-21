# email_sender.py
"""
SMTP email sending functionality using Gmail.
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL, REPLY_TO_EMAIL

logger = logging.getLogger(__name__)


def send_email(
    to_email: str, 
    subject: str, 
    html_body: str = None,
    body: str = None,
    cc_email: Optional[str] = None,
    attachment_data: Optional[bytes] = None,
    attachment_filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send an email via Gmail SMTP.
    
    Args:
        to_email: Primary recipient email address
        subject: Email subject
        html_body: HTML content of the email (preferred)
        body: Plain text or HTML body (fallback for compatibility)
        cc_email: Optional additional recipient to include in TO field
        attachment_data: Optional PDF or file data as bytes
        attachment_filename: Filename for the attachment
        
    Returns:
        Dict with 'success' boolean and 'message' string
    """
    try:
        # Support both html_body and body parameters for compatibility
        email_body = html_body or body
        
        print(f"[EMAIL DEBUG] Attempting to send email to {to_email}")
        print(f"[EMAIL DEBUG] SMTP config: host={SMTP_HOST}, port={SMTP_PORT}, user={SMTP_USER}")
        print(f"[EMAIL DEBUG] Subject: {subject}")
        print(f"[EMAIL DEBUG] CC: {cc_email}")
        print(f"[EMAIL DEBUG] Has attachment: {attachment_data is not None}")
        
        # Create message
        msg = MIMEMultipart('mixed')
        msg['From'] = FROM_EMAIL
        if REPLY_TO_EMAIL:
            msg['Reply-To'] = REPLY_TO_EMAIL

        # Build recipients list and proper headers: To (primary) and Cc (carbon copy)
        recipients = [to_email]
        msg['To'] = to_email
        if cc_email:
            recipients.append(cc_email)
            msg['Cc'] = cc_email
            
        msg['Subject'] = subject
        
        # Attach HTML body
        html_part = MIMEText(email_body, 'html')
        msg.attach(html_part)
        
        # Attach PDF if provided
        if attachment_data and attachment_filename:
            from email.mime.application import MIMEApplication
            
            pdf_part = MIMEApplication(attachment_data, _subtype='pdf')
            pdf_part.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
            msg.attach(pdf_part)
            print(f"[EMAIL DEBUG] Attached PDF: {attachment_filename}")
        
        print(f"[EMAIL DEBUG] Connecting to {SMTP_HOST}:{SMTP_PORT}")
        # Connect to Gmail SMTP server
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()  # Enable TLS encryption
        print(f"[EMAIL DEBUG] Logging in as {SMTP_USER}")
        server.login(SMTP_USER, SMTP_PASSWORD)
        
        print(f"[EMAIL DEBUG] Sending to recipients: {recipients}")
        # Send email to all recipients (including CC)
        server.send_message(msg, to_addrs=recipients)
        server.quit()
        
        recipient_msg = f" and {cc_email}" if cc_email else ""
        print(f"[EMAIL DEBUG] Email sent successfully to {to_email}{recipient_msg}")
        return {
            "success": True,
            "message": f"Email sent successfully to {to_email}{recipient_msg}"
        }
        
    except Exception as e:
        print(f"[EMAIL DEBUG ERROR] Failed to send email to {to_email}: {str(e)}")
        logger.error(f"Email sending error: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to send email to {to_email}: {str(e)}"
        }
