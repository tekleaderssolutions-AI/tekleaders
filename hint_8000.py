"""
Listen on port 8000 only to explain: use hiring FastAPI on port 8001.
Started automatically by RUN_HIRING_SERVER.bat
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Port 8000 hint")

MESSAGE = {
    "status": "wrong_port",
    "you_opened": "http://127.0.0.1:8000",
    "use_instead": "http://127.0.0.1:8001/api/health",
    "admin_portal": "http://127.0.0.1:8001/admin",
    "login": "http://127.0.0.1:8001/login",
    "instruction": "Run RUN_HIRING_SERVER.bat in the hiring folder. Do not use port 8000.",
}


@app.get("/api/health")
@app.get("/health")
@app.get("/whoami")
async def health():
    return MESSAGE


@app.post("/token")
@app.post("/api/login")
@app.post("/login")
@app.post("/api/v1/agency/auth/login")
@app.post("/api/register")
@app.post("/{full_path:path}")
async def post_hint():
    return JSONResponse(
        {**MESSAGE, "detail": "Wrong port 8000 for login. API is on http://127.0.0.1:8001"},
        status_code=200,
    )


@app.get("/")
@app.get("/{full_path:path}")
async def catch_all(full_path: str = ""):
    return JSONResponse(MESSAGE, status_code=200)


if __name__ == "__main__":
    import uvicorn

    print("Port 8000 HINT server — directs you to port 8001")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
