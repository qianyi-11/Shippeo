"""Shippeo cloud backend: one FastAPI app, deployed as a Vercel Python serverless function.
All Gemini calls and all Firestore writes happen here; the browser never sees a key.

Local:  uvicorn api.index:app --reload --port 8000   (STORE=local uses .localdb/)
"""
from __future__ import annotations

import base64
import os
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from core import gemini, service  # noqa: E402
from core.readers import MIME, ext_of  # noqa: E402
from core.review import DECISIONS, ReviewError  # noqa: E402
from core.store import get_file, get_store, now_iso  # noqa: E402

app = FastAPI(title="Shippeo API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
MAX_UPLOAD = 4 * 1024 * 1024
ALLOWED_EXT = {".txt", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}

# --- simple per-IP rate limit (per warm instance; enough to stop casual abuse of the public demo)
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request, limit: int = 30, window: int = 600) -> None:
    ip = (request.headers.get("x-forwarded-for") or request.client.host if request.client else "?").split(",")[0]
    q, now = _hits[ip], time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests from this address. Try again in a few minutes.")
    q.append(now)


def require_admin(token: str | None) -> None:
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(401, "Admin token required.")


@app.exception_handler(ReviewError)
async def _review_error(_, exc: ReviewError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ read

@app.get("/api/health")
def health():
    store = get_store()
    return {"ok": True, "store": type(store).__name__, "gemini": gemini.available(),
            "geminiModel": gemini.DEFAULT_MODEL, "geminiMode": gemini.MODE, "time": now_iso()}


@app.get("/api/emails")
def list_emails():
    keep = ("emailId", "sender", "subject", "receivedAt", "attachmentCount", "category", "classificationConfidence",
            "processingStatus", "realityStatus", "riskLevel", "suggestedAction", "headline", "mismatchedFields",
            "shipmentRef", "searchText", "openCases", "source", "updatedAt", "reviewReason", "statusReason")
    rows = [{k: e.get(k) for k in keep} for e in get_store().list("emails")]
    return sorted(rows, key=lambda r: r["emailId"] or "")


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    d = service.email_detail(get_store(), email_id)
    if not d:
        raise HTTPException(404, "Email not found.")
    return d


@app.get("/api/cases")
def cases(status: str | None = "open"):
    return service.list_cases(get_store(), None if status == "all" else status)


@app.get("/api/stats")
def stats():
    return service.stats(get_store())


@app.get("/api/report/{email_id}")
def report(email_id: str):
    r = service.report(get_store(), email_id)
    if not r:
        raise HTTPException(404, "Email not found.")
    return r


@app.get("/api/files/{file_id}")
def download(file_id: str):
    got = get_file(get_store(), file_id)
    if not got:
        raise HTTPException(404, "Original file not stored.")
    data, meta = got
    return Response(data, media_type=meta.get("mime") or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{meta.get("name")}"'})


@app.get("/api/submission")
def get_submission():
    return service.submission(get_store())


@app.get("/api/eval-runs")
def eval_runs():
    return sorted(get_store().list("evalRuns"), key=lambda r: r.get("at") or "")


@app.get("/api/decisions")
def decisions():
    return DECISIONS


# ------------------------------------------------------------------ write

class ProcessBody(BaseModel):
    emailId: str


@app.post("/api/process")
def process(body: ProcessBody, request: Request):
    rate_limit(request, limit=60)
    store = get_store()
    try:
        r = service.process_stored(store, body.emailId)
    except KeyError:
        raise HTTPException(404, "Email not found.")
    return {"emailId": body.emailId, "processingStatus": r["processingStatus"],
            "headline": (r.get("comparison") or {}).get("headline")}


@app.post("/api/retry")
def retry(body: ProcessBody, request: Request):
    rate_limit(request)
    service.audit(get_store(), body.emailId, "retry_requested", "Manual retry from the UI", "user")
    return process(body, request)


class ReviewBody(BaseModel):
    reviewerName: str
    decision: str
    comment: str = ""
    correctedValue: str | None = None


@app.post("/api/cases/{case_id}/resolve")
def resolve(case_id: str, body: ReviewBody, request: Request):
    rate_limit(request)
    store = get_store()
    out = service.resolve_case(store, case_id, body.reviewerName, body.decision, body.comment, body.correctedValue)
    if body.decision == "retry_extraction":
        service.process_stored(store, out["case"]["emailId"])
    return out


@app.post("/api/upload")
async def upload(request: Request, subject: str = Form(...), body: str = Form(""),
                 sender: str = Form("demo@shippeo.app"), files: list[UploadFile] = File(default=[])):
    rate_limit(request, limit=10)
    store = get_store()
    blobs, total = {}, 0
    for f in files:
        if ext_of(f.filename or "") not in ALLOWED_EXT:
            raise HTTPException(400, f"Unsupported file type: {f.filename}")
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "Uploads are limited to 4 MB in total.")
        blobs[f.filename] = data
    n = len([e for e in store.list("emails") if (e.get("source") == "upload")]) + 1
    eid = f"upload_{time.strftime('%m%d%H%M%S')}_{n:03d}"
    record = {"email_id": eid, "from": sender, "subject": subject, "body": body, "received_at": now_iso(),
              "attachments": list(blobs.keys())}
    service.ingest_email(store, record, blobs, source="upload")
    r = service.process_stored(store, eid)
    return {"emailId": eid, "processingStatus": r["processingStatus"]}


# ------------------------------------------------------------------ admin (local scripts only)

class IngestItem(BaseModel):
    record: dict
    files: dict[str, str] = {}  # path -> base64


class IngestBody(BaseModel):
    items: list[IngestItem]
    process: bool = False


@app.post("/api/admin/ingest")
def admin_ingest(body: IngestBody, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    store = get_store()
    out = []
    for it in body.items:
        files = {k: base64.b64decode(v) for k, v in it.files.items()}
        eid = service.ingest_email(store, it.record, files)
        status = "queued"
        if body.process:
            status = service.process_stored(store, eid)["processingStatus"]
        out.append({"emailId": eid, "processingStatus": status})
    return out


@app.post("/api/admin/process-queued")
def admin_process_queued(limit: int = 5, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    store = get_store()
    queued = [e["emailId"] for e in store.list("emails") if e.get("processingStatus") in ("queued", None)]
    done = []
    t0 = time.time()
    for eid in queued[:limit]:
        done.append({"emailId": eid, "processingStatus": service.process_stored(store, eid)["processingStatus"]})
        if time.time() - t0 > 45:
            break
    return {"processed": done, "remaining": len(queued) - len(done)}


class EvalBody(BaseModel):
    score: dict
    note: str | None = None
    commit: str | None = None


@app.post("/api/admin/eval-runs")
def admin_eval(body: EvalBody, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    get_store().add("evalRuns", {"at": now_iso(), "score": body.score, "note": body.note, "commit": body.commit})
    return {"ok": True}


@app.post("/api/admin/reset-demo")
def admin_reset(x_admin_token: str | None = Header(default=None)):
    """Remove uploaded emails and undo all review decisions (dataset emails are kept)."""
    require_admin(x_admin_token)
    store = get_store()
    removed = 0
    for e in store.list("emails"):
        if e.get("source") == "upload":
            store.delete("emails", e["emailId"])
            removed += 1
    for c in store.list("comparisons"):
        if c.get("corrections"):
            store.update("comparisons", c["id"], {"effectiveResult": c["systemResult"], "corrections": []})
            store.update("emails", c["id"], service._summary_fields(c["systemResult"]))
    reopened = 0
    for c in store.list("reviewCases"):
        if c.get("reviewerDecision"):
            store.update("reviewCases", c["id"], {"status": "open", "reviewerName": None, "reviewerDecision": None,
                                                  "reviewerComment": None, "reviewedAt": None, "correctedValue": None})
            reopened += 1
    for e in store.list("emails"):
        n = len([c for c in store.list("reviewCases", where=("emailId", e["emailId"])) if c.get("status") == "open"])
        store.update("emails", e["emailId"], {"openCases": n, "needsHumanReview": bool(n)})
    return {"removedUploads": removed, "reopenedCases": reopened}


# serve the built frontend when running locally with uvicorn (Vercel serves web/dist itself)
_dist = ROOT / "web" / "dist"
if _dist.exists() and not os.getenv("VERCEL"):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
