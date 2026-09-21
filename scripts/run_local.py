"""Run the whole pipeline locally and (optionally) submit to the self-evaluation endpoint.

Usage:
  python scripts/run_local.py                          # static bundle in data/
  python scripts/run_local.py --source http://localhost:8080 --submit
  python scripts/run_local.py --only EMAIL_ID --verbose
  python scripts/run_local.py --no-gemini              # rule-based only (offline)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

from _common import DATA_DIR, ROOT, open_inbox, make_reader

from core import gemini
from core.pipeline import process_email, normalize_email
from core.submission import build_submission, load_sample

OUT = ROOT / "out"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="data folder or http://localhost:8080")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--no-gemini", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    use_gemini = not a.no_gemini
    if use_gemini and not gemini.available():
        print("! GEMINI_API_KEY not set - running rule-based only. Add it to .env for full accuracy.")
        use_gemini = False

    inbox = open_inbox(a.source)
    reader = make_reader(inbox, a.source)
    records = [r for r in inbox]
    if a.only:
        records = [r for r in records if normalize_email(r)["emailId"] == a.only]
    print(f"Processing {len(records)} email(s) with Gemini="
          f"{'on (' + gemini.DEFAULT_MODEL + ', mode=' + gemini.MODE + ')' if use_gemini else 'off'} ...")

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        results = list(ex.map(lambda r: process_email(r, reader, use_gemini=use_gemini), records))

    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    sample_path = DATA_DIR / "sample_submission.json"
    sample = load_sample(sample_path) if sample_path.exists() else {}
    submission = build_submission(results, sample)
    (OUT / "submission.json").write_text(json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8")

    # summary table
    print(f"\n{'email_id':<14} {'category':<20} {'status':<22} {'review':<6} mismatched / reason")
    for r in results:
        cls = r.get("classification") or {}
        cmp = r.get("comparison") or {}
        detail = ", ".join(cmp.get("mismatchedFields", [])) or cmp.get("headline", "") or ""
        if r["errors"]:
            detail = "ERROR: " + r["errors"][0][:60]
        print(f"{r['emailId']:<14} {cls.get('category', '?'):<20} {r['processingStatus']:<22} "
              f"{'yes' if r['reviewCases'] else '':<6} {detail}")
        if a.verbose and cmp.get("fields"):
            for f, fr in cmp["fields"].items():
                print(f"    {f:<18} {fr['state']:<24} SI={fr['siOriginal']!r:<30} BL={fr['blOriginal']!r}")
    n_review = sum(1 for r in results if r["reviewCases"])
    print(f"\nWrote out/results.json and out/submission.json. {n_review} email(s) have review cases.")

    if a.submit:
        if not hasattr(inbox, "submit"):
            raise SystemExit("This loader has no submit(); use the Docker server source.")
        score = inbox.submit(submission)
        print("\nScoreboard:\n" + json.dumps(score, indent=2, default=str))
        try:
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        except Exception:  # noqa: BLE001
            commit = None
        hist_path = OUT / "eval_history.json"
        hist = json.loads(hist_path.read_text()) if hist_path.exists() else []
        hist.append({"at": dt.datetime.now().isoformat(timespec="seconds"), "commit": commit,
                     "gemini": use_gemini, "model": gemini.DEFAULT_MODEL if use_gemini else None, "score": score})
        hist_path.write_text(json.dumps(hist, indent=2, default=str))


if __name__ == "__main__":
    main()
