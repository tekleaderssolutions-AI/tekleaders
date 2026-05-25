# pii.py
import re
import uuid
from typing import Tuple, List

from db import db_cursor

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_REGEX = re.compile(r"\+?\d[\d\-\s]{6,}\d")

def redact_pii(text: str) -> Tuple[str, List[str]]:
    """
    Redact email & phone using regex.
    Return: (redacted_text, [pii_types])
    """
    pii_types: List[str] = []

    def _mask_email(match):
        nonlocal pii_types
        pii_types.append("email")
        return "[REDACTED_EMAIL]"

    def _mask_phone(match):
        nonlocal pii_types
        pii_types.append("phone")
        return "[REDACTED_PHONE]"

    redacted = EMAIL_REGEX.sub(_mask_email, text)
    redacted = PHONE_REGEX.sub(_mask_phone, redacted)

    return redacted, sorted(set(pii_types))


def log_pii_redaction(original: str, redacted: str, pii_types: List[str]):
    """
    Store small sample of original + redacted for evidence.
    This table does NOT contain full JD, only snippet.
    """
    if not pii_types:
        return

    original_snippet = original[:500]
    redacted_snippet = redacted[:500]

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO pii_redaction_logs (id, original_sample, redacted_sample, pii_types)
            VALUES (%s, %s, %s, %s)
            """,
            [
                str(uuid.uuid4()),
                original_snippet,
                redacted_snippet,
                pii_types,
            ],
        )
