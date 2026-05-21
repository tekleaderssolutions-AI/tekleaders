# ranking.py
from typing import List, Dict, Any

from db import get_connection


def get_jd_memory_id_by_role(role_name: str) -> str:
    """
    Find the most recent JD memory that matches a given role name.
    Tries canonical_json->>'role' and title.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM memories
            WHERE type = 'job'
              AND (
                    LOWER(canonical_json->>'role') LIKE LOWER('%%' || %s || '%%')
                 OR LOWER(title) LIKE LOWER('%%' || %s || '%%')
              )
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            [role_name, role_name],
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        raise ValueError(f"No JD found for role name='{role_name}'")
    return row[0]  # jd_memory_id


def get_memory_embedding_literal(memory_id: str) -> str:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT embedding FROM memories WHERE id = %s", [memory_id])
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        raise ValueError(f"No memory found with id={memory_id}")
    return row[0]  # e.g. "[0.1,0.2,...]"


def get_top_k_resumes_for_jd_memory(jd_memory_id: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Core matching: given JD memory id, return top-K resumes with ATS & file_name.
    """
    jd_embedding_literal = get_memory_embedding_literal(jd_memory_id)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH jd AS (SELECT %s::vector AS v)
            SELECT
                r.id AS resume_id,
                r.candidate_name,
                r.title,
                r.metadata->>'file_name' AS file_name,
                r.email,
                1 - (r.embedding <=> (SELECT v FROM jd)) AS similarity
            FROM resumes r
            WHERE r.embedding IS NOT NULL
              AND (r.type = 'resume' OR r.type IS NULL)
            ORDER BY r.embedding <=> (SELECT v FROM jd)
            LIMIT %s;
            """,
            [jd_embedding_literal, top_k],
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    results: List[Dict[str, Any]] = []
    for rank, (resume_id, name, title, file_name, email, similarity) in enumerate(rows, start=1):
        ats_score = int(max(0.0, min(1.0, similarity)) * 100)
        results.append(
            {
                "resume_id": str(resume_id),
                "candidate_name": name,
                "current_title": title,
                "file_name": file_name,
                "candidate_email": email,
                "similarity": float(similarity),
                "ats_score": ats_score,
                "rank": rank,
            }
        )
    return results


def get_direct_outreach_for_jd(jd_memory_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Resumes uploaded for this JD (metadata linked_jd_id), not email outreach rows."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                r.id,
                r.candidate_name,
                r.email,
                (r.metadata->>'ats_score')::int,
                r.title,
                r.metadata->>'file_name' AS file_name
            FROM resumes r
            WHERE r.metadata->>'linked_jd_id' = %s
            ORDER BY (r.metadata->>'ats_score')::int DESC NULLS LAST, r.created_at DESC
            LIMIT %s
            """,
            [jd_memory_id, limit],
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    results: List[Dict[str, Any]] = []
    for idx, (resume_id, name, email, ats_score, title, file_name) in enumerate(rows, start=1):
        results.append(
            {
                "resume_id": str(resume_id),
                "candidate_name": name,
                "current_title": title,
                "file_name": file_name,
                "candidate_email": email,
                "ats_score": ats_score,
                "rank": idx,
                "source": "direct",
            }
        )
    return results


def _score_sort_key(match: Dict[str, Any]) -> float:
    score = match.get("ats_score")
    if score is None:
        return -1.0
    try:
        return float(score)
    except (TypeError, ValueError):
        return -1.0


def get_scan_matches_for_jd_memory(jd_memory_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Merge direct applicants + global embedding matches, sort by ATS score (high → low), return top-K.
    """
    top_k = max(1, min(int(top_k), 50))
    direct = get_direct_outreach_for_jd(jd_memory_id, limit=100)
    seen = {m["resume_id"] for m in direct}
    pool: List[Dict[str, Any]] = list(direct)

    try:
        global_matches = get_top_k_resumes_for_jd_memory(jd_memory_id, top_k=50)
    except (ValueError, Exception):
        global_matches = []

    for m in global_matches:
        rid = str(m["resume_id"])
        if rid not in seen:
            pool.append({**m, "resume_id": rid, "source": "global"})
            seen.add(rid)

    pool.sort(key=_score_sort_key, reverse=True)
    top = pool[:top_k]
    for i, m in enumerate(top, start=1):
        m["rank"] = i
    return top


def get_top_k_resumes_for_role(role_name: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Public API method:
      - takes role_name (e.g. 'Senior Data Scientist')
      - finds JD memory internally
      - returns top-K resumes
    """
    jd_memory_id = get_jd_memory_id_by_role(role_name)
    return get_top_k_resumes_for_jd_memory(jd_memory_id, top_k=top_k)
