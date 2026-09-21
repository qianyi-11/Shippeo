"""End-to-end processing for one email. Pure orchestration over core/ modules.
Storage-agnostic: the caller supplies read_attachment(att) -> bytes."""
from __future__ import annotations

import datetime as dt
import os
import traceback
from typing import Callable

from . import gemini
from .classify import classify
from .compare import compare_shipment, incomplete_result
from .extract_gemini import extract as gemini_extract
from .extract_rules import parse_document, guess_role, detect_doc_type
from .readers import read_any
from .fields import FIELDS
from .verify import build_document_fields

Reader = Callable[[dict], bytes]

# review (default): OCR results from image-only files are shown but always need human confirmation
# trust_ocr: compare OCR values like text values (still capped by the confidence rules)
SCANNED_POLICY = os.getenv("SCANNED_POLICY", "review").lower()

_ACTION_FOR = {
    "missing_attachment": "Ask the sender for the missing SI / draft BL.",
    "wrong_doc_type": "Ask the sender for the correct document (SI and draft BL).",
    "unreadable": "Open the original file, or request a readable copy.",
    "missing_value": "Ask the sender to complete the missing value.",
}


# ------------------------------------------------------------------ email adapter

def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def normalize_email(rec: dict) -> dict:
    """Map a dataset record to our internal shape. Adjust keys after inspecting the dataset."""
    atts_raw = _first(rec, "attachments", "files", default=[]) or []
    atts = []
    for a in atts_raw:
        if isinstance(a, str):
            atts.append({"name": a.replace("\\", "/").split("/")[-1], "path": a, "type": None})
        else:
            path = _first(a, "path", "file", "filename", "file_name", "name", "url")
            name = _first(a, "filename", "file_name", "name", default=None) or (path or "").split("/")[-1]
            atts.append({"name": name, "path": path, "type": _first(a, "content_type", "mime_type", "type"),
                         "raw": a})
    sender = _first(rec, "sender", "from", "from_address", default="")
    if isinstance(sender, dict):
        sender = _first(sender, "email", "address", "name", default=str(sender))
    return {
        "emailId": str(_first(rec, "email_id", "id", "emailId", "message_id")),
        "sender": sender,
        "subject": _first(rec, "subject", default=""),
        "body": _first(rec, "body", "text", "content", "body_text", default=""),
        "receivedAt": _first(rec, "received_at", "date", "timestamp", "sent_at", "receivedAt"),
        "attachments": atts,
        "raw": rec,
    }


def _rules_confident(parsed: dict) -> bool:
    """True when the label parser found all 7 fields once, with no placeholder values."""
    from .verify import is_placeholder
    for f in FIELDS:
        v = parsed.get(f) or {}
        hit = v.get("value") or {}
        if not hit.get("raw_value") or v.get("ambiguous") or is_placeholder(hit.get("raw_value")):
            return False
    return True


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ------------------------------------------------------------------ pipeline

