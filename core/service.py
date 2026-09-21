"""Application service: glue between the pipeline, the store and the API / scripts."""
from __future__ import annotations

import collections
import re

from .fields import FIELD_DISPLAY, FIELDS
from .pipeline import normalize_email, process_email
from .readers import MIME, ext_of
from .review import DECISIONS, ReviewError, apply_decision
from .store import Store, get_file, now_iso, put_file, safe_id
from .submission import build_submission

REALITY = {"match": "converged", "mismatch": "diverging", "needs_review": "unresolved", "incomplete": "incomplete"}
_REF_RX = re.compile(r"\b\d[A-Z]{3}-\d{5}\b")


def audit(store: Store, email_id: str | None, event: str, details: str, actor: str = "system") -> None:
    store.add("auditLogs", {"emailId": email_id, "eventType": event, "details": details, "actor": actor,
                            "createdAt": now_iso()})


# ------------------------------------------------------------------ ingest

def ingest_email(store: Store, record: dict, files: dict[str, bytes], source: str = "dataset") -> str:
    """Save an email + its attachment bytes; status queued. Returns emailId."""
    email = normalize_email(record)
    eid = email["emailId"]
    atts = []
    for a in email["attachments"]:
        data = files.get(a["path"]) if a["path"] in files else files.get(a["name"])
        meta = {"name": a["name"], "path": a["path"], "mime": MIME.get(ext_of(a["name"]), "application/octet-stream")}
        if data is not None:
            meta.update(put_file(store, eid, a["name"], data, meta["mime"]))
        else:
            meta.update(size=None, stored=False, fileId=None, missing=True)
        atts.append(meta)
    prev = store.get("emails", eid) or {}
    store.set("emails", eid, {
        "emailId": eid, "sender": email["sender"], "subject": email["subject"], "body": email["body"],
        "receivedAt": email["receivedAt"], "attachments": atts, "attachmentCount": len(atts),
        "source": source, "processingStatus": "queued", "createdAt": prev.get("createdAt") or now_iso(),
        "updatedAt": now_iso(),
    })
    audit(store, eid, "email_ingested", f"{len(atts)} attachment(s) from {source}")
    return eid


# ------------------------------------------------------------------ process

def process_stored(store: Store, email_id: str, use_gemini: bool = True) -> dict:
    doc = store.get("emails", email_id)
    if not doc:
        raise KeyError(email_id)
    store.update("emails", email_id, {"processingStatus": "classifying", "updatedAt": now_iso()})

    def read(att: dict) -> bytes:
        meta = next((a for a in doc["attachments"] if a["name"] == att["name"]), None)
        if not meta or not meta.get("fileId"):
            raise FileNotFoundError(f"{att['name']} was not received")
        got = get_file(store, meta["fileId"])
        if not got:
            raise FileNotFoundError(f"{att['name']} is too large to keep or was not stored")
        return got[0]

    record = {"email_id": email_id, "from": doc.get("sender"), "subject": doc.get("subject"),
              "body": doc.get("body"), "received_at": doc.get("receivedAt"),
              "attachments": [a["path"] or a["name"] for a in doc.get("attachments", [])]}

    def on_status(s, detail):
        store.update("emails", email_id, {"processingStatus": s, "updatedAt": now_iso()})

    result = process_email(record, read, use_gemini=use_gemini, on_status=on_status)
    save_result(store, result)
    return result


def _shipment_ref(email: dict, docs: dict) -> str | None:
    for text in (email.get("subject") or "", email.get("body") or ""):
        m = _REF_RX.search(text)
        if m:
            return m.group(0)
    for d in docs.values():
        m = _REF_RX.search(d.get("text") or "")
        if m:
            return m.group(0)
    return None


