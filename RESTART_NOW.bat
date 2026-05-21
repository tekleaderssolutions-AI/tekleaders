@echo off
cd /d "%~dp0"
echo Stopping port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "venv\Scripts\python.exe" (
  set PY=venv\Scripts\python.exe
) else (
  set PY=python
)

echo Installing openai...
"%PY%" -m pip install "openai>=1.0.0" -q
echo Checking JD provider...
"%PY%" -c "from config import effective_jd_ai_provider; print('JD provider:', effective_jd_ai_provider())"

echo Starting server...
start "Hiring Server" "%PY%" serve.py
