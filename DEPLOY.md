# Deploying Shippeo to Vercel

One Vercel project serves both halves: the React frontend (static, built from `web/`) and the
Python API (`api/index.py`, a FastAPI app run as a Vercel Function). Firestore is the database;
the browser never talks to it directly.

## 1. Push the code to GitHub

Before pushing, confirm secrets are ignored:

```bash
git status --short
git check-ignore -v .env *-firebase-adminsdk-*.json
```

Both must show as ignored. **Never commit `.env` or the service-account `.json`** — they contain
your Gemini key and Firebase private key.

## 2. Import the project in Vercel

⚠️ **Set "Framework Preset" to `Other` — not `FastAPI`.**

This is the single most common way this deployment breaks. Vercel's Python runtime
auto-detects a framework preset when it sees `fastapi` in `requirements.txt`, and
[per the docs](https://vercel.com/docs/functions/runtimes/python/api-directory) a detected
preset *takes precedence over file-based functions* — meaning files under `/api` stop becoming
functions and the Python app is handed **every** request, including `/`, in a way it isn't built
to serve. It also causes Vercel to use the framework's own default Build Command (none) instead
of the one in `vercel.json`, so the React frontend never gets built at all.

**Symptom**: both `/` and `/api/health` return `500 FUNCTION_INVOCATION_FAILED`.

**Fix**: Project Settings → Build and Deployment → Framework Preset → change to `Other`. Confirm
(override ON if needed):
- Install Command: `npm --prefix web ci`
- Build Command: `npm --prefix web run build`
- Output Directory: `web/dist`

Then trigger a genuinely fresh deployment (see step 6 — a dashboard "Redeploy" of an old build is
not always enough).

## 3. Set environment variables

Project → Settings → Environment Variables — add each one, and **tick the "Production" checkbox**
(not just Preview/Development; this is the second most common way deployment breaks):

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your Google AI Studio key |
| `STORE` | `firestore` |
| `FIREBASE_SERVICE_ACCOUNT_B64` | base64 of the service-account JSON (same value as local `.env`) |
| `ADMIN_TOKEN` | a long random string (gates the `/api/admin/*` routes) |
| `GEMINI_MODE` | `smart` (keeps Gemini calls low) |
| `SCANNED_POLICY` | `review` |
| `PARTY_COMPARE_MODE` | `name_only` |

`GEMINI_MODEL` is optional — it defaults to `gemini-3.6-flash` in `core/gemini.py`.

Do **not** set `VERCEL` yourself; Vercel sets it automatically, and the app relies on it to know
it's running in production rather than locally.

## 4. Load the data into Firestore

Load it **from your machine, once** — not through the deployed API (bulk ingestion would exceed
the 60-second function limit). The deployed app reads the same Firestore database.

With `STORE=firestore` in your local `.env`:

```bash
python scripts/ingest.py --direct --workers 1
```

Use `--workers 1`. Firestore's free (Spark) plan allows 50,000 reads and 20,000 writes per day,
and a 4-worker burst previously exhausted the daily read quota mid-run. Quotas reset at midnight
US Pacific (07:00 UTC) and renew every day — they are not a one-time trial.

Also: **close any browser tab showing the app while a bulk ingest runs.** The UI polls for
progress, and each poll of the inbox reads every email document. (Polling now pauses on hidden
tabs and runs at 15s intervals — see `web/src/components/ui.tsx` — but a foreground tab still
costs reads.)

## 5. Verify the deployment

```bash
curl https://<your-app>.vercel.app/api/health
```

Expect `"store":"FirestoreStore"` and `"gemini":true`. If you instead see
`"store":"LocalStore"` and `"gemini":false`, your environment variables are not reaching the
running function — see step 6.

## 6. If env vars don't take effect after saving them

Ticking "Production" and saving does **not** retroactively update a deployment that's already
running — Vercel needs a fresh build to read the current values. In order of reliability:

1. Deployments tab → latest deployment → **⋯ → Redeploy**. If a "Use existing Build Cache"
   checkbox appears, **uncheck it**.
2. If that still doesn't pick up the new values, push any commit to `main` (a git-triggered
   deployment is unambiguously fresh and cannot reuse a stale cached build).
3. Confirm on the deployment's own detail page which environment variables it actually had —
   Vercel shows a snapshot per-deployment, which is the definitive answer if the dashboard's
   top-level Settings page is ambiguous.

## Local development

```bash
pip install -r requirements-dev.txt     # runtime deps + uvicorn/pytest/httpx
uvicorn api.index:app --port 8000       # API   (reads .env)
npm --prefix web run dev                # UI    (proxies /api to :8000)
```

Set `STORE=local` in `.env` to use `.localdb/` JSON files instead of Firestore — no quota, no
network, and the same code path. Vercel cannot use `STORE=local`: serverless functions have no
persistent disk between requests, so Firestore is required in production.
