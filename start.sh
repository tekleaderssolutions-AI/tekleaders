#!/usr/bin/env bash
set -euo pipefail

# Migrations (non-fatal — startup hook also retries)
python -c "import migrations; migrations.init_db()" || echo "[start] migration warning — continuing"

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
