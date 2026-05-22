# main.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any config-dependent imports (override stale shell env)
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional, List, Dict, Any
import pdfplumber
from io import BytesIO

from ranker_agent import get_top_matches_for_role
from resume_agent import process_resume_text
from resume_text_extractor import (
    expand_upload,
    extract_resume_text,
    is_supported_upload_filename,
)
import html


# --- Authentication Logic ---
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
from fastapi import status
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from passlib.context import CryptContext

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_TENANT_ID = "23cd7026-c85b-4f38-ad2d-bcd09cbc487c"
USER_LOGIN_WHERE = "username = %s OR email = %s"

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)



def authenticate_user(username: str, password: str) -> Optional[dict]:
    admin_username = os.getenv("ADMIN_USERNAME", "hiring")
    admin_password = os.getenv("ADMIN_PASSWORD", "Akshitha@73")
    
    print(f"DEBUG: Attempting login with username='{username}'")
    
    # 1. Check Admin Credentials (Env Vars)
    if username == admin_username and password == admin_password:
        print("DEBUG: Login successful (Admin Env)!")
        return {
            "id": "admin", 
            "username": admin_username, 
            "password_hash": admin_password
        }
    
    # 2. Check Database for Users
    try:
        from db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, COALESCE(username, email), password_hash FROM users WHERE {USER_LOGIN_WHERE}",
            (username, username),
        )
        user_row = cur.fetchone()
        conn.close()
        
        if user_row:
            user_id, db_username, db_password_hash = user_row
            if verify_password(password, db_password_hash):
                print(f"DEBUG: Login successful for user '{db_username}'")
                return {
                    "id": str(user_id),
                    "username": db_username
                }
            else:
                print("DEBUG: Password verification failed")
        else:
             print("DEBUG: User not found in DB")
             
    except Exception as e:
        print(f"DEBUG: DB Auth Error: {e}")

    print("DEBUG: Login failed")
    return None


# ---------------------------


 
app = FastAPI(title="JD Analyzer Agent")
SERVER_BUILD = "hiring-openai-v24"
RESUME_UPLOAD_VERSION = "pdf-doc-docx-zip-v1"
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")

_AUTH_HTML_PAGES = {
    "/login": "login.html",
    "/auth/login": "login.html",
    "/sign-in": "login.html",
    "/signup": "signup.html",
    "/auth/signup": "signup.html",
    "/sign-up": "signup.html",
}

_PROTECTED_APP_PAGES = {"/", "/admin", "/recruiter", "/hr", "/interviews/status"}


def _resolve_user_from_token(token: str) -> Optional[dict]:
    """Return user dict if token is valid; any logged-in user has full app access."""
    if not token:
        return None
    admin_username = os.getenv("ADMIN_USERNAME", "hiring")
    if token == admin_username:
        return {"id": "admin", "username": admin_username}
    try:
        from db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, COALESCE(username, email) FROM users WHERE {USER_LOGIN_WHERE}",
            (token, token),
        )
        user_row = cur.fetchone()
        conn.close()
        if user_row:
            return {"id": str(user_row[0]), "username": user_row[1]}
    except Exception as e:
        print(f"Error validating token: {e}")
    return None


def _token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get("access_token")


class PortalAuthMiddleware(BaseHTTPMiddleware):
    """Require login for main app pages; no role-based restrictions."""

    async def dispatch(self, request, call_next):
        if request.method == "GET":
            path = request.url.path.rstrip("/") or "/"
            if path in _PROTECTED_APP_PAGES and path not in _AUTH_HTML_PAGES:
                if _resolve_user_from_token(_token_from_request(request) or "") is None:
                    return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


class AuthPagesMiddleware(BaseHTTPMiddleware):
    """Serve login/signup HTML before the router (works even if route table is stale)."""

    async def dispatch(self, request, call_next):
        if request.method == "GET":
            path = request.url.path.rstrip("/") or "/"
            filename = _AUTH_HTML_PAGES.get(path)
            if filename:
                filepath = os.path.join(_STATIC_DIR, filename)
                if os.path.isfile(filepath):
                    with open(filepath, encoding="utf-8") as fh:
                        return HTMLResponse(
                            fh.read(),
                            headers={"X-Hiring-App": "hiring-main", "X-Auth-Page": path},
                        )
                return HTMLResponse(
                    f"<h1>Missing {filename}</h1><p>Expected: {filepath}</p>"
                    f"<p><a href='/static/{filename}'>Try /static/{filename}</a></p>",
                    status_code=500,
                )
        return await call_next(request)


app.add_middleware(PortalAuthMiddleware)
app.add_middleware(AuthPagesMiddleware)


def _read_auth_html(filename: str) -> HTMLResponse:
    filepath = os.path.join(_STATIC_DIR, filename)
    with open(filepath, encoding="utf-8") as fh:
        return HTMLResponse(fh.read(), headers={"X-Hiring-Auth": filename})


@app.get("/whoami")
async def whoami():
    return {
        "app": "hiring-main",
        "server_build": SERVER_BUILD,
        "health": "/api/health",
        "jd_upload": "/api/v1/jd/analyze-pdf",
    }


@app.get("/api/health")
@app.get("/health")
async def api_health():
    from config import effective_resume_ai_provider

    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    from config import INTERVIEWER_EMAIL, HR_INTERVIEWER_EMAIL, CALENDAR_EMAIL, FROM_EMAIL

    return {
        "status": "ok",
        "app": "hiring-main",
        "server_build": SERVER_BUILD,
        "from_email": FROM_EMAIL,
        "interviewer_email": INTERVIEWER_EMAIL,
        "hr_interviewer_email": HR_INTERVIEWER_EMAIL,
        "calendar_email": CALENDAR_EMAIL,
        "signup": "v2",
        "jd_ai_provider": "openai",
        "jd_service_version": "jd-openai-v4",
        "jd_chat_model": os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "openai_configured": bool(key),
        "resume_upload_version": RESUME_UPLOAD_VERSION,
        "resume_formats": ["pdf", "doc", "docx", "zip"],
        "resume_ai_provider": "openai",
        "resume_parser": "resume-openai-v1",
        "pages": ["/login", "/signup", "/auth/login", "/auth/signup"],
        "api": ["/api/register", "/api/login", "/login", "/signup"],
    }


# Start the feedback scheduler when the application starts
@app.on_event("startup")
async def startup_event():
    """Initialize background tasks and DB on application startup."""
    # 1. Run DB Migrations
    try:
        import migrations
        print("[STARTUP] Running database migrations...")
        migrations.init_db()
        print("[STARTUP] Database migrations completed.")
    except Exception as e:
        print(f"[STARTUP] WARNING: Database migration failed: {e}")
        try:
            from db import get_connection
            conn = get_connection()
            cur = conn.cursor()
            migrations._ensure_users_auth_columns(cur)
            conn.commit()
            cur.close()
            conn.close()
            print("[STARTUP] Repaired users table (email/role/tenant_id).")
        except Exception as repair_err:
            print(f"[STARTUP] Users table repair failed: {repair_err}")

    # 2. Start Feedback Scheduler
    from feedback_scheduler import start_feedback_scheduler
    start_feedback_scheduler()
    print("[STARTUP] Feedback scheduler started")
    print("[STARTUP] Auth signup v2 ready (email + confirm_password) at POST /api/register")
    try:
        from config import effective_jd_ai_provider, OPENAI_CHAT_MODEL, OPENAI_API_KEY

        provider = effective_jd_ai_provider()
        print(f"[STARTUP] JD upload AI: {provider}" + (
            f" (model={OPENAI_CHAT_MODEL})" if provider == "openai" and OPENAI_API_KEY else ""
        ))
    except Exception as e:
        print(f"[STARTUP] JD AI config check failed: {e}")

    try:
        from config import (
            INTERVIEWER_EMAIL,
            HR_INTERVIEWER_EMAIL,
            CALENDAR_EMAIL,
            FROM_EMAIL,
            get_default_cc_emails,
        )

        print(
            f"[STARTUP] Mail: from={FROM_EMAIL} interviewer={INTERVIEWER_EMAIL} "
            f"hr_interviewer={HR_INTERVIEWER_EMAIL} calendar={CALENDAR_EMAIL} "
            f"cc={get_default_cc_emails()}"
        )
    except Exception as e:
        print(f"[STARTUP] Mail config check failed: {e}")


# Serve the minimal UI from ./static
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_index():
    return FileResponse("static/index.html")


@app.get("/admin")
async def get_admin_portal():
    return FileResponse("static/admin_portal_view.html")


@app.get("/recruiter")
async def get_recruiter_portal():
    return FileResponse(
        "static/recruiter_portal_view.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/hr")
async def get_hr_dashboard():
    return FileResponse("static/hr_dashboard_view.html")


@app.get("/interviews/status")
async def get_interviews_status_page():
    """HR dashboard (same access for every logged-in user)."""
    return FileResponse("static/hr_dashboard_view.html")


@app.post("/init-db")
def init_db_endpoint():
    """Run DB migrations (requires DB user to have extension creation rights).

    This endpoint is intentionally unprotected in this minimal example —
    in production protect it with auth.
    """
    try:
        import migrations

        migrations.init_db()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"status": "ok", "message": "migrations run"}
 
@app.get("/debug")
def debug():
    import os
    return {
        "JD_AI_PROVIDER": os.environ.get("JD_AI_PROVIDER", "openai"),
        "OPENAI_API_KEY_present": bool(os.environ.get("OPENAI_API_KEY")),
        "OPENAI_CHAT_MODEL": os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "CHAT_MODEL": os.environ.get("CHAT_MODEL"),
        "EMBEDDING_MODEL": os.environ.get("EMBEDDING_MODEL"),
    }

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint that returns a simple access token."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    # Return username as token (simple approach without JWT)
    return {"access_token": user["username"], "token_type": "bearer"}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Validate token; all authenticated users can use every feature."""
    user = _resolve_user_from_token(token)
    if user:
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


class AgencySignupRequest(BaseModel):
    email: str
    password: str
    confirm_password: str

    @field_validator("email")
    @classmethod
    def email_not_empty(cls, email: str):
        email = (email or "").strip()
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")
        return email.lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, password: str):
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")
        return password

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class AgencyLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_not_empty(cls, email: str):
        return (email or "").strip().lower()


def _register_user(payload: AgencySignupRequest) -> dict:
    """Shared signup logic: email + password with confirmation."""
    from db import get_connection
    import uuid

    email = str(payload.email).strip().lower()
    hashed_password = get_password_hash(payload.password)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM users WHERE {USER_LOGIN_WHERE}", (email, email))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        user_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, tenant_id)
            VALUES (%s, %s, %s, %s, 'user', %s)
            RETURNING id
            """,
            (user_id, email, email, hashed_password, DEFAULT_TENANT_ID),
        )
        conn.commit()
        return {"success": True, "message": "User created successfully", "user_id": user_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f"[SIGNUP] Error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not create account. Please try again.",
        )
    finally:
        conn.close()


