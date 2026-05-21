@echo off
echo Stopping processes on ports 8000 and 8001...
for %%P in (8000 8001) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
    echo   Port %%P PID %%a
    taskkill /F /PID %%a >nul 2>&1
  )
)
timeout /t 2 /nobreak >nul
echo Done.
