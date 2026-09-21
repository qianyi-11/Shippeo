"""Gemini document extraction (text, PDF, DOCX, images, scans). Evidence-first, no guessing."""
from __future__ import annotations

from . import gemini
from .fields import FIELDS, LABELS

_LABEL_TEXT = "\n".join(f"- {f}: " + ", ".join(LABELS[f]) for f in FIELDS)

EXTRACT_SYSTEM = f"""You are an evidence-first information extractor for shipping documents.
First decide the document type: SI (Shipping Instruction, also titled "BL Instruction" or "Bill of Lading Instruction"), BL (a Bill of Lading, including a draft B/L), OTHER (e.g. commercial invoice, packing list, certificate) or unknown.
Extract ONLY these 7 fields: {", ".join(FIELDS)}.

Equivalent labels (case-insensitive):
{_LABEL_TEXT}

Rules:
- Read the document visually and semantically, including tables and irregular layouts. If it is scanned, read it carefully with visual understanding.
- Never guess. Never create values that are not explicitly in the document.
- raw_value: copy the value EXACTLY as written (same spelling, case and punctuation). For party fields include the full block (name and address lines, separated by newlines).
- party_name (shipper/consignee/notify_party only): the company name alone, copied exactly.
- If notify_party says "SAME AS CONSIGNEE" or similar, return that text verbatim.
- source_label: the label exactly as written in the document.
- evidence: a short verbatim snippet containing the label and value.
- page: page number if known, otherwise null.
- confidence: 0.0-1.0 for how clearly the value is readable and correctly attributed.
- container_count: if several lines are given (e.g. "2 x 20GP + 1 x 40HC"), copy them verbatim in raw_value; put the total in normalized_candidate only if unambiguous.
- gross_weight_kg: copy number and unit exactly; put kilograms in normalized_candidate only if number and unit are unambiguous; set weight_kind to GROSS, NET or UNKNOWN. Never report a NET weight as gross.
- If a value is unreadable, missing or ambiguous: raw_value null (or the partial text), normalized_candidate null, and explain in uncertainty_reason.
- Do not compare this document with any other document.
Return JSON only."""

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "raw_value": {"type": ["string", "null"]},
        "party_name": {"type": ["string", "null"]},
        "normalized_candidate": {"type": ["string", "number", "null"]},
        "source_label": {"type": ["string", "null"]},
        "evidence": {"type": ["string", "null"]},
        "page": {"type": ["integer", "null"]},
        "confidence": {"type": "number"},
        "uncertainty_reason": {"type": ["string", "null"]},
        "weight_kind": {"type": ["string", "null"]},
    },
    "required": ["raw_value", "source_label", "evidence", "confidence", "uncertainty_reason"],
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": ["SI", "BL", "OTHER", "unknown"]},
        "document_confidence": {"type": "number"},
        "fields": {"type": "object", "properties": {f: _FIELD_SCHEMA for f in FIELDS},
                   "required": FIELDS},
        "document_uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["document_type", "document_confidence", "fields", "document_uncertainties"],
}


def extract(text: str | None = None, file_bytes: bytes | None = None, mime_type: str | None = None,
            file_name: str | None = None) -> gemini.GeminiResult:
    prompt = f"File name: {file_name or 'unknown'}\n\n"
    if text is not None:
        prompt += "Document text:\n<<<\n" + text + "\n>>>"
    else:
        prompt += "The document is attached."
    r = gemini.call_json(EXTRACT_SYSTEM, text=prompt, file_bytes=file_bytes, mime_type=mime_type,
                         schema=EXTRACT_SCHEMA)
    if r.ok:
        # Treat a NET weight as not-a-gross-weight regardless of what the model put in raw_value
        gw = (r.data.get("fields") or {}).get("gross_weight_kg") or {}
        if (gw.get("weight_kind") or "").upper() == "NET":
            gw["uncertainty_reason"] = "Only a NET weight was found."
            gw["raw_value"] = None
    return r
