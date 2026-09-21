"""Persistence layer. One interface, two backends:

- FirestoreStore: production (Firebase Firestore, via firebase-admin). Used on Vercel.
- LocalStore:     JSON files under .localdb/ for offline development and tests.

Chosen by env: STORE=firestore|local (default: firestore if FIREBASE_SERVICE_ACCOUNT_B64 is set).

Collections
  emails        one doc per email: metadata + classification + summary used by the inbox
  documents     one doc per attachment: role, extracted text, rule-parser output, raw Gemini JSON, fields
  files         original attachment bytes (base64), only when under FILE_LIMIT
  comparisons   one doc per email: systemResult (frozen), effectiveResult (after reviews), corrections
  reviewCases   review missions
  auditLogs     append-only events
  evalRuns      self-evaluation scoreboards
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import threading
import uuid
from pathlib import Path

FILE_LIMIT = 700_000  # bytes; Firestore documents are limited to 1 MB


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:140]


def _jsonable(o):
    """Firestore/JSON-safe copy: tuples -> lists, drop non-serialisable values, no nested arrays."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        out = []
        for v in o:
            v = _jsonable(v)
            out.append(json.dumps(v) if isinstance(v, list) else v)  # Firestore forbids arrays in arrays
        return out
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


class Store:
    def get(self, col: str, doc_id: str) -> dict | None: ...
    def set(self, col: str, doc_id: str, data: dict) -> None: ...
    def update(self, col: str, doc_id: str, data: dict) -> None: ...
    def delete(self, col: str, doc_id: str) -> None: ...
    def list(self, col: str, where: tuple[str, str] | None = None, limit: int | None = None) -> list[dict]: ...

    def add(self, col: str, data: dict) -> str:
        doc_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:6]}"
        self.set(col, doc_id, data)
        return doc_id


class LocalStore(Store):
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("LOCAL_DB_DIR", Path(__file__).resolve().parent.parent / ".localdb"))
        self._lock = threading.Lock()

    def _p(self, col, doc_id):
        return self.root / col / f"{safe_id(doc_id)}.json"

    def get(self, col, doc_id):
        p = self._p(col, doc_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def set(self, col, doc_id, data):
        p = self._p(col, doc_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            p.write_text(json.dumps(_jsonable({**data, "id": doc_id}), ensure_ascii=False), encoding="utf-8")

    def update(self, col, doc_id, data):
        cur = self.get(col, doc_id) or {}
        cur.update(data)
        self.set(col, doc_id, cur)

    def delete(self, col, doc_id):
        p = self._p(col, doc_id)
        if p.exists():
            p.unlink()

    def list(self, col, where=None, limit=None):
        d = self.root / col
        if not d.exists():
            return []
        out = []
        for p in sorted(d.glob("*.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            if where and doc.get(where[0]) != where[1]:
                continue
            out.append(doc)
            if limit and len(out) >= limit:
                break
        return out


class FirestoreStore(Store):
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            b64 = os.environ["FIREBASE_SERVICE_ACCOUNT_B64"]
            info = json.loads(base64.b64decode(b64).decode("utf-8"))
            firebase_admin.initialize_app(credentials.Certificate(info))
        self.db = firestore.client()

    def get(self, col, doc_id):
        snap = self.db.collection(col).document(safe_id(doc_id)).get()
        return snap.to_dict() if snap.exists else None

    def set(self, col, doc_id, data):
        self.db.collection(col).document(safe_id(doc_id)).set(_jsonable({**data, "id": doc_id}))

    def update(self, col, doc_id, data):
        self.db.collection(col).document(safe_id(doc_id)).set(_jsonable(data), merge=True)

    def delete(self, col, doc_id):
        self.db.collection(col).document(safe_id(doc_id)).delete()

    def list(self, col, where=None, limit=None):
        q = self.db.collection(col)
        if where:
            q = q.where(field_path=where[0], op_string="==", value=where[1])
        if limit:
            q = q.limit(limit)
        return [d.to_dict() for d in q.stream()]


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        kind = os.getenv("STORE") or ("firestore" if os.getenv("FIREBASE_SERVICE_ACCOUNT_B64") else "local")
        _store = FirestoreStore() if kind == "firestore" else LocalStore()
    return _store


# ------------------------------------------------------------------ files

def put_file(store: Store, email_id: str, name: str, data: bytes, mime: str | None = None) -> dict:
    """Keep the original attachment (base64) when small enough; always return metadata."""
    doc_id = f"{email_id}__{name}"
    meta = {"emailId": email_id, "name": name, "mime": mime, "size": len(data), "stored": len(data) <= FILE_LIMIT}
    if meta["stored"]:
        store.set("files", doc_id, {**meta, "b64": base64.b64encode(data).decode("ascii")})
    return {**meta, "fileId": doc_id}


def get_file(store: Store, file_id: str) -> tuple[bytes, dict] | None:
    doc = store.get("files", file_id)
    if not doc or not doc.get("b64"):
        return None
    return base64.b64decode(doc["b64"]), doc
