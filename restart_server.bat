@echo off
cd /d "%~dp0"
echo Stopping anything on ports 8000 and 8001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING"') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak >nul
echo Starting latest hiring app...
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" launch.py
) else (
  python launch.py
)
