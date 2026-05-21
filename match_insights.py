"""Skill match insights for JD vs resume ranking."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from db import db_cursor


def _norm_skill(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _collect_skills(items: Any) -> Set[str]:
    out: Set[str] = set()
    if not items:
        return out
    if isinstance(items, str):
        for part in re.split(r"[,;/|•\n]+", items):
            n = _norm_skill(part)
            if n and len(n) > 1:
                out.add(n)
        return out
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                n = _norm_skill(item)
                if n and len(n) > 1:
                    out.add(n)
            elif isinstance(item, dict):
                for key in ("name", "skill", "title", "technology"):
                    if item.get(key):
                        out |= _collect_skills(item[key])
    return out


def _parse_json_field(val: Any) -> Any:
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return {}
    return {}


def _skills_from_text(text: str, jd_hints: Set[str]) -> Set[str]:
    """Find JD skill phrases mentioned in resume/JD body text."""
    if not text:
        return set()
    lower = text.lower()
    found: Set[str] = set()
    for skill in jd_hints:
        if len(skill) < 2:
            continue
        if skill in lower:
            found.add(skill)
            continue
        # word-boundary style for short tokens (sql, etl)
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found.add(skill)
    return found


def _skills_overlap(jd_skill: str, resume_skill: str) -> bool:
    a, b = _norm_skill(jd_skill), _norm_skill(resume_skill)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = set(re.split(r"[\s/\-]+", a)), set(re.split(r"[\s/\-]+", b))
    ta.discard("")
    tb.discard("")
    if ta & tb:
        return True
    # ssis ↔ msbi developer style partial
    for token in ta:
        if len(token) >= 3 and token in b:
            return True
    for token in tb:
        if len(token) >= 3 and token in a:
            return True
    return False


def _fuzzy_match_lists(
    jd_skills: Set[str], resume_skills: Set[str]
) -> Tuple[List[str], List[str], List[str]]:
    matched: List[str] = []
    missing: List[str] = []
    used_resume: Set[str] = set()

    for jd in sorted(jd_skills, key=len, reverse=True):
        hit = None
        for res in resume_skills:
            if res in used_resume:
                continue
            if _skills_overlap(jd, res):
                hit = res
                break
        if hit:
            matched.append(jd)
            used_resume.add(hit)
        else:
            missing.append(jd)

    extra = sorted(resume_skills - used_resume)[:12]
    return matched, missing, extra


def _jd_skill_set(canonical_json: Any, metadata: Any, jd_text: str = "") -> Set[str]:
    cj = _parse_json_field(canonical_json)
    meta = _parse_json_field(metadata)
    skills: Set[str] = set()
    for key in (
        "primary_skills",
        "secondary_skills",
        "keywords",
        "required_skills",
        "technical_skills",
        "nice_to_have",
        "tools",
        "technologies",
    ):
        skills |= _collect_skills(cj.get(key))
        skills |= _collect_skills(meta.get(key))
    skills |= _collect_skills(cj.get("responsibilities"))
    skills |= _collect_skills(cj.get("requirements"))
    skills |= _collect_skills(cj.get("qualifications"))
    if jd_text:
        skills |= _skills_from_text(jd_text, skills)
    return {s for s in skills if len(s) > 1}


def _resume_skill_set(
    canonical_json: Any,
    metadata: Any,
    *,
    resume_text: str = "",
    current_title: str = "",
    jd_hints: Optional[Set[str]] = None,
) -> Set[str]:
    cj = _parse_json_field(canonical_json)
    meta = _parse_json_field(metadata)
    skills: Set[str] = set()
    skills |= _collect_skills(cj.get("skills"))
    skills |= _collect_skills(meta.get("skills"))
    skills |= _collect_skills(cj.get("certifications"))
    skills |= _collect_skills(current_title)

    for we in cj.get("work_experience") or []:
        if isinstance(we, dict):
            skills |= _collect_skills(we.get("title"))
            skills |= _collect_skills(we.get("responsibilities"))
            skills |= _collect_skills(we.get("company"))

    skills |= _collect_skills(cj.get("summary"))
    skills |= _collect_skills(cj.get("projects"))

    hints = jd_hints or set()
    blob = " ".join(
        filter(
            None,
            [
                resume_text or "",
                cj.get("summary") or "",
                current_title or "",
            ],
        )
    )
    if blob and hints:
        skills |= _skills_from_text(blob, hints)
    return {s for s in skills if len(s) > 1}


def build_match_insights(
    *,
    jd_role: str,
    jd_skills: Set[str],
    resume_skills: Set[str],
    ats_score: int,
    candidate_name: str = "",
    current_title: str = "",
) -> Dict[str, Any]:
    matched, missing, extra = _fuzzy_match_lists(jd_skills, resume_skills)

    if ats_score >= 75:
        tier = "Strong"
    elif ats_score >= 50:
        tier = "Good"
    else:
        tier = "Partial"

    role = jd_role or "this role"
    name = candidate_name or "Candidate"
    lines: List[str] = [
        f"{tier} match ({ats_score}%) — {name} for {role}.",
    ]

    if matched:
        lines.append(
            f"Top skills matched ({len(matched)}): "
            + ", ".join(m.title() if m.islower() else m for m in matched[:10])
            + ("…" if len(matched) > 10 else "")
            + "."
        )
    else:
        lines.append(
            "No exact JD keyword overlap; ranking is driven mainly by profile similarity and role title alignment."
        )

    if missing:
        lines.append(
            f"Skills to validate in interview ({len(missing)} gaps): "
            + ", ".join(m.title() if m.islower() else m for m in missing[:8])
            + ("…" if len(missing) > 8 else "")
            + "."
        )

    if extra:
        lines.append(
            "Additional strengths on resume: "
            + ", ".join(e.title() if e.islower() else e for e in extra[:6])
            + ("…" if len(extra) > 6 else "")
            + "."
        )

    if current_title:
        lines.append(f"Current role: {current_title}.")

    if tier in ("Strong", "Good") and ats_score >= 50:
        lines.append("Recommend moving forward to recruiter screen or technical interview.")
    elif ats_score >= 40:
        lines.append("Consider for interview if gaps can be addressed with training or project experience.")
    else:
        lines.append("Lower priority unless role requirements are flexible.")

    return {
        "matched_skills": matched,
        "missing_skills": missing,
        "extra_skills": extra,
        "reason_to_select": " ".join(lines),
    }


def _resume_table_columns() -> Set[str]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'resumes'
            """
        )
        return {r[0] for r in cur.fetchall()}


