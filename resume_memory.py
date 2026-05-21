# resume_memory.py — OpenAI embeddings only
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Set

from dotenv import load_dotenv
from psycopg2.extras import Json

from config import EMBEDDING_DIM
from db import get_connection, db_cursor

_ENV_PATH = Path(__file__).resolve().parent / ".env"
DEFAULT_TENANT_ID = "23cd7026-c85b-4f38-ad2d-bcd09cbc487c"


def _ensure_resume_schema() -> None:
    """Add missing columns on older databases (idempotent)."""
    with db_cursor() as cur:
        for col, col_type in [
            ("candidate_id", "UUID"),
            ("candidate_name", "TEXT"),
            ("email", "TEXT"),
            ("phone", "TEXT"),
            ("type", "TEXT"),
            ("title", "TEXT"),
            ("text", "TEXT"),
            ("file_name", "TEXT"),
            ("raw_text", "TEXT"),
            ("structured_data", "JSONB"),
            ("metadata", "JSONB"),
            ("canonical_json", "JSONB"),
            ("created_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("user_id", "UUID"),
        ]:
            cur.execute(
                f"""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'resumes' AND column_name = '{col}'
                    ) THEN
                        ALTER TABLE resumes ADD COLUMN {col} {col_type};
                    END IF;
                END $$;
                """
            )
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'resumes' AND column_name = 'embedding'
                ) THEN
                    ALTER TABLE resumes ADD COLUMN embedding vector(768);
                END IF;
            END $$;
        """)
        cur.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'resumes' AND column_name = 'candidate_id'
                ) THEN
                    ALTER TABLE resumes ALTER COLUMN candidate_id SET DEFAULT gen_random_uuid();
                END IF;
            END $$;
        """)


def _resume_column_meta() -> List[tuple]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT column_name, is_nullable, udt_name
            FROM information_schema.columns
            WHERE table_name = 'resumes' AND table_schema = 'public'
            ORDER BY ordinal_position
            """
        )
        return cur.fetchall()


def use_openai_for_resumes() -> bool:
    return True


def embedding_to_literal(vec: List[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


def build_resume_embedding_text(parsed: Dict[str, Any]) -> str:
    title = parsed.get("current_title") or ""
    location = parsed.get("location") or ""
    skills = parsed.get("skills") or []
    skills_csv = ", ".join(skills)
    exp_years = parsed.get("total_experience_years") or parsed.get("total_experience_yrs") or 0
    summary = (parsed.get("summary") or "").strip()
    if not summary:
        summary = f"{title} with {exp_years} years experience in {skills_csv}".strip()
    return f"{title} | {location} | skills: {skills_csv} | experience: {exp_years} | summary: {summary}"


def _candidates_table_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.candidates')")
        return cur.fetchone()[0] is not None


def _candidate_column_meta() -> List[tuple]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT column_name, is_nullable, udt_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'candidates'
            ORDER BY ordinal_position
            """
        )
        return cur.fetchall()