@app.post("/api/register")
@app.post("/signup")
@app.post("/api/v1/agency/auth/signup")
async def signup(request: Request):
    """Register a new user with email and password confirmation."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid request body")

    try:
        payload = AgencySignupRequest(
            email=body.get("email") or body.get("username") or "",
            password=body.get("password") or "",
            confirm_password=body.get("confirm_password") or body.get("confirmPassword") or "",
        )
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            field = err.get("loc", ["field"])[-1]
            messages.append(f"{field}: {err.get('msg', 'invalid')}")
        raise HTTPException(status_code=400, detail="; ".join(messages) or "Invalid signup data")

    return _register_user(payload)


@app.post("/api/login")
@app.post("/login")
@app.post("/api/v1/agency/auth/login")
async def login_json(payload: AgencyLoginRequest):
    """Login with email and password; returns access token."""
    email = str(payload.email).strip().lower()
    user = authenticate_user(email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"access_token": user["username"], "token_type": "bearer"}


@app.get("/feedback-responses-link")
async def get_feedback_responses_link():
    """Redirect to Google Sheets with feedback responses."""
    from config import FEEDBACK_RESPONSES_SHEET_LINK
    from fastapi.responses import RedirectResponse, HTMLResponse
    
    if FEEDBACK_RESPONSES_SHEET_LINK and FEEDBACK_RESPONSES_SHEET_LINK != "PASTE_YOUR_GOOGLE_SHEETS_RESPONSES_LINK_HERE":
        return RedirectResponse(url=FEEDBACK_RESPONSES_SHEET_LINK)
    else:
        html = """
        <html>
        <head><title>Feedback Responses</title></head>
        <body style="font-family: Arial; padding: 40px; text-align: center;">
            <h2>⚠️ Feedback Responses Sheet Not Configured</h2>
            <p>Please update <code>FEEDBACK_RESPONSES_SHEET_LINK</code> in config.py with your Google Sheets link.</p>
            <p><strong>How to get the link:</strong></p>
            <ol style="text-align: left; max-width: 600px; margin: 20px auto;">
                <li>Open your Google Form</li>
                <li>Click "Responses" tab</li>
                <li>Click the green Sheets icon to create/open the responses spreadsheet</li>
                <li>Copy the URL from your browser</li>
                <li>Paste it in config.py</li>
            </ol>
            <button onclick="history.back()" style="padding: 10px 20px; font-size: 16px; cursor: pointer;">← Go Back</button>
        </body>
        </html>
        """
        return HTMLResponse(content=html)


@app.get("/feedback/confirm/{interview_id}")
async def confirm_feedback_status(interview_id: str, status: str):
    """
    Handle feedback confirmation from email.
    
    Args:
        interview_id: UUID of the interview
        status: 'yes' or 'no'
    """
    from fastapi.responses import RedirectResponse, HTMLResponse
    from db import get_connection
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Update status based on response
        if status.lower() == 'yes':
            # Mark interview as completed
            cur.execute(
                """
                UPDATE interview_schedules
                SET status = 'completed', updated_at = NOW()
                WHERE id = %s
                RETURNING interview_round
                """,
                [interview_id]
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            
            interview_round = row[0] if row else 1
            
            # Redirect to appropriate feedback form
            if interview_round == 2:
                return RedirectResponse(url=f"/static/hr-feedback-form.html?id={interview_id}", status_code=303)
            else:
                return RedirectResponse(url=f"/static/feedback-form.html?id={interview_id}", status_code=303)
        else:
            # Interview didn't happen - keep status as scheduled
            cur.close()
            conn.close()
            
            html_response = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Thank You</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        margin: 0;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    }
                    .container {
                        background: white;
                        padding: 40px;
                        border-radius: 10px;
                        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                        text-align: center;
                        max-width: 500px;
                    }
                    .icon {
                        font-size: 64px;
                        margin-bottom: 20px;
                    }
                    h1 {
                        color: #1f2937;
                        margin-bottom: 20px;
                    }
                    p {
                        color: #6b7280;
                        line-height: 1.6;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">📋</div>
                    <h1>Thank You</h1>
                    <p>We've recorded that the interview has not happened yet. No further action is needed at this time.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_response)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/interview/{interview_id}")
async def get_interview_details(interview_id: str):
    """
    Get interview details for pre-filling the feedback form.
    
    Args:
        interview_id: UUID of the interview
        
    Returns:
        JSON with candidate_name, jd_title, interview_date, interview_time
    """
    from db import get_connection
    
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                r.candidate_name,
                m.title as jd_title,
                i.confirmed_slot_time,
                r.email,
                m.short_id
            FROM interview_schedules i
            JOIN resumes r ON r.id = i.resume_id
            JOIN memories m ON m.id = i.jd_id
            WHERE i.id = %s
        """, [interview_id])
        
        row = cur.fetchone()
        
        if not row:
            return JSONResponse({"error": "Interview not found"}, status_code=404)
        
        candidate_name, jd_title, confirmed_slot_time, candidate_email, jd_short_id = row
        
        # Format date and time
        interview_date = confirmed_slot_time.strftime('%A, %B %d, %Y') if confirmed_slot_time else 'N/A'
        interview_time = confirmed_slot_time.strftime('%I:%M %p') if confirmed_slot_time else 'N/A'
        
        return {
            "candidate_name": candidate_name,
            "jd_title": jd_title,
            "jd_id": jd_short_id or 'N/A',
            "interview_date": interview_date,
            "interview_time": interview_time,
            "candidate_email": candidate_email
        }
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/feedback/submit")
async def submit_feedback(request: Dict[str, Any]):
    """
    Submit interview feedback to database.
    
    Expected JSON body:
    {
        "interview_id": "uuid",
        "technical_skills": 1-10,
        "education_training": 1-10,
        "work_experience": 1-10,
        "organizational_skills": 1-10,
        "communication": 1-10,
        "attitude": 1-10,
        "overall_rating": 1-10,
        "final_recommendation": "string",
        "comments": "string"
    }
    """
    from db import get_connection
    from config import INTERVIEWER_EMAIL
    
    try:
        interview_id = request.get("interview_id")
        
        # Get interview details for applicant_name and interview_date
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                r.candidate_name,
                i.confirmed_slot_time
            FROM interview_schedules i
            JOIN resumes r ON r.id = i.resume_id
            WHERE i.id = %s
        """, [interview_id])
        
        interview_row = cur.fetchone()
        if not interview_row:
            return JSONResponse({"success": False, "error": "Interview not found"}, status_code=404)
        
        candidate_name, confirmed_slot_time = interview_row
        interview_date = confirmed_slot_time.date() if confirmed_slot_time else None
        
        # Insert feedback into database
        cur.execute("""
            INSERT INTO feedback (
                interview_id,
                timestamp,
                applicant_name,
                interview_date,
                interviewer,
                interview_type,
                job_opening_id,
                technical_skills,
                education_training,
                work_experience,
                organizational_skills,
                communication,
                attitude,
                overall_rating,
                final_recommendation,
                comments
            ) VALUES (
                %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, [
            interview_id,
            candidate_name,
            interview_date,
            INTERVIEWER_EMAIL,
            request.get("interview_type", ""),
            request.get("job_opening_id", ""),
            float(request.get("technical_skills")),
            float(request.get("education_training")),
            float(request.get("work_experience")),
            float(request.get("organizational_skills")),
            float(request.get("communication")),
            float(request.get("attitude")),
            float(request.get("overall_rating")),
            request.get("final_recommendation"),
            request.get("comments", "")
        ])
        
        conn.commit()
        cur.close()
        conn.close()
        
        # If this is HR Round feedback, send decision emails automatically
        interview_type = request.get("interview_type", "")
        final_recommendation = request.get("final_recommendation")
        
        if interview_type == "HR Round" and final_recommendation:
            try:
                # Get candidate email
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT r.email, r.candidate_name, j.title
                    FROM interview_schedules i
                    JOIN resumes r ON r.id = i.resume_id
                    LEFT JOIN memories j ON j.id = i.jd_id
                    WHERE i.id = %s
                """, [interview_id])
                
                candidate_row = cur.fetchone()
                cur.close()
                conn.close()
                
                if candidate_row:
                    candidate_email, candidate_name, position = candidate_row
                    
                    # Parse HR feedback details from comments
                    comments = request.get("comments", "")
                    
                    def parse_field(field_name):
                        import re
                        regex = re.compile(f"{field_name}:\\s*(.+?)(?=\\n|$)", re.IGNORECASE)
                        match = regex.search(comments)
                        return match.group(1).strip() if match else "N/A"
                    
                    offered_package = parse_field("Offered Package")
                    joining_date = parse_field("Date of Joining")
                    
                    if final_recommendation == "Hire":
                        # Send congratulations email with offer letter PDF
                        from hr_decision_emails import generate_congratulations_email
                        from offer_letter_generator import generate_offer_letter_pdf
                        from email_sender import send_email
                        
                        # Generate offer letter PDF
                        pdf_bytes = generate_offer_letter_pdf(
                            candidate_name=candidate_name,
                            position=position or "AI Engineer (Trainee)",
                            ctc=offered_package if offered_package != "N/A" else "As per discussion",
                            joining_date=joining_date if joining_date != "N/A" else "To be confirmed"
                        )
                        
                        # Generate email
                        email_data = generate_congratulations_email(
                            candidate_name=candidate_name,
                            position=position or "AI Engineer (Trainee)",
                            ctc=offered_package if offered_package != "N/A" else "As per discussion",
                            joining_date=joining_date if joining_date != "N/A" else "To be confirmed"
                        )
                        
                        # Send email with PDF attachment
                        send_email(
                            to_email=candidate_email,
                            subject=email_data["subject"],
                            body=email_data["body"],
                            attachment_data=pdf_bytes,
                            attachment_filename=f"Offer_Letter_{candidate_name.replace(' ', '_')}.pdf"
                        )
                        
                        print(f"✅ Sent offer letter to {candidate_email}")
                        
                    elif final_recommendation == "Reject":
                        # Send rejection email
                        from hr_decision_emails import generate_rejection_email
                        from email_sender import send_email
                        
                        email_data = generate_rejection_email(
                            candidate_name=candidate_name,
                            position=position or "the position"
                        )
                        
                        send_email(
                            to_email=candidate_email,
                            subject=email_data["subject"],
                            body=email_data["body"]
                        )
                        
                        print(f"✅ Sent rejection email to {candidate_email}")
                        
            except Exception as email_error:
                print(f"⚠️ Error sending HR decision email: {email_error}")
                # Don't fail the feedback submission if email fails
        
        return {"success": True, "message": "Feedback submitted successfully"}
        
    except Exception as e:
        print(f"Error submitting feedback: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/feedback/view/{interview_id}")
async def view_feedback(interview_id: str):
    """
    Retrieve feedback for a specific interview.
    
    Returns feedback data including all ratings and comments.
    """
    from db import get_connection
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Fetch feedback for the interview
        cur.execute("""
            SELECT 
                technical_skills,
                education_training,
                work_experience,
                organizational_skills,
                communication,
                attitude,
                overall_rating,
                final_recommendation,
                comments,
                interview_type
            FROM feedback
            WHERE interview_id = %s
        """, [interview_id])
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return {"feedback": None}
        
        # Map database columns to response
        feedback = {
            "technical_skills": row[0],
            "education_training": row[1],
            "work_experience": row[2],
            "organizational_skills": row[3],
            "communication": row[4],
            "attitude": row[5],
            "overall_rating": row[6],
            "final_recommendation": row[7],
            "comments": row[8],
            "additional_comments": row[8],  # Alias for compatibility
            "interview_type": row[9]
        }
        
        return {"feedback": feedback}
        
    except Exception as e:
        print(f"Error fetching feedback: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/recruit/send-hr-decision")
async def send_hr_decision_email(request: Dict[str, Any]):
    """
    Manually send offer email with PDF attachment.
    """
    from db import get_connection
    from hr_decision_emails import generate_congratulations_email
    from offer_letter_generator import generate_offer_letter_pdf
    from email_sender import send_email
    
    try:
        # Debug logging
        import logging
        logging.basicConfig(filename='email_debug.log', level=logging.INFO, 
                          format='%(asctime)s - %(levelname)s - %(message)s')
        
        logging.info(f"Received request to send HR decision for interview_id: {request.get('interview_id')}")
        
        interview_id = request.get("interview_id")
        if not interview_id:
            logging.error("Interview ID missing")
            return JSONResponse({"success": False, "error": "Interview ID required"}, status_code=400)
            
        conn = get_connection()
        cur = conn.cursor()
        
        # Get candidate details and feedback
        cur.execute("""
            SELECT r.email, r.email, r.candidate_name, j.title, f.comments, f.final_recommendation
            FROM interview_schedules i
            JOIN resumes r ON r.id = i.resume_id
            LEFT JOIN memories j ON j.id = i.jd_id
            LEFT JOIN feedback f ON f.interview_id = i.id
            WHERE i.id = %s
        """, [interview_id])
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
             logging.error(f"Interview not found or no resume linked for id: {interview_id}")
             return JSONResponse({"success": False, "error": "Interview not found"}, status_code=404)
        
        # Handle cases where candidate_email might be in different columns (r.candidate_email vs r.email)
        candidate_email_1, candidate_email_2, candidate_name, position, comments, recommendation = row
        candidate_email = candidate_email_1 or candidate_email_2
        
        logging.info(f"Found candidate: {candidate_name}, Email: {candidate_email}, Position: {position}")
        
        if not candidate_email:
            logging.error("Candidate email is missing in database")
            return JSONResponse({"success": False, "error": "Candidate email not found"}, status_code=400)
        
        if not comments:
            comments = ""
            
        # Parse package details
        def parse_field(field_name):
            import re
            regex = re.compile(f"{field_name}:\\s*(.+?)(?=\\n|$)", re.IGNORECASE)
            match = regex.search(comments)
            return match.group(1).strip() if match else "N/A"
        
        offered_package = parse_field("Offered Package")
        joining_date = parse_field("Date of Joining")
        
        logging.info(f"Generating PDF for {candidate_name} with Package: {offered_package}")
        
        # Generate offer letter PDF
        pdf_bytes = generate_offer_letter_pdf(
            candidate_name=candidate_name,
            position=position or "AI Engineer (Trainee)",
            ctc=offered_package if offered_package != "N/A" else "As per discussion",
            joining_date=joining_date if joining_date != "N/A" else "To be confirmed"
        )
        
        logging.info("PDF Generated successfully")
        
        # Generate email
        email_data = generate_congratulations_email(
            candidate_name=candidate_name,
            position=position or "AI Engineer (Trainee)",
            ctc=offered_package if offered_package != "N/A" else "As per discussion",
            joining_date=joining_date if joining_date != "N/A" else "To be confirmed"
        )
        
        logging.info("Sending email via SMTP...")
        
        # Send email with PDF attachment
        result = send_email(
            to_email=candidate_email,
            subject=email_data["subject"],
            body=email_data["body"],
            attachment_data=pdf_bytes,
            attachment_filename=f"Offer_Letter_{candidate_name.replace(' ', '_')}.pdf"
        )
        
        logging.info(f"SMTP Result: {result}")
        
        if not result.get("success"):
            return JSONResponse({"success": False, "error": result.get("message")}, status_code=500)
        
        return {"success": True, "message": f"Offer email sent to {candidate_email}"}
        
    except Exception as e:
        import traceback
        logging.error(f"Error sending HR decision email: {e}")
        logging.error(traceback.format_exc())
        print(f"Error sending HR decision email: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/send-decision-email")
async def send_decision_email(request: Dict[str, Any]):
    """
    Manually send rejection email to candidate.
    Handles 'Reject' (HR) or 'Not Selected' (Technical) recommendations.
    """
    from db import get_connection
    from hr_decision_emails import generate_rejection_email
    from email_sender import send_email
    
    try:
        interview_id = request.get("interview_id")
        
        if not interview_id:
            return JSONResponse({"success": False, "error": "interview_id is required"}, status_code=400)
        
        conn = get_connection()
        cur = conn.cursor()
        
        # Get feedback and candidate details
        cur.execute("""
            SELECT 
                f.final_recommendation,
                r.candidate_name,
                r.email,
                j.title
            FROM feedback f
            JOIN interview_schedules i ON i.id = f.interview_id
            JOIN resumes r ON r.id = i.resume_id
            LEFT JOIN memories j ON j.id = i.jd_id
            WHERE f.interview_id = %s
            ORDER BY f.timestamp DESC
            LIMIT 1
        """, [interview_id])
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return JSONResponse({"success": False, "error": "Feedback not found for this interview"}, status_code=404)
        
        final_recommendation, candidate_name, candidate_email, jd_title = row
        
        # Determine email type based on recommendation
        if final_recommendation in ["Reject", "Not Selected", "Do Not Hire"]:
             email_data = generate_rejection_email(
                candidate_name=candidate_name,
                position=jd_title or "the position"
            )
             
             send_email(
                to_email=candidate_email,
                subject=email_data["subject"],
                body=email_data["body"]
            )
             
             return {"success": True, "message": f"Rejection email sent to {candidate_email}"}
        else:
             return JSONResponse({
                "success": False, 
                "error": f"This endpoint is only for rejections. Use 'Send Offer Email' for offers. Status: {final_recommendation}"
            }, status_code=400)
            
    except Exception as e:
        print(f"Error sending decision email: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)



@app.post("/sync-feedback-csv")
async def sync_feedback_csv(file: UploadFile = File(...)):
    """
    Upload CSV export from Google Sheets and sync to feedback table.
    Users should:
    1. Open the Google Sheets
    2. File -> Download -> CSV
    3. Upload here
    """
    import csv
    from io import StringIO
    from datetime import datetime
    from db import get_connection
    
    try:
        # Read the uploaded CSV
        contents = await file.read()
        csv_text = contents.decode('utf-8')
        csv_reader = csv.DictReader(StringIO(csv_text))
        
        conn = get_connection()
        cur = conn.cursor()
        
        # Ensure columns are NUMERIC to handle decimals (e.g. 4.5)
        # This is a safe operation to run repeatedly
        numeric_cols = [
            'technical_skills', 'education_training', 'work_experience', 
            'organizational_skills', 'communication', 'attitude', 'overall_rating'
        ]
        for col in numeric_cols:
            cur.execute(f"""
                DO $$ 
                BEGIN 
                    BEGIN
                        ALTER TABLE feedback ALTER COLUMN {col} TYPE NUMERIC(4, 1);
                    EXCEPTION
                        WHEN OTHERS THEN NULL;
                    END;
                END $$;
            """)
        conn.commit()
        
        # Clear existing feedback data (or you can skip this to keep historical data)
        # cur.execute("DELETE FROM feedback")
        
        inserted_count = 0
        skipped_count = 0
        errors = []
        
        for i, row in enumerate(csv_reader):
            try:
                # Parse the row data
                timestamp_str = row.get('Timestamp', '')
                applicant_name = row.get('Applicant Name', '')
                interview_date_str = row.get('Interview Date', '')
                interviewer = row.get('Interviewer', '')
                interview_type = row.get('Interview Type', '')
                job_opening_id = row.get('Job Opening ID', '')
                
                # Parse ratings (handle empty strings and decimals)
                def parse_rating(val):
                    if not val:
                        return 0.0
                    try:
                        return float(val)
                    except ValueError:
                        return 0.0

                technical_skills = parse_rating(row.get('Technical Skills'))
                education_training = parse_rating(row.get('Education/Training'))
                work_experience = parse_rating(row.get('Work Experience'))
                organizational_skills = parse_rating(row.get('Organizational Skills'))
                communication = parse_rating(row.get('Communication'))
                attitude = parse_rating(row.get('Attitude'))
                overall_rating = parse_rating(row.get('Overall Rating'))
                
                final_recommendation = row.get('Final recommendation', '')
                comments = row.get('Comments', '')
                
                # Parse dates
                timestamp = None
                if timestamp_str:
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%m/%d/%Y %H:%M:%S')
                    except:
                        try:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            pass
                
                interview_date = None
                if interview_date_str:
                    try:
                        interview_date = datetime.strptime(interview_date_str, '%m/%d/%Y').date()
                    except:
                        try:
                            interview_date = datetime.strptime(interview_date_str, '%Y-%m-%d').date()
                        except:
                            pass
                
                # Insert into database
                cur.execute("""
                    INSERT INTO feedback (
                        timestamp, applicant_name, interview_date, interviewer, 
                        interview_type, job_opening_id, technical_skills, 
                        education_training, work_experience, organizational_skills,
                        communication, attitude, overall_rating, 
                        final_recommendation, comments
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    timestamp, applicant_name, interview_date, interviewer,
                    interview_type, job_opening_id, technical_skills,
                    education_training, work_experience, organizational_skills,
                    communication, attitude, overall_rating,
                    final_recommendation, comments
                ))
                
                inserted_count += 1
                
            except Exception as e:
                error_msg = f"Row {i+1}: {str(e)}"
                print(f"Error processing row: {e}")
                errors.append(error_msg)
                skipped_count += 1
                continue
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            "success": True,
            "message": f"Successfully synced {inserted_count} feedback records",
            "inserted": inserted_count,
            "skipped": skipped_count,
            "errors": errors[:5]  # Return first 5 errors
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


