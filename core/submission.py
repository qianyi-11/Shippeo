"""Build the self-evaluation submission in the organisers' format (sample_submission.json):

{ "email_001": {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": null,
                "has_defect": true, "defect_fields": ["consignee"]} }

category      BL_COMPARISON | SI_REQUEST | INVOICE_QUERY | GENERAL | SPAM
status        OK | MISMATCH | NEEDS_REVIEW   (non-comparison emails: OK)
review_reason wrong_doc_type | missing_attachment | unreadable | missing_value | null
"""
from __future__ import annotations

from .fields import FIELDS

CATEGORY_TO_DATASET = {
    "document_comparison": "BL_COMPARISON",
    "new_si_request": "SI_REQUEST",
    "invoice_query": "INVOICE_QUERY",
    "general_message": "GENERAL",
    "spam": "SPAM",
}

REVIEW_REASONS = {"wrong_doc_type", "missing_attachment", "unreadable", "missing_value"}


def decide(result: dict) -> dict:
    """Map one pipeline result (optionally with reviewer overrides) to a submission entry."""
    cls = result.get("classification") or {}
    category = CATEGORY_TO_DATASET.get(cls.get("category"), "GENERAL")
    entry = {"category": category, "status": "OK", "review_reason": None,
             "defect_fields": [], "has_defect": False}
    if category != "BL_COMPARISON":
        return entry
    cmp = result.get("effectiveComparison") or result.get("comparison") or {}
    status = cmp.get("status")
    mismatched = [f for f in FIELDS if f in (cmp.get("mismatchedFields") or [])]
    if status == "incomplete" or result.get("processingStatus") == "failed_retry_available":
        entry.update(status="NEEDS_REVIEW", review_reason=cmp.get("reviewReason") or "unreadable")
    elif mismatched:
        # A confirmed discrepancy is reported even if another field also needs review.
        entry.update(status="MISMATCH", has_defect=True, defect_fields=mismatched)
    elif status == "needs_review":
        reason = cmp.get("reviewReason")
        entry.update(status="NEEDS_REVIEW", review_reason=reason if reason in REVIEW_REASONS else "missing_value")
    return entry


def build_submission(results: list[dict], sample: dict | None = None) -> dict:
    sub = {r["emailId"]: decide(r) for r in results}
    if sample:  # every email_id in the sample must be present
        for eid in sample:
            sub.setdefault(eid, {"category": "GENERAL", "status": "OK", "review_reason": None,
                                 "defect_fields": [], "has_defect": False})
        sub = {eid: sub[eid] for eid in sorted(sub)}
    return sub


def load_sample(path) -> dict:
    import json
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding="utf-8"))