def save_result(store: Store, result: dict) -> None:
    eid = result["emailId"]
    email = result["email"]
    cls = result.get("classification") or {}
    cmp = result.get("comparison")
    ts = now_iso()

    for name, d in result["documents"].items():
        store.set("documents", f"{eid}__{name}", {"emailId": eid, "fileName": name, **d, "updatedAt": ts})

    prev_cmp = store.get("comparisons", eid)
    if cmp is not None:
        store.set("comparisons", eid, {"emailId": eid, "systemResult": cmp, "effectiveResult": cmp,
                                       "corrections": [], "createdAt": (prev_cmp or {}).get("createdAt") or ts,
                                       "updatedAt": ts})
    elif prev_cmp:
        store.delete("comparisons", eid)

    # replace open system cases; keep ones a person already acted on
    for c in store.list("reviewCases", where=("emailId", eid)):
        if c.get("status") == "open" or c.get("status") == "retrying":
            store.delete("reviewCases", c["id"])
    for i, c in enumerate(result["reviewCases"]):
        cid = f"{eid}__{i}_{safe_id(c.get('field') or 'doc')}"
        store.set("reviewCases", cid, {**c, "reviewCaseId": cid, "status": "open",
                                       "title": _mission_title(c, cmp), "reviewerName": None,
                                       "reviewerDecision": None, "reviewerComment": None, "reviewedAt": None,
                                       "history": [{"at": ts, "event": "created", "by": "system"}]})
    for a in result["audit"]:
        audit(store, eid, a["status"], a["detail"] or a["status"])

    summary = _summary_fields(cmp)
    fields = (cmp or {}).get("fields") or {}
    search = " ".join(str(fields.get(f, {}).get(k) or "") for f in FIELDS for k in ("siOriginal", "blOriginal"))
    store.update("emails", eid, {
        "category": cls.get("category"), "classificationConfidence": cls.get("confidence"),
        "classificationReason": cls.get("reason"), "classificationSource": cls.get("source"),
        "suggestedAction": cls.get("suggested_action"), "classificationRaw": cls.get("geminiRaw"),
        "processingStatus": result["processingStatus"],
        "statusReason": result["errors"][0] if result["errors"] else None,
        "needsHumanReview": bool(result["reviewCases"]), "openCases": len(result["reviewCases"]),
        "shipmentRef": _shipment_ref(email, result["documents"]),
        "searchText": (search + " " + (email.get("subject") or "")).lower()[:3000],
        "processedAt": ts, "updatedAt": ts, "geminiUsed": result.get("geminiUsed"), **summary,
    })


def _summary_fields(cmp: dict | None) -> dict:
    if not cmp:
        return {"realityStatus": None, "riskLevel": None, "riskReason": None, "headline": None,
                "mismatchedFields": [], "comparisonStatus": None, "overallConfidence": None}
    return {"realityStatus": REALITY.get(cmp["status"]), "riskLevel": cmp.get("riskLevel"),
            "riskReason": cmp.get("riskReason"), "headline": cmp.get("headline"),
            "mismatchedFields": cmp.get("mismatchedFields", []), "comparisonStatus": cmp["status"],
            "overallConfidence": cmp.get("overallConfidence"), "reviewReason": cmp.get("reviewReason")}


def _mission_title(case: dict, cmp: dict | None) -> str:
    f = case.get("field")
    if f in FIELD_DISPLAY:
        return f"Confirm the {FIELD_DISPLAY[f].lower()}"
    if f == "classification":
        return "Confirm the email category"
    r = (case.get("reason") or "").lower()
    if "no si or draft bl is attached" in r or "attachments appear" in r:
        return "Locate the missing attachments"
    if "missing" in r and "bl" in r:
        return "Locate the missing draft Bill of Lading"
    if "missing" in r:
        return "Locate the missing document"
    if "scanned" in r or "ocr" in r:
        return "Confirm OCR values from a scanned document"
    if "unreadable" in r or "open" in r:
        return "Obtain a readable copy of the document"
    if "not the expected" in r:
        return "Request the correct document"
    return "Review this email"


# ------------------------------------------------------------------ review