class ClientCreate(BaseModel):
    name: str
    industry: Optional[str] = None


@app.get("/clients")
@app.get("/api/v1/agency/clients")
async def list_clients(current_user: dict = Depends(get_current_user)):
    from db import db_cursor
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, name, industry, created_at
                FROM clients
                ORDER BY name ASC
                """
            )
            rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "industry": row[2],
                    "created_at": row[3].isoformat() if row[3] else None
                } for row in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing clients: {e}")


@app.post("/clients")
@app.post("/api/v1/agency/clients")
async def create_client(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    content_type = request.headers.get("content-type", "")
    c_name = None
    c_industry = None
    
    if "application/json" in content_type:
        try:
            body = await request.json()
            c_name = body.get("name")
            c_industry = body.get("industry")
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            c_name = form.get("name")
            c_industry = form.get("industry")
        except Exception:
            pass
            
    if not c_name or not c_name.strip():
        raise HTTPException(status_code=400, detail="Client name is required")
        
    import uuid
    from db import db_cursor
    client_id = str(uuid.uuid4())
    default_tenant_id = '23cd7026-c85b-4f38-ad2d-bcd09cbc487c'
    
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO clients (id, tenant_id, name, industry)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE 
                SET industry = EXCLUDED.industry, updated_at = NOW()
                RETURNING id, name, industry
                """,
                (client_id, default_tenant_id, c_name.strip(), c_industry.strip() if c_industry else None)
            )
            row = cur.fetchone()
            return {
                "id": row[0],
                "name": row[1],
                "industry": row[2]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/jds")
@app.get("/api/v1/recruitment/jobs")
async def list_jds(
    client_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    from db import db_cursor
    try:
        with db_cursor() as cur:
            if client_id:
                cur.execute(
                    """
                    SELECT id, client_id, title, metadata, canonical_json, short_id, created_at
                    FROM memories
                    WHERE type = 'job' AND client_id = %s
                    ORDER BY created_at DESC
                    """,
                    [client_id]
                )
            else:
                cur.execute(
                    """
                    SELECT id, client_id, title, metadata, canonical_json, short_id, created_at
                    FROM memories
                    WHERE type = 'job'
                    ORDER BY created_at DESC
                    """
                )
            rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "client_id": row[1],
                    "title": row[2],
                    "metadata": row[3],
                    "canonical_json": row[4],
                    "short_id": row[5],
                    "created_at": row[6].isoformat() if row[6] else None
                } for row in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing JDs: {e}")


def _extract_pdf_text(contents: bytes) -> str:
    with pdfplumber.open(BytesIO(contents)) as pdf:
        return "\n".join([page.extract_text() or "" for page in pdf.pages])


 
 
async def _analyze_jd_pdf_openai_v5(
    *,
    file: UploadFile,
    job_id: Optional[str],
    client_id: Optional[str],
    source_url: Optional[str],
    current_user: dict,
) -> JSONResponse:
    """JD upload — OpenAI only (SERVER_BUILD v5)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY missing in hiring/.env — add key and restart RUN_HIRING_SERVER.bat",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    raw_jd_text = _extract_pdf_text(contents)
    if not raw_jd_text.strip():
        raise HTTPException(status_code=400, detail="JD text is empty after PDF extraction")

    user_id_val = current_user["id"] if current_user["id"] != "admin" else None
    target_client_id = (
        client_id if (client_id and client_id.strip()) else "60e80ea2-ae7f-46d6-b30d-f73293036729"
    )

    import importlib.util

    service_path = Path(__file__).resolve().parent / "jd_openai_service.py"
    spec = importlib.util.spec_from_file_location("jd_openai_service_v5", service_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail=f"Cannot load {service_path}")
    jd_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jd_mod)

    try:
        memory_json = jd_mod.process_jd_upload(
            raw_jd_text=raw_jd_text,
            job_id=job_id,
            source_url=source_url,
            created_by="jd_analyzer_agent_pdf",
            user_id=user_id_val,
            client_id=target_client_id,
        )
    except Exception as e:
        err = str(e)
        if "gemini" in err.lower() or "generativelanguage" in err.lower():
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Wrong/old server on port 8000 (Gemini). Stop all Python, run RUN_HIRING_SERVER.bat. "
                    f"Expected server_build={SERVER_BUILD}. {err[:300]}"
                ),
            )
        raise HTTPException(status_code=500, detail=f"[{SERVER_BUILD}] OpenAI JD error: {err}")

    response = JSONResponse(content=memory_json)
    response.headers["X-Server-Build"] = SERVER_BUILD
    response.headers["X-JD-AI-Provider"] = "openai"
    response.headers["X-JD-Service"] = memory_json.get("service_version", "jd-openai-v4")
    response.headers["X-App"] = "hiring-main"
    return response


@app.post("/api/v1/jd/analyze-pdf")
@app.post("/jd/analyze/pdf")
async def analyze_jd_pdf(
    job_id: Optional[str] = Form(default=None),
    client_id: Optional[str] = Form(default=None),
    source_url: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await _analyze_jd_pdf_openai_v5(
            file=file,
            job_id=job_id,
            client_id=client_id,
            source_url=source_url,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "Internal error (pdf)" in err or "gemini" in err.lower():
            raise HTTPException(
                status_code=500,
                detail=(
                    "You are hitting an OLD server (Gemini / Internal error pdf). "
                    "1) Task Manager → end all python.exe  2) Double-click RUN_HIRING_SERVER.bat "
                    f"3) Open /api/health — must show server_build={SERVER_BUILD}"
                ),
            )
        raise HTTPException(status_code=500, detail=f"[{SERVER_BUILD}] {err}")


def _link_resume_to_jd(resume_id: str, jd_id: str) -> tuple:
    """Score resume against JD and tag resume metadata for Scan (no outreach row)."""
    from psycopg2.extras import Json
    from db import db_cursor

    ats_score = None
    rank_val = None
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT 1 - (r.embedding <=> m.embedding) AS similarity
            FROM resumes r, memories m
            WHERE r.id = %s AND m.id = %s
            """,
            [resume_id, jd_id],
        )
        row = cur.fetchone()
        if not row:
            return ats_score, rank_val
        ats_score = int(max(0.0, min(1.0, float(row[0] or 0.0))) * 100)
        cur.execute(
            """
            UPDATE resumes
            SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            [Json({"linked_jd_id": jd_id, "ats_score": ats_score}), resume_id],
        )
    return ats_score, rank_val


@app.post("/resumes/upload")
async def upload_resumes(
    files: List[UploadFile] = File(...),
    jd_id: Optional[str] = Form(default=None),
    source_url: Optional[str] = Form(default=None),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload resumes: PDF, Word (.doc/.docx), or ZIP (containing those formats).
    Each file is parsed, stored, and optionally matched to jd_id.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    results: List[Dict[str, Any]] = []
    user_id_val = current_user["id"] if current_user["id"] != "admin" else None
    jd_id_clean = jd_id.strip() if jd_id and jd_id.strip() else None

    for file in files:
        filename = file.filename or "unknown"

        if not is_supported_upload_filename(filename):
            results.append({
                "file_name": filename,
                "status": "skipped",
                "reason": "unsupported format (use PDF, Word .doc/.docx, or ZIP)",
            })
            continue

        try:
            contents = await file.read()
            if not contents:
                results.append({
                    "file_name": filename,
                    "status": "error",
                    "reason": "empty file",
                })
                continue

            try:
                entries = expand_upload(filename, contents)
            except ValueError as e:
                results.append({
                    "file_name": filename,
                    "status": "error",
                    "reason": str(e),
                })
                continue

            if not entries:
                reason = (
                    "ZIP contains no PDF or Word resumes"
                    if filename.lower().endswith(".zip")
                    else "no readable resume content"
                )
                results.append({
                    "file_name": filename,
                    "status": "skipped",
                    "reason": reason,
                })
                continue

            for entry_name, entry_bytes in entries:
                try:
                    raw_text = extract_resume_text(entry_name, entry_bytes).strip()
                    if not raw_text:
                        results.append({
                            "file_name": entry_name,
                            "status": "error",
                            "reason": "no text extracted",
                        })
                        continue

                    processed = process_resume_text(
                        raw_text=raw_text,
                        source_url=source_url,
                        file_name=entry_name,
                        user_id=user_id_val,
                    )
                    resume_id = processed["resume_id"]
                    parsed = processed["parsed"]
                    ats_score, rank_val = None, None
                    if jd_id_clean:
                        ats_score, rank_val = _link_resume_to_jd(resume_id, jd_id_clean)

                    results.append({
                        "file_name": entry_name,
                        "status": "ok",
                        "resume_id": resume_id,
                        "candidate_name": parsed.get("candidate_name"),
                        "current_title": parsed.get("current_title"),
                        "ats_score": ats_score,
                        "rank": rank_val,
                    })
                except Exception as e:
                    err = str(e)
                    if "429" in err or "quota" in err.lower() or "generativelanguage" in err:
                        err = (
                            "AI quota exceeded (Gemini). Set RESUME_AI_PROVIDER=openai in .env "
                            "and restart RUN_HIRING_SERVER.bat."
                        )
                    results.append({
                        "file_name": entry_name,
                        "status": "error",
                        "reason": err,
                    })

        except Exception as e:
            results.append({
                "file_name": filename,
                "status": "error",
                "reason": str(e),
            })

    if jd_id_clean:
        try:
            from match_insights import enrich_matches

            ok_payload = [
                {
                    "resume_id": r["resume_id"],
                    "ats_score": r.get("ats_score") or 0,
                    "candidate_name": r.get("candidate_name"),
                    "current_title": r.get("current_title"),
                }
                for r in results
                if r.get("status") == "ok" and r.get("resume_id")
            ]
            if ok_payload:
                enriched = enrich_matches(jd_id_clean, ok_payload)
                by_id = {str(e["resume_id"]): e for e in enriched}
                for r in results:
                    if r.get("status") != "ok":
                        continue
                    ins = by_id.get(str(r.get("resume_id")))
                    if ins:
                        r["matched_skills"] = ins.get("matched_skills") or []
                        r["missing_skills"] = ins.get("missing_skills") or []
                        r["reason_to_select"] = ins.get("reason_to_select") or ""
        except Exception:
            pass

    response = JSONResponse(content={"count": len(results), "items": results})
    response.headers["X-Server-Build"] = SERVER_BUILD
    response.headers["X-Resume-Upload-Version"] = RESUME_UPLOAD_VERSION
    response.headers["X-Resume-Formats"] = "pdf,doc,docx,zip"
    return response



    


@app.post("/match/top-by-role")
async def get_top_matches_by_role(
    role_name: str = Form(...),
    top_k: int = Form(3),
):
    """
    Input from UI:
      - role_name (e.g. 'Senior Data Scientist')
      - top_k (3 or 5)

    Backend:
      - finds latest JD with that role in memories (type='job')
      - computes vector similarity with all resumes
      - returns top-K resumes with ATS score + file_name + candidate_name.
    """
    # If top_k is very large (e.g. 1000), it effectively returns "all"
    try:
        matches = get_top_matches_for_role(role_name=role_name, top_k=top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error (match/top-by-role): {e}")

    return {
        "role_name": role_name,
        "top_k": top_k,
        "matches": matches,
    }


@app.post("/match/top-by-jd")
async def get_top_matches_by_jd_id(
    jd_id: str = Form(...),
    top_k: int = Form(3),
    current_user: dict = Depends(get_current_user),
):
    """
    Scan all resumes against JD embedding; return top-K with skill insights.
    """
    try:
        from ranking import get_scan_matches_for_jd_memory
        from match_insights import enrich_matches

        top_k = max(1, min(int(top_k), 50))
        matches = get_scan_matches_for_jd_memory(jd_memory_id=jd_id, top_k=top_k)
        matches = enrich_matches(jd_id, matches)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error (match/top-by-jd): {e}")

    return {
        "jd_id": jd_id,
        "top_k": top_k,
        "matches": matches,
        "source": "scan",
    }


@app.post("/match/scan-by-jd")
async def scan_matches_by_jd(
    jd_id: str = Form(...),
    top_k: int = Form(5),
    current_user: dict = Depends(get_current_user),
):
    """Alias for scan button — top-K global resume match with reasoning."""
    return await get_top_matches_by_jd_id(jd_id=jd_id, top_k=top_k, current_user=current_user)


@app.post("/match/enrich-rankings")
async def enrich_rankings(
    jd_id: str = Form(...),
    candidates_json: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Fill matched_skills, missing_skills, and reason_to_select for ranking tiles.
    Body: candidates_json = [{\"resume_id\": \"...\", \"ats_score\": 70, ...}, ...]
    """
    import json as _json
    from match_insights import enrich_matches

    try:
        rows = _json.loads(candidates_json or "[]")
        if not isinstance(rows, list):
            raise ValueError("candidates_json must be a JSON array")
    except (ValueError, _json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid candidates_json: {e}")

    payload = [r for r in rows if isinstance(r, dict) and r.get("resume_id")]
    enriched = enrich_matches(jd_id, payload)
    return {"jd_id": jd_id, "candidates": enriched, "count": len(enriched)}


@app.get("/match/by-jd/{jd_id}")
async def get_match_by_jd(
    jd_id: str,
    top_k: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """
    Direct applicants (candidate_outreach) for a JD, with skill insights.
    """
    try:
        from db import db_cursor
        from match_insights import enrich_match

        with db_cursor() as cur:
            cur.execute(
                """
                SELECT
                    co.id AS outreach_id,
                    co.resume_id,
                    co.jd_id,
                    co.candidate_name,
                    co.candidate_email,
                    co.ats_score,
                    co.rank,
                    co.sent_at,
                    r.title AS current_title,
                    r.metadata->>'file_name' AS file_name
                FROM candidate_outreach co
                JOIN resumes r ON co.resume_id = r.id
                WHERE co.jd_id = %s
                ORDER BY co.ats_score DESC NULLS LAST, co.sent_at DESC
                LIMIT %s
                """,
                [jd_id, max(1, min(int(top_k), 100))],
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            item = {
                "outreach_id": row[0],
                "resume_id": row[1],
                "jd_id": row[2],
                "candidate_name": row[3],
                "candidate_email": row[4],
                "ats_score": row[5],
                "rank": row[6],
                "sent_at": row[7].isoformat() if row[7] else None,
                "current_title": row[8],
                "file_name": row[9],
                "source": "direct",
            }
            try:
                item = enrich_match(jd_id, item)
            except Exception:
                pass
            results.append(item)

        return {
            "applicants": results,
            "source": "direct",
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error matching by JD: {e}")


@app.post("/send-emails")
async def send_emails_to_candidates(
    jd_id: str = Form(...),
    candidate_ids: List[str] = Form(...),
    insights_json: Optional[str] = Form(None),
):
    """
    Send personalized emails to selected candidates.
    
    Args:
        jd_id: Database UUID of the JD
        candidate_ids: List of resume IDs to send emails to
    
    Returns:
        Summary of sent emails with success/failure status
    """
    from db import get_connection
    from mailing_agent import generate_personalized_email
    from email_sender import send_email
    from config import SMTP_PASSWORD, SMTP_USER, FROM_EMAIL
    import uuid

    if not (SMTP_PASSWORD or "").strip():
        raise HTTPException(
            status_code=503,
            detail=(
                "SMTP_PASSWORD is not set in .env. Add the app password for "
                f"{SMTP_USER or FROM_EMAIL} (see EMAIL_SETUP.md), then restart the server."
            ),
        )

    results = []
    conn = get_connection()
    
    try:
        # Fetch JD details including embedding
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, canonical_json, embedding FROM memories WHERE id = %s",
            [jd_id]
        )
        jd_row = cur.fetchone()
        
        if not jd_row:
            raise HTTPException(status_code=404, detail=f"JD not found: {jd_id}")
        
        jd_data = {
            "id": jd_row[0],
            "title": jd_row[1],
            "canonical_json": jd_row[2],
            "role": jd_row[2].get("role") if jd_row[2] else "Position",
            "embedding": jd_row[3] # Get the JD embedding
        }
        
        # Process each candidate
        for idx, resume_id in enumerate(candidate_ids, start=1):
            try:
                # Fetch resume details AND calculate similarity on the fly
                # We use the JD embedding literal for the distance calculation
                jd_embedding_literal = jd_data["embedding"]
                
                cur.execute(
                    """
                    SELECT 
                        id, 
                        candidate_name, 
                        email, 
                        canonical_json, 
                        metadata, 
                        embedding,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM resumes 
                    WHERE id = %s
                    """,
                    [jd_embedding_literal, resume_id]
                )
                resume_row = cur.fetchone()
                
                if not resume_row:
                    results.append({
                        "resume_id": resume_id,
                        "status": "error",
                        "message": "Resume not found"
                    })
                    continue
                
                similarity = float(resume_row[6])
                ats_score = int(max(0.0, min(1.0, similarity)) * 100)
                
                candidate_data = {
                    "id": resume_row[0],
                    "candidate_name": resume_row[1],
                    "email": resume_row[2],
                    "canonical_json": resume_row[3],
                    "metadata": resume_row[4],
                    "embedding": resume_row[5],
                }
                scan_row = insights_by_resume.get(str(resume_id))
                if scan_row:
                    candidate_data["matched_skills"] = scan_row.get("matched_skills") or []
                    candidate_data["reason_to_select"] = scan_row.get("reason_to_select") or ""
                    if scan_row.get("current_title"):
                        cj = candidate_data.get("canonical_json") or {}
                        if isinstance(cj, dict):
                            cj = {**cj, "current_title": scan_row["current_title"]}
                            candidate_data["canonical_json"] = cj
                else:
                    try:
                        from match_insights import enrich_match

                        enriched = enrich_match(
                            jd_id,
                            {
                                "resume_id": str(resume_id),
                                "ats_score": ats_score,
                                "candidate_name": candidate_data.get("candidate_name"),
                            },
                        )
                        candidate_data["matched_skills"] = enriched.get("matched_skills") or []
                        candidate_data["reason_to_select"] = enriched.get("reason_to_select") or ""
                    except Exception:
                        pass

                candidate_email = candidate_data.get("email")
                if not candidate_email:
                    results.append({
                        "resume_id": resume_id,
                        "candidate_name": candidate_data.get("candidate_name"),
                        "status": "error",
                        "message": "No email address found"
                    })
                    continue
                
                # Create outreach record
                outreach_id = str(uuid.uuid4())
                
                # Generate personalized email
                email_content = generate_personalized_email(
                    candidate_data=candidate_data,
                    jd_data=jd_data,
                    outreach_id=outreach_id,
                    rank=idx,
                    ats_score=ats_score 
                )
                
                # Send email
                send_result = send_email(
                    to_email=candidate_email,
                    subject=email_content["subject"],
                    html_body=email_content["body"]
                )
                
                if send_result["success"]:
                    # Store in database with embedding and REAL ATS score
                    embedding_literal = candidate_data.get("embedding")
                    
                    cur.execute(
                        """
                        INSERT INTO candidate_outreach 
                        (id, resume_id, jd_id, candidate_email, candidate_name, 
                         email_subject, email_body, embedding, rank, ats_score, email_sent, sent_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, TRUE, NOW())
                        """,
                        [
                            outreach_id,
                            resume_id,
                            jd_id,
                            candidate_email,
                            candidate_data.get("candidate_name"),
                            email_content["subject"],
                            email_content["body"],
                            embedding_literal,
                            idx,
                            ats_score,
                        ],
                    )
                    conn.commit()
                    
                    results.append({
                        "resume_id": resume_id,
                        "candidate_name": candidate_data.get("candidate_name"),
                        "email": candidate_email,
                        "status": "success",
                        "message": "Email sent successfully",
                        "ats_score": ats_score
                    })
                else:
                    results.append({
                        "resume_id": resume_id,
                        "candidate_name": candidate_data.get("candidate_name"),
                        "email": candidate_email,
                        "status": "error",
                        "message": send_result["message"]
                    })
                    
            except Exception as e:
                results.append({
                    "resume_id": resume_id,
                    "status": "error",
                    "message": str(e)
                })
        
        cur.close()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending emails: {str(e)}")
    finally:
        conn.close()    
    return {
        "total": len(candidate_ids),
        "sent": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "results": results
    }


def _candidate_link_denied_html(message: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><title>Access denied - Tek Leaders</title>
<style>
  body {{ font-family: Arial, sans-serif; display: flex; justify-content: center;
    align-items: center; min-height: 100vh; margin: 0; background: #f3f4f6; }}
  .box {{ background: white; padding: 40px; border-radius: 10px; max-width: 480px;
    text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
  h1 {{ color: #dc2626; }}
  p {{ color: #6b7280; line-height: 1.6; }}
</style>
</head>
<body><div class="box"><h1>Unable to proceed</h1><p>{message}</p></div></body>
</html>
"""


@app.get("/acknowledge/{outreach_id}")
async def acknowledge_interest(outreach_id: str, response: str, token: str | None = None):
    """
    Record candidate's acknowledgement (interested/not_interested).
    
    Args:
        outreach_id: UUID of the outreach record
        response: 'interested' or 'not_interested'
    
    Returns:
        HTML confirmation page
    """
    from db import get_connection
    from fastapi.responses import HTMLResponse
    
    if response not in ['interested', 'not_interested']:
        raise HTTPException(status_code=400, detail="Invalid response")

    from link_auth import verify_candidate_token

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT candidate_name, jd_id, candidate_email, acknowledgement
            FROM candidate_outreach
            WHERE id = %s
            """,
            [outreach_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Outreach record not found")

        candidate_name, jd_id, candidate_email, prior_ack = row
        candidate_email = (candidate_email or "").strip()
        if not candidate_email:
            raise HTTPException(status_code=400, detail="Candidate email not on file")

        if not verify_candidate_token(outreach_id, candidate_email, token):
            return HTMLResponse(
                status_code=403,
                content=_candidate_link_denied_html(
                    "Only the candidate who received this email can respond. "
                    "Open the link from your own inbox, or contact recruiting."
                ),
            )

        if prior_ack:
            message = (
                f"Your response was already recorded, {candidate_name or 'Candidate'}."
            )
            color = "#6b7280"
        else:
            cur.execute(
                """
                UPDATE candidate_outreach
                SET acknowledgement = %s, acknowledged_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                [response, outreach_id],
            )
            conn.commit()
        
        cur.close()

        candidate_name = candidate_name or "Candidate"

        # Automatically schedule interview if candidate is interested
        if not prior_ack and response == 'interested':
            try:
                from interview_scheduler import schedule_interview_for_single_candidate
                
                # Schedule for the first available date (automatically finds it)
                print(f"[DEBUG] Attempting to schedule interview for outreach_id={outreach_id}")
                schedule_result = schedule_interview_for_single_candidate(
                    outreach_id=outreach_id,
                    num_slots=3
                )
                
                print(f"[DEBUG] Schedule result: {schedule_result}")
                
                # Check if scheduling was successful
                if schedule_result.get('success'):
                    interview_date = schedule_result.get('interview_date')
                    message = f"Thank you, {candidate_name}! We've sent you an interview invitation email for {interview_date}. Please check your inbox and select your preferred time slot."
                elif 'error' in schedule_result:
                    # Error occurred during scheduling
                    print(f"[ERROR] Scheduling error: {schedule_result.get('error')}")
                    message = f"Thank you, {candidate_name}! We've recorded your interest and our team will contact you soon."
                elif 'message' in schedule_result:
                    # Already scheduled
                    message = f"Thank you, {candidate_name}! {schedule_result['message']}"
                else:
                    print(f"[WARNING] Unexpected schedule result format: {schedule_result}")
                    message = f"Thank you, {candidate_name}! We've recorded your interest and our team will contact you soon."
                    
            except Exception as e:
                # If scheduling fails, still acknowledge but don't show error to candidate
                print(f"[EXCEPTION] Auto-scheduling failed: {e}")
                import traceback
                traceback.print_exc()
                message = f"Thank you, {candidate_name}! We've recorded your interest and our team will contact you soon."
            
            color = "#10b981"
        elif not prior_ack:
            message = f"Thank you for your response, {candidate_name}. We appreciate your time."
            color = "#6b7280"
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Response Recorded - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background-color: #f3f4f6;
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: {color};
            margin-bottom: 20px;
        }}
        p {{
            color: #6b7280;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">{'✓' if response == 'interested' else '✗'}</div>
        <h1>Response Recorded</h1>
        <p>{message}</p>
    </div>
</body>
</html>
"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recording acknowledgement: {str(e)}")
    finally:
        conn.close()


@app.get("/confirm-interview/{interview_id}")
async def confirm_interview(
    interview_id: str,
    slot: str,
    outreach_id: str | None = None,
    token: str | None = None,
):
    """
    Confirm a candidate's selected interview time slot.
    Automatically creates a Google Calendar event and sends final emails.
    
    Args:
        interview_id: UUID of the interview
        slot: Selected slot ID (slot1, slot2, or slot3)
        outreach_id: Outreach record id (must match invited candidate)
        token: Signed token from candidate email link
    
    Returns:
        HTML confirmation page with Meet link and event details
    """
    from interview_scheduler import confirm_interview_slot
    from fastapi.responses import HTMLResponse
    
    try:
        result = confirm_interview_slot(interview_id, slot, outreach_id, token)
        
        if "error" in result:
            # Log error for debugging
            import sys
            print(f"[ERROR] Interview confirmation failed: {result['error']}", file=sys.stderr)
            message = result["error"]
            color = "#dc3545"
            icon = "❌"
            meet_link = None
            event_link = None
        else:
            meet_link = result.get("meet_link")
            event_link = result.get("event_link")
            message = f"Your interview has been confirmed! Check your email for the Google Meet link and calendar invitation."
            color = "#28a745"
            icon = "✅"
        
        meet_html = ""
        if meet_link:
            meet_html = f"""
            <div style="margin-top: 20px; padding: 20px; background-color: #e8f5e9; border-radius: 8px; border-left: 4px solid #4caf50;">
                <p style="color: #2e7d32; font-weight: bold;">📹 Google Meet Link:</p>
                <a href="{meet_link}" style="color: #4caf50; text-decoration: none; word-break: break-all;">{meet_link}</a>
            </div>
            """
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Interview Confirmation - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 600px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: {color};
            margin-bottom: 20px;
            font-size: 28px;
        }}
        p {{
            color: #333;
            line-height: 1.6;
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">{icon}</div>
        <h1>Interview Confirmed</h1>
        <p>{message}</p>
        {meet_html}
    </div>
</body>
</html>
"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error confirming interview: {str(e)}")


@app.post("/schedule-interviews")
async def schedule_interviews(
    jd_id: str = Form(...),
    interview_date: str = Form(...)  # Format: YYYY-MM-DD
):
    """
    Schedule interviews for all interested candidates for a given JD.
    
    Args:
        jd_id: Database UUID of the JD
        interview_date: Date for interviews (YYYY-MM-DD format)
    
    Returns:
        Summary of scheduled interviews
    """
    from interview_scheduler import schedule_interviews_for_interested_candidates
    from datetime import datetime
    
    try:
        # Parse the date
        date_obj = datetime.strptime(interview_date, "%Y-%m-%d")
        
        # Schedule interviews
        result = schedule_interviews_for_interested_candidates(
            jd_id=jd_id,
            interview_date=date_obj,
            num_slots=3
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scheduling interviews: {str(e)}")


@app.get("/interviews/action/{interview_id}/{action}")
async def handle_approvals(interview_id: str, action: str):
    """
    Handle interviewer's response to interview approval request.
    
    Args:
        interview_id: UUID of the interview
        action: 'approve' or 'reject'
    
    Returns:
        HTML response confirming the action
    """
    from interview_scheduler import approve_interview, process_reschedule_request
    from fastapi.responses import HTMLResponse
    from db import get_connection
    from datetime import datetime
    
    if action not in ['approve', 'reject']:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve' or 'reject'")
    
    try:
        if action == 'approve':
            # Approve the interview and create calendar event
            result = approve_interview(interview_id)
            
            if "error" in result:
                message = f"Error: {result['error']}"
                color = "#dc3545"
                icon = "❌"
            else:
                message = "Interview approved! Calendar invite has been sent to both you and the candidate."
                color = "#28a745"
                icon = "✅"
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Interview {action.title()}ed</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        margin: 0;
                        background-color: #f5f5f5;
                    }}
                    .container {{
                        background: white;
                        padding: 30px;
                        border-radius: 10px;
                        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                        text-align: center;
                        max-width: 400px;
                    }}
                    .icon {{
                        font-size: 48px;
                        margin-bottom: 20px;
                    }}
                    .message {{
                        color: {color};
                        font-size: 18px;
                        margin-bottom: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon">{icon}</div>
                    <div class="message">{message}</div>
                    <p>You can close this window now.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)

        else:  # action == 'reject'
            # Show reschedule form
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT r.candidate_name, m.title 
                    FROM interview_schedules i
                    JOIN resumes r ON r.id = i.resume_id
                    JOIN memories m ON m.id = i.jd_id
                    WHERE i.id = %s
                    """,
                    [interview_id]
                )
                row = cur.fetchone()
                cur.close()
                
                if not row:
                    raise HTTPException(status_code=404, detail="Interview not found")
                    
                candidate_name, jd_title = row
                
                # Return reschedule form
                html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Reschedule Interview - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 90%;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 24px;
            text-align: center;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
            text-align: center;
        }}
        label {{
            display: block;
            margin-top: 15px;
            margin-bottom: 5px;
            color: #333;
            font-weight: bold;
        }}
        input[type="date"], input[type="time"] {{
            width: calc(100% - 22px); /* Account for padding and border */
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
            box-sizing: border-box;
        }}
        button {{
            width: 100%;
            padding: 12px;
            background-color: #ffc107; /* Warning color for reschedule */
            color: #333;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 20px;
            transition: background-color 0.3s ease;
        }}
        button:hover {{
            background-color: #e0a800;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🗓️ Request Reschedule</h1>
        <p class="subtitle">Suggest a new time for <strong>{candidate_name}</strong><br>Role: {jd_title}</p>
        
        <form action="/interviews/reschedule/{interview_id}" method="post">
            <label for="new_date">Proposed Date</label>
            <input type="date" id="new_date" name="new_date" required min="{datetime.now().strftime('%Y-%m-%d')}">
            
            <label for="new_time">Proposed Time</label>
            <input type="time" id="new_time" name="new_time" required>
            
            <button type="submit">Send Proposal</button>
        </form>
    </div>
</body>
</html>
                """
                return HTMLResponse(content=html_content)

            except Exception as e:
                return HTMLResponse(content=f"Error loading form: {str(e)}", status_code=500)
            finally:
                conn.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing response: {str(e)}")


@app.post("/interviewer/reschedule/{interview_id}")
async def interviewer_reschedule(
    interview_id: str,
    new_date: str = Form(...),
    new_time: str = Form(...)
):
    """
    Process interviewer's reschedule request.
    
    Args:
        interview_id: UUID of the interview
        new_date: New proposed date (YYYY-MM-DD)
        new_time: New proposed time (HH:MM)
    
    Returns:
        HTML confirmation
    """
    from interview_scheduler import process_reschedule_request
    from fastapi.responses import HTMLResponse
    
    try:
        result = process_reschedule_request(interview_id, new_date, new_time)
        
        if "error" in result:
            message = f"Error: {result['error']}"
            color = "#dc3545"
            icon = "❌"
        else:
            message = "Reschedule request sent to candidate. They will receive an email with the new proposed time."
            color = "#28a745"
            icon = "✅"
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Reschedule Sent - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 500px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: {color};
            margin-bottom: 20px;
            font-size: 28px;
        }}
        p {{
            color: #333;
            line-height: 1.6;
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">{icon}</div>
        <h1>Reschedule Request Sent</h1>
        <p>{message}</p>
    </div>
</body>
</html>
"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing reschedule: {str(e)}")


@app.get("/candidate/accept-reschedule/{interview_id}")
async def candidate_accept_reschedule(interview_id: str):
    """
    Candidate accepts the interviewer's proposed reschedule time.
    This will approve the interview and create the calendar event.
    
    Args:
        interview_id: UUID of the interview
    
    Returns:
        HTML confirmation page
    """
    from interview_scheduler import approve_interview
    from fastapi.responses import HTMLResponse
    
    try:
        # Approve the rescheduled interview
        result = approve_interview(interview_id)
        
        if "error" in result:
            message = f"Error: {result['error']}"
            color = "#dc3545"
            icon = "❌"
        else:
            message = "Thank you for confirming! Calendar invite has been sent to your email. We look forward to meeting you!"
            color = "#28a745"
            icon = "✅"
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Reschedule Confirmed - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .container {{
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 500px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: {color};
            margin-bottom: 20px;
            font-size: 28px;
        }}
        p {{
            color: #333;
            line-height: 1.6;
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">{icon}</div>
        <h1>Interview Confirmed</h1>
        <p>{message}</p>
    </div>
</body>
</html>
"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error accepting reschedule: {str(e)}")


@app.get("/candidate/decline-reschedule/{interview_id}")
async def candidate_decline_reschedule(interview_id: str):
    """
    Candidate declines the interviewer's proposed time and requests different options.
    This will generate new time slots and send them to the candidate.
    
    Args:
        interview_id: UUID of the interview
    
    Returns:
        HTML page with new time slot options
    """
    from db import get_connection
    from fastapi.responses import HTMLResponse
    from interview_scheduler import _fetch_time_slots
    from datetime import datetime, timedelta
    from config import BASE_URL, COMPANY_NAME
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Fetch interview details
        cur.execute(
            """
            SELECT i.interview_date, i.outreach_id, r.candidate_name, m.title, m.id
            FROM interview_schedules i
            JOIN resumes r ON r.id = i.resume_id
            JOIN memories m ON m.id = i.jd_id
            WHERE i.id = %s
            """,
            [interview_id]
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        interview_date, outreach_id, candidate_name, jd_title, jd_id = row
        
        # Generate new time slots for the same date
        time_slots = _fetch_time_slots(interview_date, 3)
        
        # Generate HTML for slot options
        slots_html = ""
        for idx, slot in enumerate(time_slots, 1):
            start_time = slot['start_time'].strftime('%I:%M %p').lstrip('0')
            end_time = slot['end_time'].strftime('%I:%M %p').lstrip('0')
            slot_id = f"slot{idx}"
            
            confirm_url = f"{BASE_URL}/confirm-interview/{interview_id}?slot={slot_id}&outreach_id={outreach_id}"
            
            slots_html += f"""
                <div class="slot-option">
                    <strong>Option {idx}: {start_time} - {end_time}</strong><br>
                    <a href="{confirm_url}" class="slot-button">Select This Time</a>
                </div>
            """
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Select New Time - Tek Leaders</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f5f5f5;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            font-size: 24px;
            margin-bottom: 10px;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
        }}
        .slot-option {{
            margin: 15px 0;
            padding: 15px;
            background-color: #f8f9fa;
            border-left: 4px solid #4CAF50;
            border-radius: 4px;
        }}
        .slot-button {{
            display: inline-block;
            padding: 12px 30px;
            background-color: #4CAF50;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            margin-top: 10px;
        }}
        .slot-button:hover {{
            background-color: #45a049;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Select Your Preferred Time</h1>
        <p class="subtitle">Hi {candidate_name}, please choose one of the following time slots for your {jd_title} interview on {interview_date.strftime('%A, %B %d, %Y')}:</p>
        
        {slots_html}
        
        <p style="margin-top: 30px; font-size: 14px; color: #666;">
            If none of these times work, please reply to the original email and we'll work with you to find a suitable time.
        </p>
    </div>
</body>
</html>
"""
        
        cur.close()
        conn.close()
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing decline: {str(e)}")


@app.get("/interviews/list")
async def get_interviews_list(jd_id: str = None):
    """
    Get status of all scheduled interviews, optionally filtered by JD.
    
    Args:
        jd_id: Optional JD ID to filter by
    
    Returns:
        List of scheduled interviews with their status
    """
    from db import get_connection
    
    conn = get_connection()
    
    try:
        cur = conn.cursor()
        
        if jd_id:
            query = """
                SELECT 
                    i.id,
                    i.interview_date,
                    i.status,
                    i.selected_slot,
                    i.confirmed_slot_time,
                    r.candidate_name,
                    r.email,
                    m.title as jd_title
                FROM interview_schedules i
                JOIN resumes r ON r.id = i.resume_id
                JOIN memories m ON m.id = i.jd_id
                WHERE i.jd_id = %s
                ORDER BY i.interview_date DESC, i.created_at DESC
            """
            cur.execute(query, [jd_id])
        else:
            query = """
                SELECT 
                    i.id,
                    i.interview_date,
                    i.status,
                    i.selected_slot,
                    i.confirmed_slot_time,
                    r.candidate_name,
                    r.email,
                    m.title as jd_title
                FROM interview_schedules i
                JOIN resumes r ON r.id = i.resume_id
                JOIN memories m ON m.id = i.jd_id
                ORDER BY i.interview_date DESC, i.created_at DESC
            """
            cur.execute(query)
        
        rows = cur.fetchall()
        cur.close()
        
        interviews = []
        for row in rows:
            interviews.append({
                "interview_id": row[0],
                "interview_date": str(row[1]),
                "status": row[2],
                "selected_slot": row[3],
                "confirmed_time": str(row[4]) if row[4] else None,
                "candidate_name": row[5],
                "candidate_email": row[6],
                "jd_title": row[7]
            })
        
        return {
            "total": len(interviews),
            "interviews": interviews
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching interviews: {str(e)}")
    finally:
        conn.close()


def _hr_status_label(interview_status, final_recommendation, acknowledgement) -> str:
    if final_recommendation == "Make Offer":
        return "Hired"
    if final_recommendation == "Not Selected":
        return "Rejected"
    if interview_status == "scheduled":
        return "Scheduled"
    if interview_status == "completed":
        return "Completed"
    if acknowledgement == "not_interested":
        return "Rejected"
    return "Pending"


@app.get("/api/interviews/all")
async def get_all_interviews_api(
    current_user: dict = Depends(get_current_user),
    email_sent_only: bool = True,
    jd_id: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    """JSON feed for HR dashboard — defaults to candidates who received Send Mail outreach."""
    from db import get_connection

    conn = get_connection()
    try:
        cur = conn.cursor()
        filters = []
        params: List[Any] = []

        if email_sent_only:
            filters.append(
                """(
                    co.email_sent IS TRUE
                    OR (
                        co.email_sent IS NULL
                        AND co.email_subject IS DISTINCT FROM 'Application for role'
                        AND COALESCE(co.email_body, '') LIKE '%%/acknowledge/%%'
                    )
                )"""
            )
        if jd_id:
            filters.append("co.jd_id = %s")
            params.append(jd_id)
        if q:
            filters.append(
                """(
                    LOWER(co.candidate_name) LIKE LOWER(%s)
                    OR LOWER(co.candidate_email) LIKE LOWER(%s)
                    OR LOWER(m.title) LIKE LOWER(%s)
                )"""
            )
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if status:
            s = status.lower()
            if s == "scheduled":
                filters.append("i.status = 'scheduled'")
            elif s == "completed":
                filters.append("i.status = 'completed'")
            elif s == "hired":
                filters.append("f.final_recommendation = 'Make Offer'")
            elif s == "rejected":
                filters.append(
                    "(f.final_recommendation = 'Not Selected' OR co.acknowledgement = 'not_interested')"
                )
            elif s == "pending":
                filters.append(
                    "(i.id IS NULL OR i.status IN ('pending', 'waiting_approval', 'pending_reschedule'))"
                )

        where_sql = ("WHERE " + " AND ".join(filters)) if filters else ""
        cur.execute(
            f"""
            SELECT
                co.id,
                co.candidate_name,
                co.candidate_email,
                m.title,
                m.id,
                COALESCE(co.sent_at, co.created_at) AS email_sent_ts,
                i.id,
                i.interview_date,
                i.confirmed_slot_time,
                i.status,
                co.acknowledgement,
                f.final_recommendation
            FROM candidate_outreach co
            JOIN memories m ON m.id = co.jd_id
            LEFT JOIN interview_schedules i ON i.outreach_id = co.id
                AND (i.interview_round = 1 OR i.interview_round IS NULL)
            LEFT JOIN feedback f ON f.interview_id = i.id
            {where_sql}
            ORDER BY co.sent_at DESC NULLS LAST, co.created_at DESC
            """,
            params,
        )
        rows = cur.fetchall()
        cur.close()
        interviews = []
        for row in rows:
            (
                outreach_id,
                cand_name,
                cand_email,
                jd_title,
                jd_id_val,
                email_sent_ts,
                interview_id,
                interview_date,
                confirmed_time,
                interview_status,
                acknowledgement,
                final_recommendation,
            ) = row
            interview_val = confirmed_time or interview_date
            interviews.append(
                {
                    "id": str(interview_id or outreach_id),
                    "outreach_id": str(outreach_id),
                    "candidate_name": cand_name,
                    "candidate_email": cand_email,
                    "jd_title": jd_title,
                    "jd_id": str(jd_id_val) if jd_id_val else None,
                    "email_sent_at": email_sent_ts.isoformat() if hasattr(email_sent_ts, "isoformat") else None,
                    "interview_date": interview_val.isoformat() if hasattr(interview_val, "isoformat") else (str(interview_val) if interview_val else None),
                    "status": _hr_status_label(
                        interview_status, final_recommendation, acknowledgement
                    ),
                    "feedback_submitted": bool(final_recommendation),
                }
            )
        return {"interviews": interviews, "email_sent_only": email_sent_only}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching interviews: {str(e)}")
    finally:
        conn.close()


@app.get("/interviews/status/legacy")
async def get_interviews_status_legacy(
    jd_id: str | None = None,
    status: str | None = None,
    q: str | None = None,
    sort_by: str | None = "date",
    sort_order: str | None = "desc",
    decision: str | None = None,
):
    """
    Legacy HR table with filters (advanced). Prefer /hr for the main dashboard.
    """
    from db import get_connection
    from config import INTERVIEWER_EMAIL, COMPANY_NAME
    from fastapi.responses import HTMLResponse
    import json

    print("DEBUG: Executing get_interviews_status") # VERIFICATION PRINT
    conn = get_connection()
    try:
        cur = conn.cursor()

        # Enhanced query that joins candidate_outreach, memories, users, and interview_schedules
        base_sql = """
            SELECT 
                co.id as outreach_id,
                co.candidate_name,
                co.candidate_email,
                co.resume_id,
                m.id as jd_id,
                m.short_id,
                m.title as role,
                u.username as uploaded_by,
                i.id as interview_id,
                i.interview_date,
                i.confirmed_slot_time,
                i.status as interview_status,
                i.event_link,
                i.meet_link,
                i.selected_slot,
                co.acknowledgement,
                i.feedback_form_link,
                i.feedback_sent_at,
                f.final_recommendation,
                i.interview_round,
                i.hr_round_scheduled,
                i_hr.id as hr_interview_id,
                f_hr.final_recommendation as hr_decision
            FROM candidate_outreach co
            JOIN memories m ON m.id = co.jd_id
            LEFT JOIN users u ON u.id = m.user_id
            LEFT JOIN interview_schedules i ON i.outreach_id = co.id AND (i.interview_round = 1 OR i.interview_round IS NULL)
            LEFT JOIN feedback f ON f.interview_id = i.id
            LEFT JOIN interview_schedules i_hr ON i_hr.outreach_id = co.id AND i_hr.interview_round = 2
            LEFT JOIN feedback f_hr ON f_hr.interview_id = i_hr.id
        """

        filters = []
        params = []

        if jd_id:
            filters.append("m.id = %s")
            params.append(jd_id)

        # Search filter
        if q:
            search_clause = """
                (LOWER(co.candidate_name) LIKE LOWER(%s)
                 OR LOWER(co.candidate_email) LIKE LOWER(%s)
                 OR LOWER(m.title) LIKE LOWER(%s))
            """
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
            filters.append(search_clause)

        # Status filter logic
        if status:
            s = status.lower()
            if s == "scheduled":
                filters.append("i.status = 'scheduled'")
            elif s == "completed":
                filters.append("i.status = 'completed'")
            elif s == "cancelled":
                filters.append("i.status IN ('cancelled', 'declined')")
            elif s == "pending":
                filters.append("(i.status IN ('pending', 'waiting_approval', 'pending_reschedule') OR i.id IS NULL)")

        # Decision filter logic (Round 1 Decision)
        if decision:
            d = decision.lower()
            if d == "selected":
                filters.append("f.final_recommendation = 'Make Offer'")
            elif d == "rejected":
                filters.append("f.final_recommendation = 'Not Selected'")
            elif d == "hold":
                filters.append("f.final_recommendation = 'Hold'")
            elif d == "pending":
                filters.append("f.final_recommendation IS NULL")

        where_sql = ""
        if filters:
            where_sql = "WHERE " + " AND ".join(filters)

        # Sorting logic
        order_clause = "ORDER BY co.created_at DESC"  # Default
        if sort_by == "date":
            if sort_order == "asc":
                order_clause = "ORDER BY COALESCE(i.confirmed_slot_time, i.interview_date, co.created_at) ASC"
            else:
                order_clause = "ORDER BY COALESCE(i.confirmed_slot_time, i.interview_date, co.created_at) DESC"
        elif sort_by == "jd_id":
            if sort_order == "asc":
                order_clause = "ORDER BY m.short_id ASC NULLS LAST, m.id ASC"
            else:
                order_clause = "ORDER BY m.short_id DESC NULLS LAST, m.id DESC"

        query = f"""{base_sql}
            {where_sql}
            {order_clause}
        """

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        
        with open("debug_log.txt", "a") as f:
            f.write(f"Query returned {len(rows)} rows\n")

    except Exception as e:
        conn.close()
        with open("debug_log.txt", "a") as f:
            f.write(f"ERROR: {str(e)}\n")
        raise HTTPException(status_code=500, detail=f"Error fetching interviews: {str(e)}")

    conn.close()

    # Build HTML table
    table_rows = ""
    all_interviews_data = {}
    
    try:
        for row in rows:
            (outreach_id, cand_name, cand_email, resume_id, jd_id_val, short_id, role, uploaded_by, 
             interview_id, interview_date, confirmed_time, interview_status, event_link, 
             meet_link, selected_slot, acknowledgement, feedback_form_link, feedback_sent_at, final_recommendation,
             interview_round, hr_round_scheduled, hr_interview_id, hr_decision) = row

            # Determine Display Status
            display_status = "Pending Interview Mail"
            status_class = "status-pending"
            
            if interview_status == 'scheduled':
                display_status = "Scheduled Interview"
                status_class = "status-scheduled"
            elif interview_status == 'completed':
                display_status = "Completed Interview"
                status_class = "status-completed"
            elif interview_status in ['cancelled', 'declined']:
                display_status = "Cancelled"
                status_class = "status-cancelled"
            elif interview_status == 'waiting_approval':
                display_status = "Waiting Approval"
                status_class = "status-warning"
            elif interview_status == 'pending_reschedule':
                display_status = "Reschedule Proposed"
                status_class = "status-warning"
            elif interview_status == 'pending':
                display_status = "Pending Slot Selection"
                status_class = "status-pending"
            elif acknowledgement == 'not_interested':
                display_status = "Candidate Declined"
                status_class = "status-cancelled"
            
            # Format Date/Time
            date_str = ""
            time_str = ""
            if confirmed_time:
                date_str = confirmed_time.strftime('%Y-%m-%d')
                time_str = confirmed_time.strftime('%I:%M %p')
            elif interview_date:
                date_str = str(interview_date)
                time_str = "Slot not confirmed"
                
            # Use short_id if available, otherwise show first 8 chars of UUID
            jd_display_id = short_id if short_id else (jd_id_val[:8] + "..." if jd_id_val else "N/A")

            # Prepare JSON for modal
            feedback_sent_str = feedback_sent_at.strftime('%Y-%m-%d %I:%M %p') if feedback_sent_at else 'Not sent yet'
            detail_dict = {
                'interview_id': str(interview_id) if interview_id else 'N/A',
                'candidate_name': str(cand_name) if cand_name else 'N/A',
                'candidate_email': str(cand_email) if cand_email else 'N/A',
                'role': str(role) if role else 'N/A',
                'uploaded_by': str(uploaded_by) if uploaded_by else 'System',
                'interviewer_email': str(INTERVIEWER_EMAIL) if INTERVIEWER_EMAIL else 'N/A',
                'interview_date': str(date_str) if date_str else 'N/A',
                'interview_time': str(time_str) if time_str else 'N/A',
                'slot': str(selected_slot) if selected_slot else 'N/A',
                'meet_link': str(meet_link) if meet_link else 'N/A',
                'feedback_link': str(feedback_form_link) if feedback_form_link else 'N/A',
                'feedback_sent': str(feedback_sent_str),
                'interview_round': int(interview_round) if interview_round else 1,
                'hr_round_scheduled': bool(hr_round_scheduled),
                'hr_interview_id': str(hr_interview_id) if hr_interview_id else None,
                'hr_decision': str(hr_decision) if hr_decision else None
            }
            
            # Store in global data object
            all_interviews_data[str(outreach_id)] = detail_dict

            # Map final recommendation to display text
            decision_display = "-"
            decision_class = ""
            if final_recommendation == "Make Offer":
                decision_display = "Selected"
                decision_class = "status-scheduled"  # Green
            elif final_recommendation == "Not Selected":
                decision_display = "Rejected"
                decision_class = "status-cancelled"  # Red
            elif final_recommendation == "Hold":
                decision_display = "On Hold"
                decision_class = "status-warning"  # Yellow
            else:
                decision_display = "Pending"
                decision_class = "status-pending"  # Yellow
            
            # Map HR decision to display text
            hr_decision_display = "-"
            hr_decision_class = ""
            if hr_decision == "Hire":
                hr_decision_display = "Selected"
                hr_decision_class = "status-scheduled"  # Green
            elif hr_decision == "Reject":
                hr_decision_display = "Not Selected"
                hr_decision_class = "status-cancelled"  # Red
            elif hr_decision == "Hold":
                hr_decision_display = "On Hold"
                hr_decision_class = "status-warning"  # Yellow
            elif hr_decision:
                hr_decision_display = hr_decision
                hr_decision_class = "status-warning"  # Yellow
            else:
                hr_decision_display = "Pending"
                hr_decision_class = "status-pending"  # Yellow

            # Sanitize and Escape Data for HTML Table
            # Ensure no newlines in IDs that go into JS
            safe_outreach_id = str(outreach_id).strip()
            safe_jd_id_val = html.escape(str(jd_id_val)) if jd_id_val else ""
            safe_jd_display_id = html.escape(str(jd_display_id))
            safe_role = html.escape(str(role)) if role else ""
            safe_uploaded_by = html.escape(str(uploaded_by)) if uploaded_by else "System"
            safe_event_link = str(event_link).replace('"', '&quot;') if event_link else ""
            
            # Calendar Link
            cal_html = (
                f'<a href="{safe_event_link}" target="_blank" class="link-btn">Open calendar</a>'
                if event_link else "-"
            )

            table_rows += f"""
            <tr>
                <td>{safe_uploaded_by}</td>
                <td><span title="{safe_jd_id_val}">{safe_jd_display_id}</span></td>
                <td>{safe_role}</td>
                <td>{date_str} {time_str}</td>
                <td><span class="status-badge {status_class}">{display_status}</span></td>
                <td>{cal_html}</td>
                <td>
                    <button type="button" class="action-btn view-details-trigger" data-id="{safe_outreach_id}">View Details</button>
                </td>
                <td><span class="status-badge {decision_class}">{decision_display}</span></td>
                <td><span class="status-badge {hr_decision_class}">{hr_decision_display}</span></td>
            </tr>
            """
    
    except Exception as e:
        with open("debug_log.txt", "a") as f:
            f.write(f"ERROR building table rows: {str(e)}\n")
        raise HTTPException(status_code=500, detail=f"Error building table: {str(e)}")

    # Convert interview data to JSON for JavaScript
    # Use ensure_ascii=True to avoid encoding issues and escape for safe HTML embedding
    # Also replace </script> to prevent breaking the HTML script tag
    interviews_data_json = json.dumps(all_interviews_data, ensure_ascii=True, default=str).replace("</", "<\\/")

    empty_row = '<tr><td colspan="9"><div class="empty-state">No records found matching your criteria.</div></td></tr>'
    record_count = len(rows)

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Dashboard | TekLeaders AI</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
            --primary-color: #c026d3;
            --primary-hover: #a21caf;
            --card-bg: #ffffff;
            --text-color: #1f2937;
            --border-color: #f5d0fe;
            --text-secondary: #4b5563;
            --text-muted: #6b7280;
            --gradient: linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%);
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: #ffffff;
            color: var(--text-color);
            min-height: 100vh;
        }}
        .page-wrapper {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px 80px; }}
        .back-link {{
            display: inline-flex; align-items: center; gap: 8px;
            color: var(--text-secondary); font-size: 14px; text-decoration: none;
            margin-bottom: 28px;
        }}
        .back-link:hover {{ color: var(--primary-color); }}
        .back-link svg {{ width: 16px; height: 16px; }}
        .header {{ text-align: center; margin-bottom: 32px; }}
        .header-badge {{
            display: inline-flex; align-items: center; gap: 8px;
            background: #ffffff; border: 1px solid #e5e7eb;
            border-radius: 100px; padding: 6px 16px;
            font-size: 12px; font-weight: 600; letter-spacing: 0.05em;
            color: var(--primary-color); margin-bottom: 16px; text-transform: uppercase;
        }}
        .header-badge::before {{
            content: ''; width: 6px; height: 6px; border-radius: 50%;
            background: var(--primary-color);
        }}
        .header h1 {{
            font-size: clamp(26px, 5vw, 36px); font-weight: 800;
            background: var(--gradient);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text; margin-bottom: 8px;
        }}
        .header p {{ color: var(--text-secondary); font-size: 16px; }}
        .header-actions {{
            display: flex; justify-content: center; gap: 12px; margin-top: 20px; flex-wrap: wrap;
        }}
        .stat-strip {{
            display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; margin-bottom: 24px;
        }}
        .stat-pill {{
            background: var(--card-bg); border: 1px solid var(--border-color);
            border-radius: 12px; padding: 12px 20px; font-size: 14px; color: var(--text-secondary);
        }}
        .stat-pill strong {{ color: var(--text-color); font-weight: 700; }}
        .card {{
            background: var(--card-bg); border: 1px solid var(--border-color);
            border-radius: 20px; padding: 28px;
            box-shadow: 0 10px 35px rgba(192, 38, 211, 0.06);
        }}
        .card-header {{ margin-bottom: 24px; }}
        .card-title {{ font-size: 18px; font-weight: 700; }}
        .card-subtitle {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
        label {{
            display: block; font-size: 11px; font-weight: 600; color: var(--text-secondary);
            margin-bottom: 6px; letter-spacing: 0.04em; text-transform: uppercase;
        }}
        select, input[type="text"] {{
            width: 100%; background: #ffffff; border: 1px solid var(--border-color);
            border-radius: 10px; color: var(--text-color); font-size: 14px;
            font-family: inherit; padding: 10px 36px 10px 12px; outline: none;
        }}
        select {{
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
            background-repeat: no-repeat; background-position: right 10px center;
        }}
        select:focus, input:focus {{
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(192, 38, 211, 0.12);
        }}
        .filter-form {{
            display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 14px; align-items: end; margin-bottom: 24px;
        }}
        .filter-form .search-field {{ grid-column: 1 / -1; }}
        @media (min-width: 900px) {{
            .filter-form .search-field {{ grid-column: span 2; }}
        }}
        .filter-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
        .btn {{
            display: inline-flex; align-items: center; justify-content: center;
            border: none; border-radius: 10px; font-family: inherit;
            font-size: 14px; font-weight: 600; cursor: pointer; padding: 10px 18px;
            text-decoration: none; transition: all 0.2s;
        }}
        .btn-primary {{ background: var(--gradient); color: #fff; }}
        .btn-primary:hover {{ transform: translateY(-1px); box-shadow: 0 6px 20px rgba(192,38,211,0.25); }}
        .btn-ghost {{
            background: #fff; color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }}
        .btn-ghost:hover {{ color: var(--text-color); border-color: var(--primary-color); }}
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        thead th {{
            padding: 12px 14px; text-align: left; font-size: 11px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);
            border-bottom: 1px solid var(--border-color); background: #fafafa;
        }}
        tbody td {{ padding: 14px; font-size: 14px; border-bottom: 1px solid #f5d0fe; vertical-align: middle; }}
        tbody tr:hover {{ background: #f9fafb; }}
        .status-badge {{
            display: inline-flex; padding: 4px 10px; border-radius: 100px;
            font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
        }}
        .status-pending {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }}
        .status-warning {{ background: #fef3c7; color: #b45309; border: 1px solid #fcd34d; }}
        .status-scheduled {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
        .status-completed {{ background: #ecfeff; color: #0891b2; border: 1px solid #a5f3fc; }}
        .status-cancelled {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
        .link-btn {{ color: var(--primary-color); font-weight: 600; text-decoration: none; font-size: 13px; }}
        .link-btn:hover {{ text-decoration: underline; }}
        .action-btn {{
            background: var(--gradient); color: #fff; border: none;
            padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
        }}
        .action-btn:hover {{ opacity: 0.92; }}
        .empty-state {{ text-align: center; padding: 40px 16px; color: var(--text-muted); font-size: 14px; }}
        .modal {{
            display: none; position: fixed; z-index: 10000; inset: 0;
            background: rgba(15, 23, 42, 0.45); padding: 20px; overflow: auto;
        }}
        .modal-content {{
            background: #fff; margin: 4vh auto; padding: 28px; max-width: 560px;
            border: 1px solid var(--border-color); border-radius: 16px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.15);
        }}
        .modal-content h2 {{ font-size: 20px; margin-bottom: 16px; }}
        .close {{
            float: right; font-size: 24px; font-weight: 400; cursor: pointer;
            color: var(--text-muted); line-height: 1;
        }}
        .close:hover {{ color: var(--text-color); }}
        .detail-row {{
            display: flex; justify-content: space-between; gap: 12px;
            margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #f3f4f6;
            font-size: 14px;
        }}
        .detail-label {{ font-weight: 600; color: var(--text-secondary); }}
        #feedbackSection h3 {{ margin: 16px 0 10px; font-size: 16px; }}
    </style>
</head>
<body>
  <div class="page-wrapper">
    <a href="/" class="back-link">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
      Back to Home
    </a>

    <div class="header">
      <div class="header-badge">Step 3 of 3</div>
      <h1>HR Dashboard</h1>
      <p>Interview management, feedback tracking, and hiring decisions.</p>
      <div class="header-actions">
        <a href="/interviews/status" class="btn btn-ghost">Refresh</a>
      </div>
    </div>

    <div class="stat-strip">
      <div class="stat-pill"><strong>{record_count}</strong> records shown</div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">Interview Records</div>
        <div class="card-subtitle">Filter, search, and review candidate interview status.</div>
      </div>

      <form method="get" action="/interviews/status" class="filter-form">
        <div>
          <label for="status">Filter by Status</label>
          <select name="status" id="status">
            <option value="">All Statuses</option>
            <option value="pending" {"selected" if (status or "").lower() == "pending" else ""}>Pending</option>
            <option value="scheduled" {"selected" if (status or "").lower() == "scheduled" else ""}>Scheduled</option>
            <option value="completed" {"selected" if (status or "").lower() == "completed" else ""}>Completed</option>
            <option value="cancelled" {"selected" if (status or "").lower() == "cancelled" else ""}>Cancelled</option>
          </select>
        </div>
        <div>
          <label for="decision">Technical Round Decision</label>
          <select name="decision" id="decision">
            <option value="">All Decisions</option>
            <option value="selected" {"selected" if (decision or "").lower() == "selected" else ""}>Selected</option>
            <option value="rejected" {"selected" if (decision or "").lower() == "rejected" else ""}>Rejected</option>
            <option value="hold" {"selected" if (decision or "").lower() == "hold" else ""}>On Hold</option>
            <option value="pending" {"selected" if (decision or "").lower() == "pending" else ""}>Pending</option>
          </select>
        </div>
        <div>
          <label for="sort_by">Sort By</label>
          <select name="sort_by" id="sort_by">
            <option value="date" {"selected" if (sort_by or "date") == "date" else ""}>Date</option>
            <option value="jd_id" {"selected" if (sort_by or "date") == "jd_id" else ""}>Job ID</option>
          </select>
        </div>
        <div>
          <label for="sort_order">Order</label>
          <select name="sort_order" id="sort_order">
            <option value="desc" {"selected" if (sort_order or "desc") == "desc" else ""}>Descending</option>
            <option value="asc" {"selected" if (sort_order or "desc") == "asc" else ""}>Ascending</option>
          </select>
        </div>
        <div class="search-field">
          <label for="q">Search</label>
          <input type="text" id="q" name="q" placeholder="Candidate name, email, or role" value="{html.escape(q or '')}"/>
        </div>
        <div class="filter-actions">
          <button type="submit" class="btn btn-primary">Apply Filters</button>
          <a href="/interviews/status" class="btn btn-ghost">Clear</a>
        </div>
      </form>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Uploaded By</th>
              <th>JD ID</th>
              <th>Role</th>
              <th>Date &amp; Time</th>
              <th>Status</th>
              <th>Calendar</th>
              <th>Actions</th>
              <th>Technical Decision</th>
              <th>HR Decision</th>
            </tr>
          </thead>
          <tbody>
            {table_rows or empty_row}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div id="detailsModal" class="modal">
    <div class="modal-content">
      <span class="close" onclick="closeModal()">&times;</span>
      <h2>Interview Details</h2>
      <div id="modalBody"></div>
    </div>
  </div>

  <script>
    // Global Error Handler to catch anything
    window.onerror = function(msg, url, line) {{
        alert("System Error: " + msg + "\\nLine: " + line);
        return false;
    }};

    console.log("HR Dashboard Script Loaded");
    
    // Interview data store
    const allInterviewsData = {interviews_data_json};
    console.log("Loaded interview data:", allInterviewsData);
    
    let currentInterviewData = null;

    // Event delegation for view details buttons
    document.addEventListener('click', function(e) {{
        if (e.target && e.target.classList.contains('view-details-trigger')) {{
            const outreachId = e.target.getAttribute('data-id');
            openModal(outreachId);
        }}
    }});

    function openModal(outreachId) {{
        try {{
            console.log("Opening modal for outreach ID:", outreachId);
            // Ensure ID is a string
            const safeId = String(outreachId).trim();
            const data = allInterviewsData[safeId];
            
            if (!data) {{
                alert("No data found for this interview ID: " + safeId);
                console.error("No data for outreach ID:", safeId);
                console.log("Available IDs:", Object.keys(allInterviewsData));
                return;
            }}
            
            currentInterviewData = data;
            
            const modal = document.getElementById("detailsModal");
            const body = document.getElementById("modalBody");
            
            body.innerHTML = `
                <div class="detail-row"><span class="detail-label">Candidate Name:</span> <span>${{data.candidate_name}}</span></div>
                <div class="detail-row"><span class="detail-label">Candidate Email:</span> <span>${{data.candidate_email}}</span></div>
                <div class="detail-row"><span class="detail-label">Role:</span> <span>${{data.role}}</span></div>
                <div class="detail-row"><span class="detail-label">Uploaded By:</span> <span>${{data.uploaded_by}}</span></div>
                <hr>
                <div class="detail-row"><span class="detail-label">Interviewer:</span> <span>${{data.interviewer_email}}</span></div>
                <div class="detail-row"><span class="detail-label">Date:</span> <span>${{data.interview_date}}</span></div>
                <div class="detail-row"><span class="detail-label">Time:</span> <span>${{data.interview_time}}</span></div>
                <div class="detail-row"><span class="detail-label">Slot ID:</span> <span>${{data.slot}}</span></div>
                <div class="detail-row"><span class="detail-label">Meeting Link:</span> <span><a href="${{data.meet_link}}" target="_blank">${{data.meet_link}}</a></span></div>
                <hr>
                <div class="detail-row"><span class="detail-label">Feedback Sent:</span> <span style="color: ${{data.feedback_sent === 'Not sent yet' ? '#dc3545' : '#28a745'}};">${{data.feedback_sent}}</span></div>
                <hr>
                <div style="text-align: center; margin-top: 15px;">
                    <button class="btn btn-primary" onclick="viewTechnicalFeedback('${{data.interview_id}}')" style="margin-right: 10px;">View Technical Feedback</button>
                    ${{data.hr_interview_id ? `<button class="btn btn-primary" onclick="viewHrFeedback('${{data.hr_interview_id}}')" style="margin-right: 10px;">View HR Feedback</button>` : ''}}
                    <button class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
                <div id="feedbackSection" style="margin-top: 20px; display: none;">
                    <h3>Interview Feedback</h3>
                    <div id="feedbackContent"></div>
                </div>
            `;
            
            modal.style.display = "block";
        }} catch (err) {{
            alert("Javascript Error: " + err.message);
            console.error(err);
        }}
    }}

    function closeModal() {{
        document.getElementById("detailsModal").style.display = "none";
        // Reset feedback section
        const feedbackSection = document.getElementById("feedbackSection");
        if (feedbackSection) {{
            feedbackSection.style.display = "none";
            feedbackSection.querySelector("#feedbackContent").innerHTML = "";
        }}
    }}

    async function viewTechnicalFeedback(interviewId) {{
        const feedbackSection = document.getElementById("feedbackSection");
        const feedbackContent = document.getElementById("feedbackContent");
        
        feedbackContent.innerHTML = '<p style="text-align: center; color: #666;">Loading feedback...</p>';
        feedbackSection.style.display = "block";
        
        try {{
            const response = await fetch(`/api/feedback/view/${{interviewId}}`);
            const data = await response.json();
            
            if (data.feedback) {{
                const f = data.feedback;
                // Render all rating fields
                let content = '<div style="background: #f9fafb; padding: 15px; border-radius: 8px;">';
                
                // Show all ratings if available (Technical Round)
                if (f.technical_skills !== undefined) {{
                    content += '<h4 style="margin-top: 0; color: #667eea;">Technical Assessment</h4>';
                    content += `<div class="detail-row"><span class="detail-label">Technical Skills:</span> <span>${{f.technical_skills}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Education/Training:</span> <span>${{f.education_training}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Work Experience:</span> <span>${{f.work_experience}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Organizational Skills:</span> <span>${{f.organizational_skills}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Communication:</span> <span>${{f.communication}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Attitude:</span> <span>${{f.attitude}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Overall Rating:</span> <span style="font-weight: bold; color: #667eea;">${{f.overall_rating}}/5</span></div>`;
                    content += '<hr>';
                }}
                
                // Show HR ratings if available (HR Round)
                if (f.communication_skills !== undefined) {{
                    content += '<h4 style="margin-top: 10px; color: #667eea;">HR Assessment</h4>';
                    content += `<div class="detail-row"><span class="detail-label">Communication Skills:</span> <span>${{f.communication_skills}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Problem Solving:</span> <span>${{f.problem_solving}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Teamwork:</span> <span>${{f.teamwork}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Leadership:</span> <span>${{f.leadership}}/5</span></div>`;
                    content += `<div class="detail-row"><span class="detail-label">Cultural Fit:</span> <span>${{f.cultural_fit}}/5</span></div>`;
                    if (f.current_ctc) {{
                        content += '<hr>';
                        content += '<h4 style="margin-top: 10px; color: #667eea;">Compensation Details</h4>';
                        content += `<div class="detail-row"><span class="detail-label">Current CTC:</span> <span>${{f.current_ctc}}</span></div>`;
                        content += `<div class="detail-row"><span class="detail-label">Expected CTC:</span> <span>${{f.expected_ctc}}</span></div>`;
                        content += `<div class="detail-row"><span class="detail-label">Notice Period:</span> <span>${{f.notice_period}}</span></div>`;
                    }}
                    content += '<hr>';
                }}
                
                // Show recommendation
                const rec = f.final_recommendation || f.recommendation; 
                content += `<div class="detail-row"><span class="detail-label">Recommendation:</span> <span style="font-weight: bold; font-size: 16px; color: ${{rec === 'Make Offer' || rec === 'Strong Hire' || rec === 'Hire' ? '#28a745' : rec === 'Not Selected' || rec === 'Do Not Hire' ? '#dc3545' : '#ffc107'}};">${{rec}}</span></div>`;
                content += `<div style="margin-top: 10px;"><strong>Comments:</strong><p style="padding: 10px; background: white; border-radius: 4px;">${{f.comments || f.additional_comments || 'No comments'}}</p></div>`;
                
                content += '</div>';
                feedbackContent.innerHTML = content;
                
                // ACTION BUTTONS Logic
                const interviewRound = currentInterviewData.interview_round;
                const hrScheduled = currentInterviewData.hr_round_scheduled;
                
                if (interviewRound == 1 && rec === 'Make Offer') {{
                    if (hrScheduled) {{
                        feedbackContent.innerHTML += `<div style="margin-top: 20px; text-align: center;"><button class="btn" disabled style="background:#28a745; opacity: 0.7; color:white;">✅ HR Round Scheduled</button></div>`;
                    }} else {{
                        feedbackContent.innerHTML += `
                            <div style="margin-top: 25px; padding-top: 20px; border-top: 2px solid #e5e7eb; text-align: center;">
                                <p><strong>Candidate passed Technical Round.</strong></p>
                                <button id="scheduleHrBtn-${{interviewId}}" class="btn" style="background-color: #667eea; color: white;" onclick="scheduleHrRound('${{interviewId}}')">
                                    Schedule HR Round
                                </button>
                                <p id="hrStatus-${{interviewId}}"></p>
                            </div>
                        `;
                    }}
                }} else if (interviewRound == 2 && (rec === 'Strong Hire' || rec === 'Hire')) {{
                     feedbackContent.innerHTML += `
                        <div style="margin-top: 25px; text-align: center;">
                            <button id="proceedBtn-${{interviewId}}" class="btn" style="background-color: #28a745; color: white;" onclick="sendHrDecision('${{interviewId}}')">
                                ✉️ Send Offer Email
                            </button>
                            <p id="emailStatus-${{interviewId}}"></p>
                        </div>
                    `;
                }} else if (rec === 'Not Selected' || rec === 'Do Not Hire') {{
                    feedbackContent.innerHTML += `
                        <div style="margin-top: 25px; text-align: center;">
                            <button id="rejectBtn-${{interviewId}}" class="btn" style="background-color: #dc3545; color: white;" onclick="sendRejection('${{interviewId}}')">
                                ✉️ Send Rejection Email
                            </button>
                             <p id="rejectStatus-${{interviewId}}"></p>
                        </div>
                    `;
                }}
            }} else {{
                feedbackContent.innerHTML = '<p style="text-align: center; color: #999;">No feedback submitted yet for this interview.</p>';
            }}
        }} catch (error) {{
            console.error('Error fetching feedback:', error);
            feedbackContent.innerHTML = '<p style="text-align: center; color: #dc3545;">❌ Error loading feedback.</p>';
        }}
    }}

    async function viewHrFeedback(hrInterviewId) {{
        const feedbackSection = document.getElementById("feedbackSection");
        const feedbackContent = document.getElementById("feedbackContent");
        
        feedbackContent.innerHTML = '<p style="text-align: center; color: #666;">Loading HR feedback...</p>';
        feedbackSection.style.display = "block";
        
        try {{
            const response = await fetch(`/api/feedback/view/${{hrInterviewId}}`);
            const data = await response.json();
            
            if (data.feedback) {{
                const f = data.feedback;
                
                // Parse HR-specific data from comments field
                const comments = f.additional_comments || f.comments || '';
                const parseField = (fieldName) => {{
                    const regex = new RegExp(`${{fieldName}}:\\s*(.+?)(?=\\n|$)`, 'i');
                    const match = comments.match(regex);
                    return match ? match[1].trim() : 'N/A';
                }};
                
                // Render all HR rating fields
                let content = '<div style="background: #f9fafb; padding: 15px; border-radius: 8px;">';
                
                // Show HR-specific information
                content += '<h4 style="margin-top: 0; color: #667eea;">HR Assessment Details</h4>';
                content += `<div class="detail-row"><span class="detail-label">Reason for Leaving:</span> <span>${{parseField('Reason for leaving')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Previous Package:</span> <span>${{parseField('Previous Package')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Offered Package:</span> <span>${{parseField('Offered Package')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Expected Package:</span> <span>${{parseField('Expected Package')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Notice Period:</span> <span>${{parseField('Notice Period')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Date of Joining:</span> <span>${{parseField('Date of Joining')}}</span></div>`;
                
                content += '<hr>';
                content += '<h4 style="margin-top: 10px; color: #667eea;">Skills Rating</h4>';
                content += `<div class="detail-row"><span class="detail-label">Technical Skills:</span> <span>${{f.technical_skills}}/5</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Communication Skills:</span> <span>${{f.communication}}/5</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Teamwork:</span> <span>${{f.education_training}}/5</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Attitude:</span> <span>${{f.organizational_skills}}/5</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Time Management:</span> <span>${{f.work_experience}}/5</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Overall Impression:</span> <span>${{f.overall_rating}}/5</span></div>`;
                
                content += '<hr>';
                content += `<div class="detail-row"><span class="detail-label">Strengths:</span> <span>${{parseField('Strengths')}}</span></div>`;
                content += `<div class="detail-row"><span class="detail-label">Areas to Improve:</span> <span>${{parseField('Areas to Improve')}}</span></div>`;
                
                content += '<hr>';
                
                // Show recommendation
                const rec = f.final_recommendation || f.recommendation; 
                content += `<div class="detail-row"><span class="detail-label">Recommendation:</span> <span style="font-weight: bold; font-size: 16px; color: ${{rec === 'Hire' ? '#28a745' : rec === 'Reject' ? '#dc3545' : '#ffc107'}};">${{rec}}</span></div>`;
                
                const additionalComments = parseField('Additional Comments');
                if (additionalComments !== 'N/A') {{
                    content += `<div style="margin-top: 10px;"><strong>Additional Comments:</strong><p style="padding: 10px; background: white; border-radius: 4px;">${{additionalComments}}</p></div>`;
                }}
                
                content += '</div>';
                feedbackContent.innerHTML = content;
                
                // Add action buttons based on recommendation
                if (rec === 'Hire') {{
                    feedbackContent.innerHTML += `
                        <div style="margin-top: 25px; text-align: center;">
                            <button id="offerBtn-${{hrInterviewId}}" class="btn" style="background-color: #28a745; color: white;" onclick="sendHrDecision('${{hrInterviewId}}', 'offer')">
                                ✉️ Send Offer Email
                            </button>
                             <p id="offerStatus-${{hrInterviewId}}"></p>
                        </div>
                    `;
                }} else if (rec === 'Reject') {{
                    feedbackContent.innerHTML += `
                        <div style="margin-top: 25px; text-align: center;">
                            <button id="rejectBtn-${{hrInterviewId}}" class="btn" style="background-color: #dc3545; color: white;" onclick="sendRejection('${{hrInterviewId}}')">
                                ✉️ Send Rejection Email
                            </button>
                             <p id="rejectStatus-${{hrInterviewId}}"></p>
                        </div>
                    `;
                }}
            }} else {{
                feedbackContent.innerHTML = '<p style="text-align: center; color: #999;">No HR feedback submitted yet for this interview.</p>';
            }}
        }} catch (error) {{
            console.error('Error fetching HR feedback:', error);
            feedbackContent.innerHTML = '<p style="text-align: center; color: #dc3545;">❌ Error loading HR feedback.</p>';
        }}
    }}

    async function scheduleHrRound(interviewId) {{
        const btn = document.getElementById(`scheduleHrBtn-${{interviewId}}`);
        const status = document.getElementById(`hrStatus-${{interviewId}}`);
        
        if (!confirm('Schedule HR Round for this candidate? This will send an invitation email.')) return;
        
        btn.disabled = true;
        btn.textContent = 'Scheduling...';
        
        try {{
            const response = await fetch('/api/recruit/schedule-hr-round', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ interview_id: interviewId }})
            }});
            const data = await response.json();
            
            if (data.success) {{
                status.textContent = '✅ ' + data.message;
                status.style.color = 'green';
                btn.textContent = 'Scheduled';
            }} else {{
                status.textContent = '❌ ' + (data.error || 'Failed');
                status.style.color = 'red';
                btn.disabled = false;
                btn.textContent = 'Retry Schedule';
            }}
        }} catch (e) {{
            status.textContent = '❌ Error: ' + e.message;
            btn.disabled = false;
        }}
    }}
    
    async function sendHrDecision(interviewId, type) {{
         // Determine button and status IDs based on context (HR view vs Technical view)
         let btnId = `proceedBtn-${{interviewId}}`;
         let statusId = `emailStatus-${{interviewId}}`;
         
         if (type === 'offer' || document.getElementById(`offerBtn-${{interviewId}}`)) {{
             btnId = `offerBtn-${{interviewId}}`;
             statusId = `offerStatus-${{interviewId}}`;
         }}
         
         const btn = document.getElementById(btnId);
         const status = document.getElementById(statusId);
         
         if (!btn) {{
             console.error("Button not found:", btnId);
             return;
         }}

         if (!confirm('Send Final Offer Email?')) return;
         
         btn.disabled = true;
         btn.textContent = 'Sending...';
         
         try {{
             const response = await fetch('/api/recruit/send-hr-decision', {{
                 method: 'POST',
                 headers: {{ 'Content-Type': 'application/json' }},
                 body: JSON.stringify({{ interview_id: interviewId }})
             }});
             const data = await response.json();
             if (data.success) {{
                 if (status) {{
                    status.textContent = '✅ ' + data.message;
                    status.style.color = 'green';
                 }}
                 btn.textContent = 'Sent';
             }} else {{
                 if (status) {{
                    status.textContent = '❌ ' + (data.error || 'Failed');
                    status.style.color = 'red';
                 }}
                 btn.disabled = false;
                 btn.textContent = 'Retry Send';
             }}
         }} catch (e) {{
             console.error(e);
             if (status) status.textContent = '❌ ' + e.message;
             btn.disabled = false;
         }}
    }}
    
    async function sendRejection(interviewId) {{
         const btn = document.getElementById(`rejectBtn-${{interviewId}}`);
         const status = document.getElementById(`rejectStatus-${{interviewId}}`);
         
         if (!confirm('Send Rejection Email?')) return;
         btn.disabled = true;
         
         try {{
            const response = await fetch('/api/send-decision-email', {{
                method: 'POST',
                 headers: {{ 'Content-Type': 'application/json' }},
                 body: JSON.stringify({{ interview_id: interviewId }})
            }});
            const data = await response.json();
             if (data.success) {{
                 if (status) {{
                     status.textContent = '✅ ' + data.message;
                     status.style.color = 'green';
                 }}
             }} else {{
                 if (status) {{
                     status.textContent = '❌ ' + (data.error || 'Failed');
                     status.style.color = 'red';
                 }}
             }}
         }} catch (e) {{
             console.error(e);
             if (status) status.textContent = '❌ ' + e.message;
             btn.disabled = false;
         }}
    }}
  </script>
</body>
</html>
    """


    return HTMLResponse(content=html_content)


# Start feedback scheduler when app initializes
# from feedback_scheduler import start_feedback_scheduler

# Temporarily disabled - uncomment after testing
# @app.on_event("startup")
# async def startup_event():
#     """Start background jobs when app starts."""
#     print("[STARTUP] Starting feedback scheduler...")
#     start_feedback_scheduler()
#     print("[STARTUP] Feedback scheduler started successfully")



# --- HR Round & Round 2 Logic ---

@app.post("/api/recruit/technical-decision")
async def api_technical_decision(request: Dict[str, Any]):
    """Update Technical Round (Round 1) decision."""
    from db import get_connection
    
    interview_id = request.get("interview_id")
    decision = request.get("decision") # Selected, Rejected, On Hold, etc.
    
    if not interview_id or not decision:
        return JSONResponse({"success": False, "error": "interview_id and decision are required"}, status_code=400)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE interview_schedules 
            SET technical_decision = %s, technical_decision_sent_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, [decision, interview_id])
        conn.commit()
        return {"success": True, "message": f"Technical decision updated to {decision}"}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/recruit/schedule-hr-round")
async def api_schedule_hr_round(request: Dict[str, Any]):
    """Schedule HR Round (Round 2) for a candidate."""
    from interview_scheduler import schedule_hr_round_interview
    
    interview_id = request.get("interview_id") # Original Round 1 interview ID
    if not interview_id:
        return JSONResponse({"success": False, "error": "interview_id is required"}, status_code=400)
        
    return schedule_hr_round_interview(original_interview_id=interview_id)


@app.post("/api/hr-feedback/submit")
async def submit_hr_feedback(request: Dict[str, Any]):
    """Submit HR Round feedback."""
    from db import get_connection
    
    interview_id = request.get("interview_id")
    if not interview_id:
        return JSONResponse({"success": False, "error": "interview_id is required"}, status_code=400)
        
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Verify interview exists
        cur.execute("SELECT id FROM interview_schedules WHERE id = %s", [interview_id])
        if not cur.fetchone():
            return JSONResponse({"success": False, "error": "Interview not found"}, status_code=404)

        # Insert into hr_feedback
        fields = [
            'interview_id', 'candidate_name', 'job_title', 'interview_date', 'interviewer_name',
            'current_ctc', 'expected_ctc', 'company_ctc', 'reason_leave', 'notice_period', 'joining_date',
            'technical_skills', 'communication_skills', 'problem_solving', 'teamwork', 'leadership', 
            'domain_knowledge', 'adaptability', 'cultural_fit',
            'confidence', 'attitude', 'time_management', 'motivation', 'integrity',
            'clarity', 'examples_quality', 'job_understanding',
            'strengths', 'improvements', 'concerns',
            'recommendation', 'additional_comments'
        ]
        
        # Build query dynamically
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        
        values = [request.get(f) for f in fields]
        
        # Handle empty strings for integer fields (convert to None/0)
        # Actually standard Postgres driver handles None as NULL, but empty string might be issue for integers
        # The frontend JS sends parsed ints, so should be fine. string fields can be empty strings.
        
        cur.execute(f"""
            INSERT INTO hr_feedback ({columns}, timestamp)
            VALUES ({placeholders}, NOW())
        """, values)
        
        conn.commit()
        return {"success": True, "message": "HR Feedback submitted successfully"}
        
    except Exception as e:
        conn.rollback()
        print(f"Error submitting HR feedback: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.post("/api/recruit/send-hr-decision")
async def send_hr_decision(request: Dict[str, Any]):
    """
    Send final decision email after HR Round.
    """
    from db import get_connection
    from candidate_decision_emails import generate_offer_email, generate_rejection_email
    from email_sender import send_email
    from config import COMPANY_NAME
    
    interview_id = request.get("interview_id")
    if not interview_id:
        return JSONResponse({"success": False, "error": "interview_id is required"}, status_code=400)
        
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Get HR feedback recommendation and candidate info
        # We join with interview_schedules to get resume/memory info
        cur.execute("""
            SELECT 
                f.recommendation,
                r.candidate_name,
                r.email,
                m.title as jd_title
            FROM hr_feedback f
            JOIN interview_schedules i ON i.id = f.interview_id
            JOIN resumes r ON r.id = i.resume_id
            JOIN memories m ON m.id = i.jd_id
            WHERE f.interview_id = %s
            ORDER BY f.created_at DESC
            LIMIT 1
        """, [interview_id])
        
        row = cur.fetchone()
        
        if not row:
            return JSONResponse({"success": False, "error": "HR Feedback not found"}, status_code=404)
            
        recommendation, candidate_name, candidate_email, jd_title = row
        
        # Map recommendation to decision type
        # Options: Strong Hire, Hire, Neutral..., Do Not Hire
        is_offer = recommendation in ["Strong Hire", "Hire"]
        is_rejection = recommendation == "Do Not Hire"
        
        if not (is_offer or is_rejection):
            return JSONResponse({"success": False, "error": f"Recommendation '{recommendation}' does not trigger automatic email"}, status_code=400)
            
        # Generate Email
        if is_offer:
            # We use the standard offer email (which is final offer)
            email_content = generate_offer_email(candidate_name, jd_title, COMPANY_NAME)
            decision_status = "Offer Sent"
        else:
            email_content = generate_rejection_email(candidate_name, jd_title, COMPANY_NAME)
            decision_status = "Rejected"
            
        # Send Email
        send_result = send_email(
            to_email=candidate_email,
            subject=email_content["subject"],
            html_body=email_content["body"]
        )
        
        if send_result["success"]:
            # Update HR decision status
            cur.execute("""
                UPDATE interview_schedules 
                SET hr_decision = %s, hr_decision_sent_at = NOW()
                WHERE id = %s
            """, [decision_status, interview_id])
            conn.commit()
            return {"success": True, "message": f"Sent {decision_status} email to {candidate_name}"}
        else:
            return JSONResponse({"success": False, "error": "Failed to send email"}, status_code=500)
            
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        conn.close()


# Register auth UI routes first in the router (highest priority after middleware)
async def _login_ui_page(request):
    return _read_auth_html("login.html")


async def _signup_ui_page(request):
    return _read_auth_html("signup.html")


from starlette.routing import Route

async def _login_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    payload = AgencyLoginRequest(
        email=body.get("email") or body.get("username") or "",
        password=body.get("password") or "",
    )
    email = str(payload.email).strip().lower()
    user = authenticate_user(email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"access_token": user["username"], "token_type": "bearer"}


for _path, _endpoint, _methods in (
    ("/login", _login_ui_page, ["GET"]),
    ("/auth/login", _login_ui_page, ["GET"]),
    ("/sign-in", _login_ui_page, ["GET"]),
    ("/signup", _signup_ui_page, ["GET"]),
    ("/auth/signup", _signup_ui_page, ["GET"]),
    ("/sign-up", _signup_ui_page, ["GET"]),
    ("/api/login", _login_api, ["POST"]),
    ("/login", _login_api, ["POST"]),
    ("/api/v1/agency/auth/login", _login_api, ["POST"]),
):
    app.router.routes.insert(0, Route(_path, endpoint=_endpoint, methods=_methods))

print(f"[HIRING] Auth UI loaded from {_STATIC_DIR}")
print("[HIRING] Login:  http://127.0.0.1:8000/login")
print("[HIRING] Signup: http://127.0.0.1:8000/signup")
print("[HIRING] Fallback: http://127.0.0.1:8000/static/login.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    print(f"[HIRING] Starting main.py from {_BASE_DIR} on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, reload=True)