def process_email(rec: dict, read_attachment: Reader, use_gemini: bool = True,
                  on_status: Callable[[str, str], None] | None = None) -> dict:
    email = normalize_email(rec) if "emailId" not in rec else rec
    use_gemini = use_gemini and gemini.available()
    audit: list[dict] = []

    def status(s: str, detail: str = ""):
        audit.append({"at": _now(), "status": s, "detail": detail})
        if on_status:
            on_status(s, detail)

    result = {"emailId": email["emailId"], "email": {k: v for k, v in email.items() if k != "raw"},
              "processingStatus": "queued", "audit": audit, "documents": {}, "comparison": None,
              "reviewCases": [], "errors": [], "geminiUsed": use_gemini}
    try:
        status("classifying")
        cls = classify(email, use_gemini=use_gemini)
        result["classification"] = cls
        status("classified", f"{cls['category']} ({cls['confidence']:.2f}) via {cls['source']}")
        if cls.get("needsHumanReview"):
            result["reviewCases"].append(_case(email, "classification",
                                               f"Classification uncertain: {cls['reason']}", "medium"))
        if cls["category"] != "document_comparison":
            result["processingStatus"] = "needs_review" if result["reviewCases"] else "completed"
            return result

        # ---- locate SI / BL
        status("locating_documents")
        docs = []
        for att in email["attachments"]:
            d = {"att": att, "text": None, "bytes": None, "mime": None, "kind": None, "error": None,
                 "role": "unknown", "roleReason": "", "contentType": "unknown", "rules": None, "gemini": None}
            try:
                d["bytes"] = read_attachment(att)
                rr = read_any(att["name"], d["bytes"])
                d.update(text=rr.text, mime=rr.mime, kind=rr.kind, readNote=rr.note)
            except Exception as e:  # noqa: BLE001
                d.update(kind="corrupt", error=f"Could not open attachment: {e}")
            d["role"], d["roleReason"] = guess_role(att["name"] or "", "")
            if d["text"]:
                d["contentType"], d["heading"] = detect_doc_type(d["text"])
            docs.append(d)

        # ---- read / OCR with Gemini (also classifies scanned documents)
        status("extracting")
        for d in docs:
            if d["kind"] == "text":
                d["rules"] = parse_document(d["text"])
            if not use_gemini or d["kind"] in ("corrupt", "unsupported"):
                continue
            if d["kind"] == "text" and d["contentType"] == "OTHER":
                continue  # wrong document type: no need to spend a Gemini call
            if gemini.MODE != "full" and d["kind"] == "text" and d["rules"] and _rules_confident(d["rules"]):
                continue  # smart mode: the rule parser read all 7 fields cleanly
            r = gemini_extract(text=d["text"], file_bytes=None if d["text"] else d["bytes"],
                               mime_type=d["mime"], file_name=d["att"]["name"])
            d["geminiRaw"] = r.raw_text
            if r.ok:
                d["gemini"] = r.data
                gt = r.data.get("document_type")
                if d["contentType"] == "unknown" and gt in ("SI", "BL", "OTHER"):
                    d["contentType"] = gt if (r.data.get("document_confidence") or 0) >= 0.7 else "unknown"
            else:
                d["error"] = f"Gemini extraction failed: {r.error}"
                result["errors"].append(d["error"])

        # ---- decide roles: content beats filename when the content is explicit
        for d in docs:
            if d["contentType"] in ("SI", "BL") and d["contentType"] != d["role"]:
                d["roleReason"] = f"content says {d['contentType']} (filename said {d['role']})"
                d["role"] = d["contentType"]
        for d in docs:
            result["documents"][d["att"]["name"]] = {
                "role": d["role"], "roleReason": d["roleReason"], "contentType": d["contentType"],
                "heading": d.get("heading"), "fileName": d["att"]["name"], "path": d["att"].get("path"),
                "kind": d["kind"], "readNote": d.get("readNote"), "text": d.get("text"),
                "rules": d.get("rules"), "gemini": d.get("gemini"), "geminiRaw": d.get("geminiRaw"),
                "error": d.get("error"),
            }

        usable = [d for d in docs if d["contentType"] != "OTHER"]
        si_docs = [d for d in usable if d["role"] == "SI"]
        bl_docs = [d for d in usable if d["role"] == "BL"]
        others = [d for d in docs if d["contentType"] == "OTHER"]
        problem, code = None, None
        if not email["attachments"]:
            problem, code = "no SI or draft BL is attached", "missing_attachment"
        elif others and (not si_docs or not bl_docs):
            o = others[0]
            problem = (f"'{o['att']['name']}' is a {o.get('heading') or 'different document'}, "
                       f"not the expected {'draft BL' if not bl_docs else 'SI'}")
            code = "wrong_doc_type"
        elif len(si_docs) > 1 and not bl_docs:
            problem, code = "both attachments are Shipping Instructions; the draft BL is missing", "wrong_doc_type"
        elif len(bl_docs) > 1 and not si_docs:
            problem, code = "both attachments are Bills of Lading; the SI is missing", "wrong_doc_type"
        elif not bl_docs:
            problem, code = "the draft BL attachment is missing", "missing_attachment"
        elif not si_docs:
            problem, code = "the Shipping Instruction (SI) attachment is missing", "missing_attachment"
        else:
            bad = [d for d in (si_docs[0], bl_docs[0]) if d["kind"] != "text" and not d.get("gemini")]
            if bad:
                b = bad[0]
                why = b.get("readNote") or b.get("error") or "file could not be read"
                if b["kind"] == "scanned" and not use_gemini:
                    why += " Gemini OCR is not configured."
                problem, code = f"the {b['role']} '{b['att']['name']}' is unreadable ({why})", "unreadable"
        if problem:
            result["comparison"] = incomplete_result(problem)
            result["comparison"]["reviewReason"] = code
            result["reviewCases"].append(_case(email, None, f"Comparison cannot begin because {problem}.",
                                               "critical", _ACTION_FOR.get(code, "Review the documents.")))
            result["processingStatus"] = "needs_review"
            status("needs_review", problem)
            return result

        si, bl = si_docs[0], bl_docs[0]

        status("normalizing")
        si_f = build_document_fields(si.get("rules"), si.get("gemini"), si.get("text"), bool(si.get("gemini")))
        bl_f = build_document_fields(bl.get("rules"), bl.get("gemini"), bl.get("text"), bool(bl.get("gemini")))
        result["documents"][si["att"]["name"]]["fields"] = {f: v.to_dict() for f, v in si_f.items()}
        result["documents"][bl["att"]["name"]]["fields"] = {f: v.to_dict() for f, v in bl_f.items()}

        status("comparing")
        cmp = compare_shipment(si_f, bl_f)
        cmp["siFile"], cmp["blFile"] = si["att"]["name"], bl["att"]["name"]
        scanned = [d for d in (si, bl) if d["kind"] == "scanned"]
        if scanned and SCANNED_POLICY == "review":
            # OCR-only values cannot be checked against a text layer: show them as a provisional
            # comparison, but a person must confirm before the result counts.
            names = ", ".join(d["att"]["name"] for d in scanned)
            cmp["provisional"] = True
            cmp["provisionalMismatches"] = cmp["mismatchedFields"]
            cmp.update(status="needs_review", mismatch=False, mismatchedFields=[], mismatchCount=0,
                       needsHumanReview=True, statusLabel="Needs review", themeLabel="Unresolved Reality",
                       headline="Scanned (image-only) document read by OCR: human confirmation required.",
                       reviewReason="unreadable")
            cmp["reviewReasons"].insert(0, f"{names} is image-only; OCR values are provisional.")
            result["comparison"] = cmp
            result["reviewCases"].append(_case(email, None, f"{names} is a scanned image; OCR values need confirmation.",
                                               "high", "Confirm the OCR values against the scan, or request a text copy."))
            result["processingStatus"] = "needs_review"
            status("needs_review", cmp["headline"])
            return result
        issues = [cmp["fields"][f]["issue"] for f in FIELDS
                  if cmp["fields"][f]["state"] not in ("match_confirmed", "normalized_match", "mismatch_confirmed")]
        cmp["reviewReason"] = ("unreadable" if "unreadable" in issues else "missing_value") if issues else None
        result["comparison"] = cmp
        for f in FIELDS:
            fr = cmp["fields"][f]
            if fr["needsReview"]:
                result["reviewCases"].append(_case(
                    email, f, fr["explanation"],
                    "high" if f in ("port_of_loading", "port_of_discharge", "container_count", "gross_weight_kg") else "medium",
                    f"Confirm the {f.replace('_', ' ')} using the original documents.", fr))
        result["processingStatus"] = "needs_review" if cmp["needsHumanReview"] else "completed"
        status(result["processingStatus"], cmp["headline"])
    except Exception as e:  # noqa: BLE001 — visible failure, never silent
        result["processingStatus"] = "failed_retry_available"
        result["errors"].append(f"{type(e).__name__}: {e}")
        result["traceback"] = traceback.format_exc()
        result["reviewCases"].append(_case(email, None, f"Processing failed: {e}", "critical",
                                           "Retry processing; if it fails again, check the attachment."))
        status("failed_retry_available", str(e))
    return result


def _case(email: dict, field: str | None, reason: str, priority: str,
          action: str = "Review and confirm the classification.", fr: dict | None = None) -> dict:
    c = {"emailId": email["emailId"], "field": field, "reason": reason, "priority": priority,
         "recommendedAction": action, "status": "open", "createdAt": _now()}
    if fr:
        c.update(siValue=fr.get("siOriginal"), blCandidateValue=fr.get("blOriginal"),
                 confidence=fr.get("confidence"),
                 evidence=[{"document": "SI", "snippet": fr.get("siEvidence")},
                           {"document": "BL", "snippet": fr.get("blEvidence")}])
    return c