def resolve_case(store: Store, case_id: str, reviewer: str, decision: str, comment: str = "",
                 corrected_value: str | None = None) -> dict:
    reviewer = (reviewer or "").strip()
    if not (2 <= len(reviewer) <= 60):
        raise ReviewError("Reviewer name is required (2-60 characters).")
    case = store.get("reviewCases", case_id)
    if not case:
        raise ReviewError("Review case not found.")
    eid = case["emailId"]
    comp = store.get("comparisons", eid) or {}
    eff, status, detail = apply_decision(comp.get("effectiveResult") or {}, case, decision, reviewer,
                                         (comment or "").strip()[:500], corrected_value)
    ts = now_iso()
    if comp:
        corrections = comp.get("corrections") or []
        corrections.append({"at": ts, "reviewer": reviewer, "decision": decision, "field": case.get("field"),
                            "correctedValue": corrected_value, "comment": comment})
        store.update("comparisons", eid, {"effectiveResult": eff, "corrections": corrections, "updatedAt": ts})
    history = (case.get("history") or []) + [{"at": ts, "event": decision, "by": reviewer, "comment": comment}]
    store.update("reviewCases", case_id, {"status": status, "reviewerName": reviewer, "reviewerDecision": decision,
                                          "reviewerComment": comment, "correctedValue": corrected_value,
                                          "reviewedAt": ts, "history": history})
    email_update = {"updatedAt": ts}
    if comp:
        email_update.update(_summary_fields(eff))
    if decision == "change_category":
        email_update.update(category=corrected_value, classificationReason=f"Set by reviewer {reviewer}",
                            classificationSource="reviewer")
    open_left = [c for c in store.list("reviewCases", where=("emailId", eid)) if c.get("status") == "open"]
    email_update.update(openCases=len(open_left), needsHumanReview=bool(open_left))
    if not open_left and (store.get("emails", eid) or {}).get("processingStatus") == "needs_review":
        email_update["processingStatus"] = "completed"
    store.update("emails", eid, email_update)
    audit(store, eid, "review_decision", detail, actor=reviewer)
    return {"case": store.get("reviewCases", case_id), "effectiveResult": eff}


# ------------------------------------------------------------------ read models

def email_detail(store: Store, email_id: str) -> dict | None:
    e = store.get("emails", email_id)
    if not e:
        return None
    docs = [d for d in store.list("documents", where=("emailId", email_id))]
    cases = store.list("reviewCases", where=("emailId", email_id))
    logs = sorted(store.list("auditLogs", where=("emailId", email_id)), key=lambda x: x.get("createdAt") or "")
    return {"email": e, "documents": docs, "comparison": store.get("comparisons", email_id),
            "reviewCases": cases, "auditLogs": logs}


def list_cases(store: Store, status: str | None = "open") -> list[dict]:
    cases = store.list("reviewCases", where=("status", status) if status else None)
    emails = {e["emailId"]: e for e in store.list("emails")}
    pr = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for c in cases:
        e = emails.get(c["emailId"], {})
        c["subject"], c["shipmentRef"], c["category"] = e.get("subject"), e.get("shipmentRef"), e.get("category")
        c["attachments"] = e.get("attachments", [])
    return sorted(cases, key=lambda c: (pr.get(c.get("priority"), 4), c.get("createdAt") or ""))


