# config.py
import os
from pathlib import Path
from dotenv import load_dotenv
 
# Path of the folder that contains config.py
BASE_DIR = Path(__file__).resolve().parent
 
# Allow overriding the env file via ENV_FILE, fall back to .env next to config.py
ENV_FILE = os.environ.get("ENV_FILE", ".env")
env_path = (Path(ENV_FILE).resolve()
            if Path(ENV_FILE).is_absolute()
            else BASE_DIR / ENV_FILE)
load_dotenv(dotenv_path=env_path, override=True)
 
 
def get_env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """
    Small helper to fetch environment variables with optional defaults and a required flag.
    Raises ValueError early when a required setting is missing.
    """
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    return value
 
# Google Gemini API Configuration (optional if OpenAI is configured)
GEMINI_API_KEY = get_env("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

CHAT_MODEL = get_env("CHAT_MODEL", "gemini-2.5-flash-exp")
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", "text-embedding-004")

# OpenAI (JD + resume parsing + embeddings when provider is openai)
OPENAI_API_KEY = get_env("OPENAI_API_KEY", "")
OPENAI_CHAT_MODEL = get_env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = get_env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
JD_AI_PROVIDER = get_env("JD_AI_PROVIDER", "openai").lower()
RESUME_AI_PROVIDER = get_env("RESUME_AI_PROVIDER", "openai").lower()

if not (OPENAI_API_KEY or "").strip() and not (GEMINI_API_KEY or "").strip():
    raise ValueError("Set OPENAI_API_KEY or GEMINI_API_KEY in hiring/.env")


def effective_jd_ai_provider() -> str:
    """Use OpenAI for JD when key is set and provider is not explicitly gemini."""
    provider = (os.environ.get("JD_AI_PROVIDER") or JD_AI_PROVIDER or "openai").lower()
    api_key = (os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY or "").strip()
    if provider == "gemini":
        return "gemini"
    if api_key:
        return "openai"
    return "gemini"


def effective_resume_ai_provider() -> str:
    provider = (
        os.environ.get("RESUME_AI_PROVIDER") or RESUME_AI_PROVIDER or JD_AI_PROVIDER or "openai"
    ).lower()
    api_key = (os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY or "").strip()
    if provider == "gemini":
        return "gemini"
    if api_key:
        return "openai"
    return "gemini"
 
DB_HOST = get_env("DB_HOST", "localhost")
DB_PORT = int(get_env("DB_PORT", "5432"))
DB_NAME = get_env("DB_NAME", "recruitment_ai")
DB_USER = get_env("DB_USER", "postgres")
DB_PASSWORD = get_env("DB_PASSWORD", "postgres")
 
EMBEDDING_DIM = 768  # text-embedding-004 outputs 768-d vectors

# Email Configuration
SMTP_HOST = get_env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(get_env("SMTP_PORT", "587"))
SMTP_USER = get_env("SMTP_USER", "recruit@tekleaders.io")
SMTP_PASSWORD = get_env("SMTP_PASSWORD", "")  # App password or SMTP password from IT
FROM_EMAIL = get_env("FROM_EMAIL", "recruit@tekleaders.io")
REPLY_TO_EMAIL = get_env("REPLY_TO_EMAIL", FROM_EMAIL)
COMPANY_NAME = get_env("COMPANY_NAME", "Tek Leaders")

# Recruiting mailbox + calendar (technical & HR rounds use the same account)
RECRUIT_EMAIL = (get_env("RECRUIT_EMAIL", FROM_EMAIL) or FROM_EMAIL or "recruit@tekleaders.io").strip().lower()

# Legacy personal Gmail — override so Render/old .env cannot keep routing interviewer mail here
_LEGACY_INTERVIEWER_EMAILS = frozenset({
    "akkireddy41473@gmail.com",
    "akkireddy41472@gmail.com",
})


def _recruit_mailbox(env_name: str, default: str | None = None) -> str:
    """Resolve interviewer/calendar mailbox; map deprecated Gmail to recruit@."""
    fallback = (default or RECRUIT_EMAIL or "recruit@tekleaders.io").strip().lower()
    raw = (get_env(env_name, fallback) or fallback).strip().lower()
    if raw in _LEGACY_INTERVIEWER_EMAILS:
        print(
            f"[CONFIG] {env_name}={raw} is deprecated; using {RECRUIT_EMAIL} instead."
        )
        return RECRUIT_EMAIL
    return raw


INTERVIEWER_EMAIL = _recruit_mailbox("INTERVIEWER_EMAIL")
HR_INTERVIEWER_EMAIL = _recruit_mailbox("HR_INTERVIEWER_EMAIL")
CALENDAR_EMAIL = _recruit_mailbox("CALENDAR_EMAIL")


def get_interviewer_email(*, hr_round: bool = False) -> str:
    """
    Interviewer mailbox at send time (reloads .env).
    Technical & HR approval emails always use recruit@ unless you change RECRUIT_EMAIL.
    """
    load_dotenv(env_path, override=True)
    if hr_round:
        return _recruit_mailbox("HR_INTERVIEWER_EMAIL")
    return _recruit_mailbox("INTERVIEWER_EMAIL")

# CC on every outbound email (comma-separated override in EMAIL_CC_LIST)
TEAM_CC_EMAILS: tuple[str, ...] = (
    "raghavendra.v@tekleaders.com",
    "sajida.baig@tekleaders.com",
    "janaki.vijinigiri@tekleaders.com",
)
_EMAIL_CC_DEFAULT = ",".join(TEAM_CC_EMAILS)
EMAIL_CC_LIST = (get_env("EMAIL_CC_LIST", _EMAIL_CC_DEFAULT) or _EMAIL_CC_DEFAULT).strip()


def get_default_cc_emails() -> list[str]:
    """
    Team CC on every send. Reads EMAIL_CC_LIST from os.environ each call so
    Render/local .env updates apply without stale imports.
    Always includes TEAM_CC_EMAILS even if env is empty or partial.
    """
    raw = (os.environ.get("EMAIL_CC_LIST") or "").strip() or _EMAIL_CC_DEFAULT
    seen: set[str] = set()
    out: list[str] = []

    def add(addr: str) -> None:
        norm = addr.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)

    for addr in TEAM_CC_EMAILS:
        add(addr)
    for part in raw.replace(";", ",").split(","):
        add(part)
    return out


