# Render deploy failed — fix checklist

If deploy shows **"Cause of failure could not be determined"**, check these in the [Render Dashboard](https://dashboard.render.com) → your web service → **Settings**:

## Start command (required)

Use **one** of these (not `python main.py` alone):

```bash
bash start.sh
```

or:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Wrong:** `python main.py` without `PORT` (old builds bound to `127.0.0.1` only).

## Build command

```bash
pip install -r requirements.txt && chmod +x start.sh
```

Do **not** run `pip install` in the start command — it times out on the free plan.

## Environment

- Do **not** override `PORT` manually; Render sets it.
- Set `DATABASE_URL` or `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT`.
- Set `OPENAI_API_KEY`, `BASE_URL=https://tekleaders.onrender.com`, SMTP vars.

## Health check

Path: `/api/health` — should return JSON with `"status":"ok"`.

## Logs

Dashboard → **Logs** → filter **Deploy** (not just Runtime). Look for:

- `bad interpreter` → `start.sh` line endings (fixed via `.gitattributes`)
- `Permission denied` → use `bash start.sh` or `chmod +x start.sh` in build
- `ModuleNotFoundError` → build failed; check `requirements.txt`
- Migration errors → DB credentials; app still starts (migrations are non-fatal in `start.sh`)

## Manual redeploy

After pushing this fix: **Manual Deploy** → **Clear build cache & deploy**.