def stats(store: Store) -> dict:
    emails = store.list("emails")
    cat = collections.Counter(e.get("category") or "unprocessed" for e in emails)
    reality = collections.Counter(e.get("realityStatus") for e in emails if e.get("category") == "document_comparison")
    failures = sum(1 for e in emails if e.get("processingStatus") == "failed_retry_available")
    queued = sum(1 for e in emails if e.get("processingStatus") in (None, "queued"))
    field_mm = collections.Counter(f for e in emails for f in (e.get("mismatchedFields") or []))
    risk = collections.Counter(e.get("riskLevel") for e in emails if e.get("riskLevel"))
    reasons = collections.Counter(e.get("reviewReason") for e in emails
                                  if e.get("realityStatus") in ("unresolved", "incomplete") and e.get("reviewReason"))
    confs = [e["overallConfidence"] for e in emails if isinstance(e.get("overallConfidence"), (int, float))
             and e.get("realityStatus") in ("converged", "diverging")]
    open_cases = [c for c in store.list("reviewCases") if c.get("status") == "open"]
    comp = cat.get("document_comparison", 0)
    s = {
        "total": len(emails), "categories": dict(cat), "comparisons": comp,
        "clear": reality.get("converged", 0), "mismatches": reality.get("diverging", 0),
        "unresolved": reality.get("unresolved", 0) + reality.get("incomplete", 0),
        "incomplete": reality.get("incomplete", 0), "failures": failures, "queued": queued,
        "mismatchByField": {f: field_mm.get(f, 0) for f in FIELDS}, "risk": dict(risk),
        "reviewReasons": dict(reasons), "openCases": len(open_cases),
        "avgConfidence": round(sum(confs) / len(confs), 3) if confs else None,
    }
    s["briefing"] = _briefing(s)
    return s


def _briefing(s: dict) -> str:
    if not s["total"]:
        return "The inbox is empty. Load the dataset or upload an email to begin."
    parts = [f"{s['total']} emails in the inbox.", f"{s['comparisons']} are document-comparison requests."]
    parts.append(f"{s['clear']} shipment{'s are' if s['clear'] != 1 else ' is'} clear.")
    if s["mismatches"]:
        parts.append(f"{s['mismatches']} {'have' if s['mismatches'] != 1 else 'has'} confirmed mismatches"
                     f" that need attention.")
    if s["unresolved"]:
        why = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(s["reviewReasons"].items(), key=lambda x: -x[1]))
        parts.append(f"{s['unresolved']} need human review" + (f" ({why})." if why else "."))
    if s["failures"]:
        parts.append(f"{s['failures']} failed processing and can be retried.")
    if s["queued"]:
        parts.append(f"{s['queued']} are still queued.")
    return " ".join(parts)


def submission(store: Store, sample: dict | None = None) -> dict:
    results = []
    for e in store.list("emails"):
        comp = store.get("comparisons", e["emailId"]) if e.get("category") == "document_comparison" else None
        results.append({"emailId": e["emailId"], "classification": {"category": e.get("category")},
                        "processingStatus": e.get("processingStatus"),
                        "effectiveComparison": (comp or {}).get("effectiveResult")})
    return build_submission(results, sample)


def report(store: Store, email_id: str) -> dict | None:
    d = email_detail(store, email_id)
    if not d:
        return None
    e, comp = d["email"], (d["comparison"] or {})
    eff = comp.get("effectiveResult") or {}
    reviews = [c for c in d["reviewCases"] if c.get("reviewerDecision")]
    action = {"match": "Approve the draft BL for release.",
              "mismatch": "Ask the carrier to amend the draft BL for: " +
                          ", ".join(FIELD_DISPLAY[f] for f in eff.get("mismatchedFields", [])) + ".",
              "needs_review": "Resolve the open review items before approving the draft BL.",
              "incomplete": "Obtain the missing or correct documents, then re-run the check."}.get(eff.get("status"), "-")
    return {
        "generatedAt": now_iso(), "emailId": email_id, "shipmentRef": e.get("shipmentRef"),
        "subject": e.get("subject"), "sender": e.get("sender"), "receivedAt": e.get("receivedAt"),
        "category": e.get("category"), "siFile": eff.get("siFile"), "blFile": eff.get("blFile"),
        "status": eff.get("status"), "statusLabel": eff.get("statusLabel"),
        "realityStatus": REALITY.get(eff.get("status")), "headline": eff.get("headline"),
        "riskLevel": eff.get("riskLevel"), "riskReason": eff.get("riskReason"),
        "overallConfidence": eff.get("overallConfidence"), "mismatchCount": eff.get("mismatchCount", 0),
        "needsHumanReview": bool(e.get("openCases")), "fields": eff.get("fields") or {},
        "recommendedAction": action, "reviews": reviews, "corrections": comp.get("corrections", []),
        "decisions": DECISIONS,
    }
