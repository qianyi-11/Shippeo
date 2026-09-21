"""Score what the CLOUD app currently shows (including reviewer corrections) on the organisers'
self-evaluation server, and save the scoreboard so the Evaluation screen can chart it.

  python scripts/submit.py --api https://<your-app>.vercel.app --server http://localhost:8080
  python scripts/submit.py --direct --server http://localhost:8080      # read the store directly
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request

from _common import ROOT, import_loader
from ingest import post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("API_BASE_URL"))
    ap.add_argument("--direct", action="store_true")
    ap.add_argument("--server", default="http://localhost:8080", help="organisers' scoring server")
    ap.add_argument("--note", default=None)
    a = ap.parse_args()

    if a.direct:
        from core import service
        from core.store import get_store
        sub = service.submission(get_store())
    else:
        with urllib.request.urlopen(a.api.rstrip("/") + "/api/submission", timeout=120) as r:
            sub = json.loads(r.read())
    loader = import_loader()
    inbox = loader.Inbox(a.server)
    sample = inbox.sample_submission()
    for eid in sample:
        sub.setdefault(eid, {"category": "GENERAL", "status": "OK", "review_reason": None,
                             "defect_fields": [], "has_defect": False})
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "submission_cloud.json").write_text(json.dumps(sub, indent=2))
    score = inbox.submit(sub)
    print(json.dumps(score, indent=2))
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        commit = None
    payload = {"score": score, "note": a.note, "commit": commit}
    if a.direct:
        from core.store import get_store, now_iso
        get_store().add("evalRuns", {"at": now_iso(), **payload})
    elif os.getenv("ADMIN_TOKEN"):
        post(a.api.rstrip("/") + "/api/admin/eval-runs", payload, os.getenv("ADMIN_TOKEN"))
    print("Saved to the Evaluation screen.")


if __name__ == "__main__":
    main()
