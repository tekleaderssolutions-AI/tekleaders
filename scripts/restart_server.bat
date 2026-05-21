@echo off
cd /d "%~dp0.."
echo Project: %CD%
echo Stopping anything on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak >nul
echo Starting hiring/main.py (NOT TalentForgeAI)...
"%~dp0..\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
echo.
echo Login:  http://127.0.0.1:8000/login
echo Signup: http://127.0.0.1:8000/signup
echo Health: http://127.0.0.1:8000/api/health
pause
