$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Start-Sleep -Seconds 2

$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pip install "openai>=1.0.0" -q
& $py -c "from config import effective_jd_ai_provider; print('JD provider:', effective_jd_ai_provider())"

Write-Host "Starting server on http://127.0.0.1:8000 ..."
& $py serve.py