def _fetch_resume_row(resume_id: str) -> Dict[str, Any]:
    cols = _resume_table_columns()
    select_parts = ["canonical_json", "metadata", "email", "title", "candidate_name"]
    for opt in ("text", "raw_text", "structured_data"):
        if opt in cols and opt not in select_parts:
            select_parts.append(opt)
    sql = f"SELECT {', '.join(select_parts)} FROM resumes WHERE id = %s"
    with db_cursor() as cur:
        cur.execute(sql, [str(resume_id)])
        row = cur.fetchone()
    if not row:
        return {}
    data = dict(zip(select_parts, row))
    cj = data.get("canonical_json")
    if not cj and data.get("structured_data"):
        data["canonical_json"] = data["structured_data"]
    text_blob = (data.get("text") or "") + " " + (data.get("raw_text") or "")
    data["resume_text"] = text_blob.strip()
    return data


def _fetch_jd_row(jd_memory_id: str) -> Dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT title, canonical_json, metadata, text
            FROM memories WHERE id = %s AND type = 'job'
            """,
            [jd_memory_id],
        )
        row = cur.fetchone()
    if not row:
        return {}
    return {
        "title": row[0],
        "canonical_json": row[1],
        "metadata": row[2],
        "text": row[3] or "",
    }


def enrich_match(jd_memory_id: str, match: Dict[str, Any]) -> Dict[str, Any]:
    """Add matched_skills, missing_skills, reason_to_select (heuristic; AI applied in enrich_matches)."""
    jd = _fetch_jd_row(jd_memory_id)
    res = _fetch_resume_row(str(match["resume_id"]))

    jd_role = jd.get("title") or match.get("current_title") or "Role"
    jd_cj, jd_meta, jd_text = jd.get("canonical_json"), jd.get("metadata"), jd.get("text") or ""
    res_cj = res.get("canonical_json") or {}
    res_meta = res.get("metadata") or {}
    email = res.get("email") or match.get("candidate_email")
    resume_text = res.get("resume_text") or ""
    res_title = res.get("title") or match.get("current_title") or ""
    cand_name = res.get("candidate_name") or match.get("candidate_name") or ""

    jd_skills = _jd_skill_set(jd_cj, jd_meta, jd_text)
    if not jd_skills and jd_text:
        jd_skills |= _collect_skills(jd_text[:3000])
    resume_skills = _resume_skill_set(
        res_cj,
        res_meta,
        resume_text=resume_text,
        current_title=res_title,
        jd_hints=jd_skills,
    )

    insights = build_match_insights(
        jd_role=jd_role,
        jd_skills=jd_skills,
        resume_skills=resume_skills,
        ats_score=int(match.get("ats_score") or 0),
        candidate_name=cand_name,
        current_title=res_title,
    )

    out = {**match, **insights}
    if email:
        out["candidate_email"] = email
    out["_jd_snippet"] = (jd_text or "")[:1500]
    out["_resume_snippet"] = (resume_text or "")[:2500]
    out["_jd_role"] = jd_role
    return out


def _ai_enrich_reason(
    *,
    jd_role: str,
    ats_score: int,
    matched: List[str],
    missing: List[str],
    extra: List[str],
    candidate_name: str,
    current_title: str,
    resume_snippet: str,
    jd_snippet: str,
) -> Optional[Dict[str, Any]]:
    """Short OpenAI pass for detailed recruiter-facing reasoning."""
    if not resume_snippet.strip():
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    prompt = f"""You are a hiring analyst. Compare this candidate to the job.

