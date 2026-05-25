"""
JD upload pipeline — OpenAI only (v4).
Loaded via importlib from disk so stale jd_parser caches cannot run.
"""
SERVICE_VERSION = "jd-openai-v4"

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from dotenv import load_dotenv
from psycopg2.extras import Json

from config import EMBEDDING_DIM
from db import db_cursor
from pii import log_pii_redaction, redact_pii

_ENV_PATH = Path(__file__).resolve().parent / ".env"

JD_PARSE_PROMPT = """You are a precise JD parsing assistant. Extract structured fields from this job description.

Job Description:
{jd_text}

Return a JSON object with: role, team, location, employment_type, experience (min, max, units),
salary (min, max, currency), primary_skills, secondary_skills, responsibilities, education,
nice_to_have, keywords. JSON only."""


def _reload_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def _api_key() -> str:
    _reload_env()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing in hiring/.env")
    return key


def _chat_model() -> str:
    _reload_env()
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def _embedding_model() -> str:
    _reload_env()
    return os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def _client():
    from openai import OpenAI

    return OpenAI(api_key=_api_key())


def _clean_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_jd_openai(jd_text: str) -> Dict[str, Any]:
    client = _client()
    response = client.chat.completions.create(
        model=_chat_model(),
        messages=[{"role": "user", "content": JD_PARSE_PROMPT.format(jd_text=jd_text)}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(_clean_json(response.choices[0].message.content or "{}"))


def _embed(text: str) -> list:
    client = _client()
    model = _embedding_model()
    kwargs = {"input": [text], "model": model}
    if model.startswith("text-embedding-3"):
        kwargs["dimensions"] = EMBEDDING_DIM
    return client.embeddings.create(**kwargs).data[0].embedding


def _build_summary(structured_jd: Dict[str, Any], raw_jd_text: str) -> str:
    role = structured_jd.get("role") or "Unknown role"
    location = structured_jd.get("location") or "Unspecified location"
    primary = ", ".join(structured_jd.get("primary_skills") or [])
    summary = f"{role} in {location}. Skills: {primary}.".strip()
    if len(summary) < 150:
        summary = f"{summary} {raw_jd_text[:150]}".strip()
    return summary[:800]


def _build_embed_text(structured_jd: Dict[str, Any], summary: str) -> str:
    role = structured_jd.get("role") or ""
    location = structured_jd.get("location") or ""
    skills = ", ".join(structured_jd.get("primary_skills") or [])
    return f"{role} | {location} | skills: {skills} | summary: {summary}"


def process_jd_upload(
    raw_jd_text: str,
    *,
    job_id: Optional[str] = None,
    source_url: Optional[str] = None,
    created_by: str = "jd_analyzer",
    user_id: Optional[str] = None,
    client_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not raw_jd_text.strip():
        raise ValueError("JD text is empty")

    redacted, pii_types = redact_pii(raw_jd_text)
    log_pii_redaction(original=raw_jd_text, redacted=redacted, pii_types=pii_types)

    structured_jd = parse_jd_openai(redacted)
    memory_uuid = str(uuid.uuid4())
    title = structured_jd.get("role") or "Untitled role"
    summary = _build_summary(structured_jd, raw_jd_text)
    embed_text = _build_embed_text(structured_jd, summary)
    embedding = _embed(embed_text)
    embedding_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT short_id FROM memories
            WHERE type = 'job' AND short_id LIKE 'tek%'
            ORDER BY short_id DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if row and row[0]:
            try:
                next_num = int(str(row[0]).replace("tek", "")) + 1
            except ValueError:
                next_num = 1
        else:
            next_num = 1
        short_id = f"tek{next_num:04d}"

    now_iso = datetime.now(timezone.utc).isoformat()
    exp = structured_jd.get("experience") or {}
    salary = structured_jd.get("salary") or {}
    metadata = {
        "job_id": job_id,
        "client_id": client_id,
        "location": structured_jd.get("location"),
        "employment_type": structured_jd.get("employment_type"),
        "experience_min": exp.get("min"),
        "experience_max": exp.get("max"),
        "primary_skills": structured_jd.get("primary_skills") or [],
        "secondary_skills": structured_jd.get("secondary_skills") or [],
        "salary_min": salary.get("min"),
        "salary_max": salary.get("max"),
        "version": 4,
        "created_by": created_by,
        "created_at": now_iso,
        "source_url": source_url,
        "pii_flag": bool(pii_types),
        "raw_text_snippet": raw_jd_text[:800],
        "embedding_model": _embedding_model(),
        "ai_provider": "openai",
        "service_version": SERVICE_VERSION,
        "short_id": short_id,
    }

    client_id_str = str(client_id) if client_id else None
    user_id_str = str(user_id) if user_id else None

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO memories (id, client_id, type, title, text, embedding, metadata, canonical_json, short_id, created_at, updated_at, user_id)
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, NOW(), NOW(), %s)
            """,
            (
                memory_uuid,
                client_id_str,
                "job",
                title,
                embed_text,
                embedding_literal,
                Json(metadata),
                Json(structured_jd),
                short_id,
                user_id_str,
            ),
        )

    return {
        "id": memory_uuid,
        "type": "job",
        "title": title,
        "summary": summary,
        "role": structured_jd.get("role"),
        "short_id": short_id,
        "metadata": metadata,
        "canonical_json": structured_jd,
        "ai_provider": "openai",
        "service_version": SERVICE_VERSION,
    }