def _lookup_candidate_by_email(email: str) -> str | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'candidates' AND column_name = 'email'
            """
        )
        if not cur.fetchone():
            return None
        cur.execute("SELECT id FROM candidates WHERE email = %s LIMIT 1", [email])
        found = cur.fetchone()
        return str(found[0]) if found else None


def _build_candidate_row(candidate_id: str, parsed_resume: Dict[str, Any]) -> Dict[str, Any]:
    name = parsed_resume.get("candidate_name") or "Unknown Candidate"
    email = (parsed_resume.get("email") or "").strip() or f"candidate-{candidate_id[:8]}@local.invalid"
    phone = parsed_resume.get("phone")
    now = datetime.now(timezone.utc)

    row: Dict[str, Any] = {
        "id": candidate_id,
        "name": name,
        "full_name": name,
        "candidate_name": name,
        "display_name": name,
        "email": email,
        "phone": phone,
        "tenant_id": DEFAULT_TENANT_ID,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }

    meta = _candidate_column_meta()
    col_names = {m[0] for m in meta}
    final: Dict[str, Any] = {}

    for col_name, nullable, _udt, default in meta:
        if col_name not in col_names:
            continue
        val = row.get(col_name)
        if val is None and nullable == "NO" and default is None:
            if col_name == "email":
                val = email
            elif col_name in ("name", "full_name", "candidate_name", "display_name"):
                val = name
            elif col_name == "tenant_id":
                val = DEFAULT_TENANT_ID
            elif col_name == "status":
                val = "active"
            elif col_name == "id":
                val = candidate_id
        if val is not None:
            final[col_name] = val

    return final


def _insert_candidate_row(row: Dict[str, Any]) -> None:
    insert_cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(insert_cols))
    sql = f"INSERT INTO candidates ({', '.join(insert_cols)}) VALUES ({placeholders})"
    with db_cursor() as cur:
        cur.execute(sql, [row[c] for c in insert_cols])


def _ensure_candidate_record(parsed_resume: Dict[str, Any]) -> str:
    """
    Ensure a row exists in candidates (FK target for resumes.candidate_id).
    Uses separate DB transactions so a failed insert cannot abort the resume insert.
    """
    if not _candidates_table_exists():
        return str(uuid.uuid4())

    meta = _candidate_column_meta()
    if not any(m[0] == "id" for m in meta):
        return str(uuid.uuid4())

    email = (parsed_resume.get("email") or "").strip() or None
    if email:
        existing = _lookup_candidate_by_email(email)
        if existing:
            return existing

    candidate_id = str(uuid.uuid4())
    row = _build_candidate_row(candidate_id, parsed_resume)

    try:
        _insert_candidate_row(row)
        return candidate_id
    except Exception as insert_err:
        if email:
            existing = _lookup_candidate_by_email(email)
            if existing:
                return existing
        raise RuntimeError(f"Could not create candidate record: {insert_err}") from insert_err


def get_embedding(text: str) -> List[float]:
    from openai import OpenAI

    load_dotenv(_ENV_PATH, override=True)
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing in hiring/.env")
    model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client = OpenAI(api_key=api_key)
    kwargs: Dict[str, Any] = {"input": [text], "model": model}
    if model.startswith("text-embedding-3"):
        kwargs["dimensions"] = EMBEDDING_DIM
    return client.embeddings.create(**kwargs).data[0].embedding


def save_parsed_resume_and_memory(
    parsed_resume: Dict[str, Any],
    raw_text: str,
    source_url: str | None = None,
    file_name: str | None = None,
    user_id: str | None = None,
) -> str:
    _ensure_resume_schema()

    resume_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    embed_text = build_resume_embedding_text(parsed_resume)
    embedding = get_embedding(embed_text)
    embedding_literal = embedding_to_literal(embedding)

    exp_years = parsed_resume.get("total_experience_years") or parsed_resume.get("total_experience_yrs")
    embed_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    resume_metadata = {
        "current_company": parsed_resume.get("current_company"),
        "location": parsed_resume.get("location"),
        "total_experience_years": exp_years,
        "skills": parsed_resume.get("skills") or [],
        "domain": parsed_resume.get("domain"),
        "education": parsed_resume.get("education"),
        "certifications": parsed_resume.get("certifications"),
        "projects": parsed_resume.get("projects"),
        "source_url": source_url,
        "file_name": file_name,
        "raw_text_snippet": raw_text[:800],
        "embedding_model": embed_model,
        "ai_provider": "openai",
        "created_at": now_iso,
    }

    conn = get_connection()
    try:
        cur = conn.cursor()
        candidate_id = _ensure_candidate_record(parsed_resume)

        row: Dict[str, Any] = {
            "id": resume_id,
            "candidate_id": candidate_id,
            "candidate_name": parsed_resume.get("candidate_name") or "Unknown Candidate",
            "email": parsed_resume.get("email"),
            "phone": parsed_resume.get("phone"),
            "type": "resume",
            "title": parsed_resume.get("current_title"),
            "text": embed_text,
            "embedding": embedding_literal,
            "metadata": Json(resume_metadata),
            "canonical_json": Json(parsed_resume),
            "structured_data": Json(parsed_resume),
            "file_name": file_name or source_url or "resume",
            "raw_text": raw_text or "",
            "user_id": user_id,
        }

        insert_cols: List[str] = []
        placeholders: List[str] = []
        values: List[Any] = []

        for col_name, nullable, udt_name in _resume_column_meta():
            if col_name in ("created_at", "updated_at"):
                continue

            val = row.get(col_name)
            if val is None and nullable == "NO":
                if col_name == "candidate_id":
                    val = candidate_id
                elif col_name == "type":
                    val = "resume"
                elif col_name == "file_name":
                    val = row.get("file_name") or "resume"
                elif col_name == "raw_text":
                    val = row.get("raw_text") or ""
                elif col_name == "id":
                    val = resume_id
                elif col_name == "candidate_name":
                    val = row.get("candidate_name") or "Unknown Candidate"

            if val is None:
                continue

            insert_cols.append(col_name)
            if col_name == "embedding" or udt_name == "vector":
                placeholders.append("%s::vector")
            else:
                placeholders.append("%s")
            values.append(val)

        if "id" not in insert_cols:
            raise RuntimeError("resumes table missing id column")
        if "candidate_id" not in insert_cols:
            raise RuntimeError("candidate_id must be set for resumes insert")

        sql = f"INSERT INTO resumes ({', '.join(insert_cols)}) VALUES ({', '.join(placeholders)})"
        cur.execute(sql, values)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return resume_id
