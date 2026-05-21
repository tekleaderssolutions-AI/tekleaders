@echo off
title Hiring Portal Server (OpenAI JD)
cd /d "%~dp0"
echo.
echo === hiring/main.py on port 8000 (NOT TalentForgeAI) ===
echo Starting from: %CD%
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
  echo Stopping old process PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

if exist "venv\Scripts\python.exe" (
  set PY=venv\Scripts\python.exe
) else (
  set PY=python
)

echo Using: %PY%
"%PY%" -m pip install "openai>=1.0.0" -q
"%PY%" -c "from config import effective_jd_ai_provider; print('JD provider:', effective_jd_ai_provider())"
echo.
echo Open http://127.0.0.1:8000/api/health — expect jd_ai_provider: openai
echo.
"%PY%" launch.py
pause
