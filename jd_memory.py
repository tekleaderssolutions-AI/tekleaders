# memory_store.py
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from psycopg2.extras import Json

from config import EMBEDDING_DIM
from db import db_cursor

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _reload_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def _openai_api_key() -> str:
    _reload_env()
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _openai_embedding_model() -> str:
    _reload_env()
    return os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def build_embedding_text(structured_jd: Dict[str, Any], summary: str | None = None) -> str:
    role = structured_jd.get("role") or ""
    location = structured_jd.get("location") or ""
    primary_skills = structured_jd.get("primary_skills") or []
    exp = structured_jd.get("experience") or {}
    exp_min = exp.get("min")
    exp_max = exp.get("max")

    primary_csv = ", ".join(primary_skills)

    if exp_min is not None or exp_max is not None:
        exp_str = f"{exp_min or ''}-{exp_max or ''}".strip("-")
    else:
        exp_str = ""

    if not summary:
        summary = f"{role} in {location} with skills {primary_csv}".strip()

    return f"{role} | {location} | skills: {primary_csv} | experience: {exp_str} | summary: {summary}"


def get_embedding_vector(text: str) -> List[float]:
    """Generate JD embedding via OpenAI (never Gemini)."""
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing for JD embeddings. Add it to hiring/.env and restart."
        )
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model = _openai_embedding_model()
    kwargs = {"input": [text], "model": model}
    if model.startswith("text-embedding-3"):
        kwargs["dimensions"] = EMBEDDING_DIM
    response = client.embeddings.create(**kwargs)
    return response.data[0].embedding


def embedding_to_literal(vec: List[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


def build_summary(structured_jd: Dict[str, Any], raw_jd_text: str) -> str:
    role = structured_jd.get("role") or "Unknown role"
    location = structured_jd.get("location") or "Unspecified location"
    employment_type = structured_jd.get("employment_type") or "unspecified"
    exp = structured_jd.get("experience") or {}
    exp_text = ""
    if exp.get("min") is not None or exp.get("max") is not None:
        exp_text = f"{exp.get('min') or ''}-{exp.get('max') or ''} years"

    primary = ", ".join(structured_jd.get("primary_skills") or [])
    responsibilities = structured_jd.get("responsibilities") or []

    parts = [
        f"{role} opportunity based in {location} ({employment_type}).",
    ]

    if exp_text:
        parts.append(f"Experience: {exp_text}.")

    if primary:
        parts.append(f"Primary skills: {primary}.")

    if responsibilities:
        resp_sentence = "Responsibilities include " + "; ".join(responsibilities[:4]) + "."
        parts.append(resp_sentence)

    summary = " ".join(parts).strip()

    if len(summary) < 150:
        filler = raw_jd_text[: max(0, 150 - len(summary))]
        summary = f"{summary} {filler}".strip()

    if len(summary) > 800:
        summary = summary[:800].rsplit(" ", 1)[0]

    return summary


def create_memory(
    structured_jd: Dict[str, Any],
    job_id: str | None,
    raw_jd_text: str,
    source_url: str | None = None,
    created_by: str = "system",
    pii_flag: bool = False,
    user_id: str | None = None,
    client_id: str | None = None,
) -> Dict[str, Any]:

    memory_uuid = str(uuid.uuid4())

    now_iso = datetime.now(timezone.utc).isoformat()

    title = structured_jd.get("role") or "Untitled role"
    raw_text_snippet = raw_jd_text[:800]

    summary = build_summary(structured_jd, raw_jd_text)
    embed_text = build_embedding_text(structured_jd, summary=summary)
    embedding = get_embedding_vector(embed_text)
    embedding_literal = embedding_to_literal(embedding)

    exp = structured_jd.get("experience") or {}
    salary = structured_jd.get("salary") or {}

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT short_id FROM memories 
            WHERE type = 'job' AND short_id LIKE 'tek%'
            ORDER BY short_id DESC 
            LIMIT 1
            """
        )
        row = cur.fetchone()

        if row and row[0]:
            last_id = row[0]
            try:
                last_num = int(last_id.replace("tek", ""))
                next_num = last_num + 1
            except ValueError:
                next_num = 1
        else:
            next_num = 1

        short_id = f"tek{next_num:04d}"

    embed_model = _openai_embedding_model()
    metadata: Dict[str, Any] = {
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
        "version": 1,
        "created_by": created_by,
        "created_at": now_iso,
        "source_url": source_url,
        "pii_flag": pii_flag,
        "raw_text_snippet": raw_text_snippet,
        "embedding_model": embed_model,
        "chunk_index": 0,
        "short_id": short_id,
    }

    canonical_json = structured_jd

    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO memories (id, client_id, type, title, text, embedding, metadata, canonical_json, short_id, created_at, updated_at, user_id)
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, NOW(), NOW(), %s)
            """,
            (
                memory_uuid,
                client_id,
                "job",
                title,
                embed_text,
                embedding_literal,
                Json(metadata),
                Json(canonical_json),
                short_id,
                user_id,
            ),
        )

    return {
        "id": memory_uuid,
        "type": "job",
        "title": title,
        "summary": summary,
        "text": embed_text,
        "raw_text_snippet": raw_text_snippet,
        "metadata": metadata,
        "canonical_json": canonical_json,
        "embedding_model": embed_model,
        "embedding": embedding,
        "chunk_index": 0,
        "source_url": source_url,
        "pii_flag": pii_flag,
        "role": structured_jd.get("role"),
        "short_id": short_id,
    }
