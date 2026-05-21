"""
Resume parsing — OpenAI only (same as JD upload).
"""
import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
SERVICE_VERSION = "resume-openai-v1"

RESUME_PARSE_PROMPT = """You are an expert at parsing resumes. Extract structured information from the resume below.

Resume:
{resume_text}

Return a JSON object with these fields (omit or null if missing):
- candidate_name (required)
- email, phone, current_title, location
- total_experience_years (number)
- skills (array of strings)
- education (array of {{degree, institution, year}})
- work_experience (array of {{title, company, duration, responsibilities}})
- certifications (array of strings)
- summary (string)

JSON only."""


def _reload_env() -> None:
    load_dotenv(_ENV_PATH, override=True)


def use_openai_for_resumes() -> bool:
    """Always True when this module is used — kept for resume_memory compatibility."""
    return True


def _api_key() -> str:
    _reload_env()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY missing in hiring/.env — add key and restart RUN_HIRING_SERVER.bat"
        )
    return key


def _chat_model() -> str:
    _reload_env()
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def _clean_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_resume_text(resume_text: str) -> Dict[str, Any]:
    if not resume_text or not resume_text.strip():
        raise ValueError("Resume text cannot be empty")

    from openai import OpenAI

    try:
        client = OpenAI(api_key=_api_key())
        response = client.chat.completions.create(
            model=_chat_model(),
            messages=[
                {
                    "role": "user",
                    "content": RESUME_PARSE_PROMPT.format(resume_text=resume_text),
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        parsed = json.loads(_clean_json(response.choices[0].message.content or "{}"))
        if not parsed.get("candidate_name"):
            parsed["candidate_name"] = "Unknown Candidate"
        parsed["ai_provider"] = "openai"
        parsed["service_version"] = SERVICE_VERSION
        return parsed
    except json.JSONDecodeError as e:
        return {
            "candidate_name": "Unknown Candidate",
            "error": f"Failed to parse resume JSON: {e}",
            "ai_provider": "openai",
        }
    except Exception as e:
        err = str(e)
        if "generativelanguage" in err or "gemini" in err.lower():
            raise RuntimeError(
                "Old Gemini resume code is still running. Restart RUN_HIRING_SERVER.bat "
                f"(expect server_build hiring-openai-v8). {err[:200]}"
            ) from e
        raise RuntimeError(f"Failed to parse resume: {err}") from e
