# Email setup — recruit@tekleaders.io (Google Workspace)

The **Send Mail** button calls `POST /send-emails` → **OpenAI** writes the email (from resume + JD) → **Google SMTP** sends it. Match scores are **not** included in the email body.

## Google Workspace SMTP settings (use these in `.env`)

```env
SMTP_HOST="smtp.gmail.com"
SMTP_PORT="587"
SMTP_USER="recruit@tekleaders.io"
SMTP_PASSWORD="xxxx xxxx xxxx xxxx"
FROM_EMAIL="recruit@tekleaders.io"
REPLY_TO_EMAIL="recruit@tekleaders.io"
BASE_URL="http://127.0.0.1:8001"
COMPANY_NAME="TekLeaders"
```

| Setting | Value |
|---------|--------|
| Server | `smtp.gmail.com` |
| Port | `587` (STARTTLS) |
| Username | Full address: `recruit@tekleaders.io` |
| Password | **App Password** (16 characters) — not your normal Gmail/Workspace login password |
| From / Reply-To | `recruit@tekleaders.io` |

---

## Step-by-step: create a Google App Password

Do this while signed in as **recruit@tekleaders.io** (or as a Workspace admin for that user).

### A. Turn on 2-Step Verification (required for App Passwords)

1. Open https://myaccount.google.com/security (or Google Admin for the user).
2. Under **How you sign in to Google**, enable **2-Step Verification**.
3. Complete setup (phone / authenticator).

Workspace note: Admin can enforce 2SV under **Admin console → Security → Authentication → 2-step verification**.

### B. Create the App Password

1. Go to https://myaccount.google.com/apppasswords  
   (If missing: Security → 2-Step Verification → App passwords at the bottom.)
2. **Select app:** Mail (or Other → name it `Hiring POC`).
3. **Select device:** Windows Computer (or Other).
4. Click **Generate**.
5. Google shows a **16-character password** (e.g. `abcd efgh ijkl mnop`).
6. Copy it into `.env` as `SMTP_PASSWORD` — spaces are optional; the app accepts with or without spaces.

### C. If App Passwords are blocked

Workspace admin must allow them:

- **Admin console** → **Security** → **Authentication** → **Allow users to manage their access to less secure apps** / **App access control**
- Or: **Admin console** → **Apps** → **Google Workspace** → **Gmail** → ensure SMTP allowed for the organization

Some orgs use **SMTP relay** instead; ask IT if app passwords are disabled.

---

## Update `.env` and restart

1. Paste the app password into `SMTP_PASSWORD=` in `hiring/.env`.
2. Confirm `SMTP_USER` and `FROM_EMAIL` are `recruit@tekleaders.io`.
3. Stop Python on port **8001**.
4. Run `RUN_HIRING_SERVER.bat` or `start_hiring_8001.py`.
5. Open http://127.0.0.1:8001/api/health — should be OK.

---

## Test sending

**Option 1 — UI**

1. http://127.0.0.1:8001/recruiter → login.
2. Select client + role → **Scan**.
3. Select a candidate **with an email on the resume**.
4. **Send Mail** → confirm alert shows `Sent 1 of 1...`.

**Option 2 — script**

```bash
cd hiring
python test_email_simple.py
```

(Edit that script’s `to_email` to your test inbox if needed.)

---

## Other requirements (unchanged)

| Item | Status |
|------|--------|
| `OPENAI_API_KEY` | Email body + Scan/upload (same key in `.env`) |
| PostgreSQL running | Required |
| Candidate email on resume | Required per send |

---

## Production: `BASE_URL`

For **Interested / Not interested** links in emails, set:

```env
BASE_URL="https://your-public-domain.com"
```

`http://127.0.0.1:8001` only works on your machine.

---

## Troubleshooting (Google)

| Error | Fix |
|-------|-----|
| `535 Username and Password not accepted` | Wrong password — use **App Password**, not login password |
| `SMTP_PASSWORD is not set` | Fill `.env` and restart server |
| App passwords menu missing | Enable 2-Step Verification first |
| `Less secure app access` | Deprecated — use App Passwords only |
| Mail goes to spam | Ask IT to configure SPF/DKIM for `tekleaders.io` |
| `No email address found` | Re-upload resume; parser must extract email |
