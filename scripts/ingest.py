"""Load the organisers' dataset into Shippeo's cloud store and have the cloud process it.

Usage (cloud, recommended):
  python scripts/ingest.py --api https://<your-app>.vercel.app            # uses ADMIN_TOKEN from .env
  python scripts/ingest.py --api http://localhost:8000 --only email_001

Usage (direct to the store, no API; STORE=local or FIREBASE_SERVICE_ACCOUNT_B64 set):
  python scripts/ingest.py --direct
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from _common import open_inbox


def post(url: str, payload: dict, token: str | None = None, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"X-Admin-Token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="dataset folder or http://localhost:8080")
    ap.add_argument("--api", default=os.getenv("API_BASE_URL"))
    ap.add_argument("--direct", action="store_true", help="write to the store directly instead of the API")
    ap.add_argument("--only", default=None)
    ap.add_argument("--no-process", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()

    inbox = open_inbox(a.source)
    records = [r for r in inbox if not a.only or r["email_id"] == a.only]
    print(f"{len(records)} email(s) to ingest")

    def files_of(r):
        return {p: inbox.read_bytes(p) for p in r.get("attachments", [])}

    if a.direct:
        from core import service
        from core.store import get_store
        store = get_store()
        for r in records:
            service.ingest_email(store, r, files_of(r))
        print(f"Ingested into {type(store).__name__}.")
        if not a.no_process:
            def run(r):
                res = service.process_stored(store, r["email_id"])
                print(f"  {r['email_id']}: {res['processingStatus']}")
            with ThreadPoolExecutor(a.workers) as ex:
                list(ex.map(run, records))
        return

    if not a.api:
        raise SystemExit("Give --api https://<app>.vercel.app (or set API_BASE_URL), or use --direct.")
    base, token = a.api.rstrip("/"), os.getenv("ADMIN_TOKEN")
    if not token:
        raise SystemExit("ADMIN_TOKEN is not set in .env (it must match the one configured on Vercel).")
    for i in range(0, len(records), 20):
        batch = records[i:i + 20]
        items = [{"record": r, "files": {p: base64.b64encode(b).decode() for p, b in files_of(r).items()}}
                 for r in batch]
        post(f"{base}/api/admin/ingest", {"items": items, "process": False}, token)
        print(f"  uploaded {i + len(batch)}/{len(records)}")
    if a.no_process:
        return

    def run(r):
        for attempt in range(3):
            try:
                res = post(f"{base}/api/process", {"emailId": r["email_id"]}, timeout=300)
                print(f"  {r['email_id']}: {res['processingStatus']}")
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(30)
                    continue
                print(f"  {r['email_id']}: HTTP {e.code} {e.read()[:200]!r}")
                return
            except Exception as e:  # noqa: BLE001
                print(f"  {r['email_id']}: {e}")
                time.sleep(5)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, records))
    print("Done. Open the web app to see the results.")


if __name__ == "__main__":
    main()
