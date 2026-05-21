"""
Start the hiring FastAPI app. Default port 8001 (port 8000 is often Django or an old process).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

HIRING_PORT = int(os.environ.get("HIRING_PORT", "8001"))

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("HIRING FastAPI")
    print("Folder:", ROOT)
    print("Port:", HIRING_PORT, "(not 8000 — that is often the wrong app)")
    print("=" * 60)

    try:
        from main import SERVER_BUILD, RESUME_UPLOAD_VERSION, app, api_health
        import resume_text_extractor  # noqa: F401 — PDF/Word/ZIP uploads
        from resume_parser import SERVICE_VERSION as RESUME_PARSER_VERSION, use_openai_for_resumes
    except Exception as exc:
        print("FAILED to import main.py:", exc)
        sys.exit(1)

    print("SERVER_BUILD:", SERVER_BUILD)
    print("RESUME_UPLOAD:", RESUME_UPLOAD_VERSION)
    print("RESUME_PARSER:", RESUME_PARSER_VERSION, "| openai:", use_openai_for_resumes())

    paths = {getattr(r, "path", "") for r in app.routes}
    if "/api/health" not in paths:
        app.add_api_route("/api/health", api_health, methods=["GET"])
    if "/health" not in paths:
        app.add_api_route("/health", api_health, methods=["GET"])

    @app.get("/whoami")
    async def whoami():
        return {
            "app": "hiring-main",
            "server_build": SERVER_BUILD,
            "port": HIRING_PORT,
            "health": f"http://127.0.0.1:{HIRING_PORT}/api/health",
        }

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    print("OPENAI_API_KEY:", "SET" if key else "MISSING")
    print()
    print("Open these URLs (use", HIRING_PORT, "not 8000):")
    print(f"  http://127.0.0.1:{HIRING_PORT}/api/health")
    print(f"  http://127.0.0.1:{HIRING_PORT}/whoami")
    print(f"  http://127.0.0.1:{HIRING_PORT}/login")
    print(f"  http://127.0.0.1:{HIRING_PORT}/admin")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=HIRING_PORT, reload=False)
