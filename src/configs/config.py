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
load_dotenv(dotenv_path=env_path, override=False)
 
 
def get_env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """
    Small helper to fetch environment variables with optional defaults and a required flag.
    Raises ValueError early when a required setting is missing.
    """
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    return value
 
# Google Gemini API Configuration
GEMINI_API_KEY = get_env("GEMINI_API_KEY", required=True)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

CHAT_MODEL = get_env("CHAT_MODEL", "gemini-2.5-flash-exp")
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", "text-embedding-004")
 
DB_HOST = get_env("DB_HOST", "localhost")
DB_PORT = int(get_env("DB_PORT", "5432"))
DB_NAME = get_env("DB_NAME", "recruitment_ai")
DB_USER = get_env("DB_USER", "postgres")
DB_PASSWORD = get_env("DB_PASSWORD", "postgres")
 
EMBEDDING_DIM = 768  # text-embedding-004 outputs 768-d vectors

# Email Configuration
SMTP_HOST = get_env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(get_env("SMTP_PORT", "587"))
SMTP_USER = get_env("SMTP_USER", "srikanthtata8374@gmail.com")
SMTP_PASSWORD = get_env("SMTP_PASSWORD", "lbkr xlod igfj wzrg")  # Gmail App Password
FROM_EMAIL = get_env("FROM_EMAIL", "srikanthtata8374@gmail.com")
COMPANY_NAME = get_env("COMPANY_NAME", "Tek Leaders")

# Google Calendar Configuration
GOOGLE_CALENDAR_CREDENTIALS_PATH = get_env("GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json")
INTERVIEWER_EMAIL = get_env("INTERVIEWER_EMAIL", "recruit@tekleaders.io")
INTERVIEW_DURATION_MINUTES = int(get_env("INTERVIEW_DURATION_MINUTES", "60"))

# BASE_URL: Must be publicly accessible for email acknowledgement links to work
# For testing: Use ngrok (ngrok http 8000) and set to your ngrok URL
# For production: Set to your deployed application URL
BASE_URL = get_env("BASE_URL", "http://localhost:8000")
# Admin secret used to authorize HR/admin actions (e.g., finalizing interviews)
ADMIN_SECRET = get_env("ADMIN_SECRET", "changeme_admin_secret")
