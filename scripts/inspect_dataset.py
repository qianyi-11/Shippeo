"""Print the dataset's shape so the adapter and submission format can be confirmed.

Usage: python scripts/inspect_dataset.py [--source data|http://localhost:8080]"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from _common import DATA_DIR, open_inbox


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    a = ap.parse_args()
    inbox = open_inbox(a.source)
    emails = list(inbox)
    print(f"Emails: {len(emails)}")
    if not emails:
        return
    first = emails[0]
    print("\nFirst record keys:", list(first.keys()) if isinstance(first, dict) else type(first))
    print(json.dumps(first, indent=2, ensure_ascii=False, default=str)[:3000])
    n_att = Counter(len((e.get("attachments") or [])) for e in emails if isinstance(e, dict))
    print("\nAttachment count distribution:", dict(n_att))
    atts = next((e.get("attachments") for e in emails if isinstance(e, dict) and e.get("attachments")), None)
    if atts:
        print("\nAttachment field format:", json.dumps(atts, indent=2, default=str)[:800])
        a0 = atts[0]
        path = a0 if isinstance(a0, str) else (a0.get("path") or a0.get("filename") or a0.get("name"))
        try:
            print(f"\n--- read_text({path!r}) ---\n{inbox.read_text(path)[:1500]}")
        except Exception as e:  # noqa: BLE001
            print(f"read_text failed: {e}")
    sample = DATA_DIR / "sample_submission.json"
    if sample.exists():
        print("\n--- sample_submission.json ---")
        print(sample.read_text(encoding="utf-8")[:3000])
    else:
        print(f"\nsample_submission.json not found in {DATA_DIR}")


if __name__ == "__main__":
    main()
