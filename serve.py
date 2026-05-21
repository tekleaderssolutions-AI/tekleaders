"""
Double-click this file (or run: python serve.py) to start the hiring app on port 8000.
"""
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(Path(ROOT) / ".env", override=True)

if __name__ == "__main__":
    import uvicorn

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    print("=" * 60)
    print("HIRING APP — starting from:", ROOT)
    print("JD parsing: OpenAI only")
    print("OPENAI_API_KEY:", "SET" if key else "MISSING — add to .env")
    print("OPENAI_CHAT_MODEL:", os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"))
    print("Login:  http://127.0.0.1:8000/login")
    print("Health: http://127.0.0.1:8000/api/health")
    print("=" * 60)
    from main import app, api_health

    paths = {getattr(r, "path", "") for r in app.routes}
    if "/health" not in paths:
        app.add_api_route("/health", api_health, methods=["GET"])

    port = int(os.environ.get("HIRING_PORT", "8001"))
    print(f"Port: {port} (use this URL, not 8000)")
    print(f"Health: http://127.0.0.1:{port}/api/health")
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
