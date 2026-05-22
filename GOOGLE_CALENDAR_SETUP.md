# Google Calendar setup for recruit@tekleaders.io

The app reads **`CALENDAR_EMAIL`** from `.env` (default: `recruit@tekleaders.io`) for free/busy checks and creating interview events.

## Org policy blocks service account keys?

If you see **“Service account key creation is disabled”** (`iam.disableServiceAccountKeyCreation`), you **cannot** download JSON keys. Use **Option B (OAuth)** below — the app supports refresh tokens on Render via environment variables.

---

## Choose one approach

### Option A — Service account (only if your org allows JSON keys)

1. Open [Google Cloud Console](https://console.cloud.google.com/) → your project.
2. **APIs & Services** → **Library** → enable **Google Calendar API**.
3. **Credentials** → **Create credentials** → **Service account**.
   - Name: e.g. `tekleaders-hiring-calendar`
4. Open the service account → **Keys** → **Add key** → **JSON** → download.
5. Save the downloaded file as **`credentials.json`** in the project root (`hiring/credentials.json`).
   - The file must look like:
     ```json
     {
       "type": "service_account",
       "project_id": "...",
       "private_key_id": "...",
       "private_key": "-----BEGIN PRIVATE KEY-----\n...",
       "client_email": "something@....iam.gserviceaccount.com",
       ...
     }
     ```
   - **Not** the old `"installed": { "client_id": ... }` OAuth desktop format.
6. Copy the **`client_email`** from that JSON (ends with `.iam.gserviceaccount.com`).
7. In Google Calendar **as recruit@tekleaders.io** (or Workspace admin):
   - Open the **recruit** calendar → **Settings** → **Share with specific people**
   - Add the service account email
   - Permission: **Make changes to events**
8. In `.env`:
   ```
   CALENDAR_EMAIL=recruit@tekleaders.io
   GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
   ```

**On Render:** use **Environment → Secret Files** → filename `credentials.json`, paste the full service account JSON.

---

### Option B — OAuth as recruit@tekleaders.io (use when SA keys are blocked)

1. **APIs & Services** → **OAuth consent screen** → configure (Internal for Workspace if available).
2. **Credentials** → **+ Create credentials** → **OAuth client ID**.
3. **User data** → Application type **Desktop app** → Create.
4. Download JSON → save as `credentials.json` in project root (`"installed": { ... }`).
5. On your PC, sign in as **recruit@tekleaders.io** when the browser opens:
   ```bash
   cd hiring
   python check_calendar_setup.py check --days 1
   ```
   This creates **`token.json`** (gitignored).
6. Copy refresh token to Render (one-time script):
   ```bash
   python -c "import json; t=json.load(open('token.json')); print('REFRESH=', t.get('refresh_token'))"
   ```
7. From `credentials.json`, copy `client_id` and `client_secret` (under `"installed"`).

**Render environment variables:**

```env
CALENDAR_EMAIL=recruit@tekleaders.io
GOOGLE_OAUTH_CLIENT_ID=<from credentials.json installed.client_id>
GOOGLE_OAUTH_CLIENT_SECRET=<from credentials.json installed.client_secret>
GOOGLE_OAUTH_REFRESH_TOKEN=<from token.json refresh_token>
```

No service account JSON needed on Render for this path.

---

## Remove old personal calendar (akkireddy41473@gmail.com)

- Delete or replace any old `credentials.json` tied only to a personal Gmail.
- Ensure `.env` does **not** set `INTERVIEWER_EMAIL` or `CALENDAR_EMAIL` to `akkireddy41473@gmail.com`.
- In Google Calendar, remove the service account share from the old calendar if you no longer use it.

---

## Test

```bash
python check_calendar_setup.py
```

Expect free/busy for `recruit@tekleaders.io` (or a clear error if the calendar is not shared).

---

## `.env` checklist

```env
RECRUIT_EMAIL=recruit@tekleaders.io
INTERVIEWER_EMAIL=recruit@tekleaders.io
HR_INTERVIEWER_EMAIL=recruit@tekleaders.io
CALENDAR_EMAIL=recruit@tekleaders.io
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
```