Job role: {jd_role}
ATS similarity score: {ats_score}%
Candidate: {candidate_name}
Title: {current_title}
Heuristic matched skills: {', '.join(matched) or 'none'}
Heuristic missing skills: {', '.join(missing) or 'none'}
Extra resume skills: {', '.join(extra) or 'none'}

JD excerpt:
{jd_snippet[:1200]}

Resume excerpt:
{resume_snippet[:2000]}

Return JSON only:
{{
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1"],
  "reason_to_select": "2-4 sentences for recruiter: why select, key matches, gaps, interview focus"
}}
Use concrete technology names from the texts. matched_skills and missing_skills must be arrays of strings (max 12 each)."""

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=600,
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        reason = (data.get("reason_to_select") or "").strip()
        if not reason:
            return None
        ms = data.get("matched_skills")
        mis = data.get("missing_skills")
        out: Dict[str, Any] = {"reason_to_select": reason}
        if isinstance(ms, list) and ms:
            out["matched_skills"] = [str(x) for x in ms[:12]]
        if isinstance(mis, list) and mis:
            out["missing_skills"] = [str(x) for x in mis[:12]]
        return out
    except Exception:
        return None


def _apply_batch_ai_insights(
    jd_memory_id: str, enriched: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """One OpenAI call for all candidates — faster and more reliable than per-row calls."""
    if not enriched or os.environ.get("MATCH_INSIGHTS_AI", "1") != "1":
        return enriched
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return enriched
    try:
        from openai import OpenAI
    except ImportError:
        return enriched

    jd = _fetch_jd_row(jd_memory_id)
    jd_role = jd.get("title") or "Role"
    jd_snippet = (jd.get("text") or "")[:2000]

    blocks: List[str] = []
    for i, m in enumerate(enriched[:12]):
        blocks.append(
            f"""--- Candidate {i + 1} ---
resume_id: {m.get('resume_id')}
name: {m.get('candidate_name')}
title: {m.get('current_title')}
ats_score: {m.get('ats_score')}%
resume_excerpt: {(m.get('_resume_snippet') or '')[:1200]}
"""
        )

    prompt = f"""You are a hiring analyst. For each candidate below, compare to the job and return detailed recruiter insights.

Job: {jd_role}
JD excerpt:
{jd_snippet[:2000]}

{chr(10).join(blocks)}

Return JSON only:
{{
  "candidates": [
    {{
      "resume_id": "<same id>",
      "matched_skills": ["skill1", "skill2"],
      "missing_skills": ["gap1"],
      "reason_to_select": "3-5 sentences: fit, top matches, gaps, interview focus"
    }}
  ]
}}
Include one entry per candidate in the same order. Use concrete tech skills from the resume excerpts."""

    try:
        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2500,
        )
        data = json.loads((resp.choices[0].message.content or "{}").strip())
        items = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return enriched
        by_id = {str(x.get("resume_id")): x for x in items if isinstance(x, dict) and x.get("resume_id")}
        for m in enriched:
            upd = by_id.get(str(m.get("resume_id")))
            if not upd:
                continue
            reason = (upd.get("reason_to_select") or "").strip()
            if reason:
                m["reason_to_select"] = reason
            ms = upd.get("matched_skills")
            mis = upd.get("missing_skills")
            if isinstance(ms, list) and ms:
                m["matched_skills"] = [str(x) for x in ms[:12]]
            if isinstance(mis, list) and mis:
                m["missing_skills"] = [str(x) for x in mis[:12]]
    except Exception:
        for m in enriched:
            if not m.get("matched_skills") and not m.get("missing_skills"):
                _ai_single = _ai_enrich_reason(
                    jd_role=m.get("_jd_role") or jd_role,
                    ats_score=int(m.get("ats_score") or 0),
                    matched=m.get("matched_skills") or [],
                    missing=m.get("missing_skills") or [],
                    extra=m.get("extra_skills") or [],
                    candidate_name=m.get("candidate_name") or "",
                    current_title=m.get("current_title") or "",
                    resume_snippet=m.get("_resume_snippet") or "",
                    jd_snippet=jd_snippet,
                )
                if _ai_single:
                    if _ai_single.get("reason_to_select"):
                        m["reason_to_select"] = _ai_single["reason_to_select"]
                    if _ai_single.get("matched_skills"):
                        m["matched_skills"] = _ai_single["matched_skills"]
                    if _ai_single.get("missing_skills"):
                        m["missing_skills"] = _ai_single["missing_skills"]

    for m in enriched:
        m.pop("_jd_snippet", None)
        m.pop("_resume_snippet", None)
        m.pop("_jd_role", None)
    return enriched


def enrich_matches(jd_memory_id: str, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in matches:
        try:
            out.append(enrich_match(jd_memory_id, m))
        except Exception as ex:
            score = int(m.get("ats_score") or 0)
            out.append(
                {
                    **m,
                    "matched_skills": m.get("matched_skills") or [],
                    "missing_skills": m.get("missing_skills") or [],
                    "reason_to_select": m.get("reason_to_select")
                    or f"Match score {score}% for this role. Analysis error: {ex}",
                }
            )
    return _apply_batch_ai_insights(jd_memory_id, out)