# Google Calendar Configuration
GOOGLE_CALENDAR_CREDENTIALS_PATH = get_env("GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json")
# OAuth fallback when org policy blocks service account keys (set on Render after one-time local login)
GOOGLE_OAUTH_CLIENT_ID = get_env("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = get_env("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REFRESH_TOKEN = get_env("GOOGLE_OAUTH_REFRESH_TOKEN", "")
INTERVIEW_DURATION_MINUTES = int(get_env("INTERVIEW_DURATION_MINUTES", "60"))

# BASE_URL: Must be publicly accessible for email acknowledgement links to work
# For testing: Use ngrok (ngrok http 8000) and set to your ngrok URL
# For production: Set to your deployed application URL
BASE_URL = get_env("BASE_URL", "http://localhost:8000")

# Admin secret used to authorize HR/admin actions (e.g., finalizing interviews)
ADMIN_SECRET = get_env("ADMIN_SECRET", "changeme_admin_secret")

# Feedback Form Configuration
FEEDBACK_FORM_LINK = get_env("FEEDBACK_FORM_LINK", "https://docs.google.com/forms/d/e/1FAIpQLSdjWfUGHoSvMEeeN1pg53Nvvs6u4SvPRx3OzD2huZCMeNhJRg/viewform?usp=publish-editor")

# Google Sheets link where feedback responses are stored
FEEDBACK_RESPONSES_SHEET_LINK = get_env("FEEDBACK_RESPONSES_SHEET_LINK", "https://docs.google.com/spreadsheets/d/19BJR8_AZ5sYs1iUvN8qLOtdI-zEUYRYq7sBBUleTF-o/edit?usp=sharing")

# Google Sheets ID extracted from the link
FEEDBACK_SHEET_ID = "19BJR8_AZ5sYs1iUvN8qLOtdI-zEUYRYq7sBBUleTF-o"

# Google Sheets sync configuration
SHEETS_SYNC_ENABLED = get_env("SHEETS_SYNC_ENABLED", "true").lower() == "true"
SHEETS_SYNC_INTERVAL_MINUTES = int(get_env("SHEETS_SYNC_INTERVAL_MINUTES", "5"))  # Sync every 5 minutes