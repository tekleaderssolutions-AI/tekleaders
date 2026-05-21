"""
High-level orchestration for JD processing.

This module wires together:
- PII redaction + logging
- Structured parsing via LLM
- Persisting the resulting record in the memories table
"""
from typing import Dict, Any, Optional

from jd_openai_service import parse_jd_openai as parse_jd_with_function_call
from jd_memory import create_memory
from pii import redact_pii, log_pii_redaction


def analyze_job_description(
    raw_jd_text: str,
    *,
    job_id: Optional[str] = None,
    source_url: Optional[str] = None,
    created_by: str = "jd_analyzer",
    user_id: Optional[str] = None,
    client_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full JD processing pipeline used by the FastAPI layer.
    """
    if not raw_jd_text.strip():
        raise ValueError("JD text is empty")

    redacted_text, pii_types = redact_pii(raw_jd_text)
    log_pii_redaction(original=raw_jd_text, redacted=redacted_text, pii_types=pii_types)

    structured_jd = parse_jd_with_function_call(redacted_text)

    return create_memory(
        structured_jd=structured_jd,
        job_id=job_id,
        raw_jd_text=raw_jd_text,
        source_url=source_url,
        created_by=created_by,
        pii_flag=bool(pii_types),
        user_id=user_id,
        client_id=client_id,
    )


