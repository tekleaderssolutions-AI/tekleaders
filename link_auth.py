"""Signed tokens so only the candidate in To can use acknowledge / slot links."""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from config import ADMIN_SECRET


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def make_candidate_token(outreach_id: str, candidate_email: str) -> str:
    key = (ADMIN_SECRET or "changeme_admin_secret").encode("utf-8")
    msg = f"{outreach_id}:{_normalize_email(candidate_email)}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_candidate_token(outreach_id: str, candidate_email: str, token: Optional[str]) -> bool:
    if not outreach_id or not candidate_email or not token:
        return False
    expected = make_candidate_token(outreach_id, candidate_email)
    return hmac.compare_digest(expected, token.strip())


def with_candidate_token(url: str, outreach_id: str, candidate_email: str) -> str:
    """Append token= query param to an existing URL."""
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["token"] = make_candidate_token(outreach_id, candidate_email)
    new_query = urlencode(params)
    return urlunparse(parsed._replace(query=new_query))
