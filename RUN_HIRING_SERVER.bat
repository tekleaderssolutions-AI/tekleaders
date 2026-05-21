@echo off
title Hiring — ports 8001 (app) + 8000 (hint)
cd /d "%~dp0"

echo.
echo ============================================
echo   HIRING APP
echo   Real server:  http://127.0.0.1:8001
echo   (Port 8000 only shows a help message)
echo ============================================
echo.

for %%P in (8000 8001) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
    echo Stopping port %%P PID %%a
    taskkill /F /PID %%a >nul 2>&1
  )
)
timeout /t 2 /nobreak >nul

if exist "venv\Scripts\python.exe" (set PY=venv\Scripts\python.exe) else (set PY=python)

"%PY%" -m pip install "openai>=1.0.0" fastapi uvicorn pdfplumber "python-docx>=1.1.0" python-multipart python-dotenv psycopg2-binary -q

echo Starting port 8000 hint (background)...
start "Port8000-Hint" /MIN "%PY%" hint_8000.py
timeout /t 2 /nobreak >nul

echo.
echo Starting hiring app on port 8001...
echo.
echo >>> OPEN IN BROWSER: http://127.0.0.1:8001/api/health
echo >>> ADMIN PORTAL:     http://127.0.0.1:8001/admin
echo.
"%PY%" launch.py
