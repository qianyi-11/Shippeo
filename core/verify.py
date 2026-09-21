"""Merge the two extractors (rule parser + Gemini) into one value per field, with an
evidence-backed confidence level that does not rely on Gemini's self-score alone.

HIGH   = evidence verified AND (extractors agree OR (rule parser found nothing AND gemini >= 0.90))
MEDIUM = evidence verified but extractors disagree, or gemini confidence 0.70–0.89,
         or only the rule parser ran (offline mode) and its hit is ambiguous
LOW    = not verified, or gemini < 0.70, or the label exists but no value could be read
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field as dc_field

from .fields import FIELDS
from .normalize import normalize_field, collapse_ws, is_same_as_consignee, Norm

LEVEL_SCORE = {"high": 0.95, "medium": 0.8, "low": 0.5}


@dataclass
class FieldValue:
    field: str
    raw_value: str | None = None
    source_label: str | None = None
    evidence: str | None = None
    page: int | None = None
    normalized: object | None = None
    normalization_note: str = ""
    candidates: list = dc_field(default_factory=list)
    level: str = "low"               # high | medium | low
    confidence: float = 0.0          # numeric, used in UI and overall confidence
    label_found: bool = False
    evidence_verified: bool = False
    extractors_agree: bool | None = None
    gemini_confidence: float | None = None
    rule_value: str | None = None
    gemini_value: str | None = None
    uncertainty: str | None = None
    reference: str | None = None     # e.g. "same_as_consignee"
    issue: str | None = None         # missing_value | unreadable (reason code for review)
    extra: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _squash(s: str) -> str:
    return collapse_ws(s).lower()


def evidence_in_text(value: str | None, text: str | None) -> bool:
    """True when the value (whitespace/case-insensitive) literally appears in the text."""
    if not value or not text:
        return False
    v, t = _squash(value), _squash(text)
    if v in t:
        return True
    # multi-line party block: accept if every line is present
    lines = [_squash(l) for l in value.splitlines() if l.strip()]
    return len(lines) > 1 and all(l in t for l in lines)


_GARBLED = re.compile(r"\.{3}|…|\?{2,}|�|#{3,}|\[illegible\]|\[unreadable\]|\bx{4,}\b", re.I)
_PLACEHOLDER = re.compile(r"^\s*(n/?a|nil|none|null|tba|tbc|tbd|to be (advised|confirmed)|-+|_+|\.+|\?)\s*"
                          r"(mts?|kgs?|kg|containers?)?\s*$", re.I)


def is_placeholder(value: str | None) -> bool:
    """Blank-form values like N/A, TBA, ______ mean the value is missing, not unreadable."""
    return bool(value) and bool(_PLACEHOLDER.match(value.replace("\n", " ")))


def _looks_garbled(value: str | None) -> bool:
    return bool(value) and bool(_GARBLED.search(value))


def _norm_eq(field: str, a: str | None, b: str | None, label_a=None, label_b=None) -> bool:
    if not a or not b:
        return False
    na, nb = normalize_field(field, a, label_a), normalize_field(field, b, label_b)
    return na.value is not None and na.value == nb.value


def merge_field(field: str, rule: dict | None, gem: dict | None, text: str | None,
                gemini_ran: bool) -> FieldValue:
    """rule: parse_document()[field]; gem: gemini fields[field] dict (may be None)."""
    rv = (rule or {}).get("value") or {}
    r_raw = rv.get("raw_value")
    r_amb = bool((rule or {}).get("ambiguous"))
    g_raw = (gem or {}).get("raw_value")
    g_conf = (gem or {}).get("confidence")
    fv = FieldValue(field=field, rule_value=r_raw, gemini_value=g_raw, gemini_confidence=g_conf)
    fv.label_found = bool(rv) or bool((gem or {}).get("source_label"))
    if is_placeholder(r_raw) or (not r_raw and is_placeholder(g_raw)):
        fv.issue = "missing_value"
        fv.uncertainty = f"Label present but the value is blank/placeholder ('{(r_raw or g_raw).strip()}')."
        fv.evidence = rv.get("evidence") or (gem or {}).get("evidence")
        fv.source_label = rv.get("source_label") or (gem or {}).get("source_label")
        return fv
    if is_placeholder(g_raw):
        g_raw = None

    # choose the value to carry forward
    if g_raw and r_raw:
        fv.extractors_agree = _norm_eq(field, g_raw, r_raw, gem.get("source_label"), rv.get("source_label"))
        # prefer the rule value when they agree (exact text from the document)
        use_rule = fv.extractors_agree or not evidence_in_text(g_raw, text)
    elif r_raw:
        fv.extractors_agree = False if gemini_ran else None
        use_rule = True
    elif g_raw:
        fv.extractors_agree = False if rule is not None and text else None
        use_rule = False
    else:
        fv.uncertainty = (gem or {}).get("uncertainty_reason") or (
            "Label found but value could not be read." if fv.label_found else "Field not found.")
        fv.issue = "unreadable" if fv.label_found and (gem or {}).get("uncertainty_reason") else "missing_value"
        return fv

    if use_rule:
        fv.raw_value, fv.source_label, fv.evidence = r_raw, rv.get("source_label"), rv.get("evidence")
    else:
        fv.raw_value, fv.source_label = g_raw, gem.get("source_label")
        fv.evidence, fv.page = gem.get("evidence"), gem.get("page")

    fv.evidence_verified = evidence_in_text(fv.raw_value, text) if text else bool(g_raw and g_conf and g_conf >= 0.9)

    # confidence level
    if not fv.evidence_verified:
        fv.level = "low"
        fv.issue = "unreadable"
        fv.uncertainty = ("Value not found verbatim in the document text." if text else
                          "Scanned document: OCR confidence below 0.90, value cannot be confirmed.")
    elif _looks_garbled(fv.raw_value):
        fv.level = "low"
        fv.issue = "unreadable"
        fv.uncertainty = (gem or {}).get("uncertainty_reason") or \
            "Value contains illegible characters (e.g. '...', '?', '#')."
    elif g_raw and g_conf is not None and g_conf < 0.7:
        fv.level = "low"
        fv.issue = "unreadable"
        fv.uncertainty = (gem or {}).get("uncertainty_reason") or "Gemini confidence below 0.70."
    elif not gemini_ran:  # offline mode: rule parser only
        fv.level = "medium" if r_amb else "high"
        if r_amb:
            fv.uncertainty = "Label appears several times with different values."
    elif fv.extractors_agree:
        fv.level = "high" if (g_conf is None or g_conf >= 0.7) else "medium"
    elif not r_raw and g_conf is not None and g_conf >= 0.9:
        fv.level = "high"
    elif g_conf is not None and g_conf < 0.7:
        fv.level = "low"
        fv.uncertainty = (gem or {}).get("uncertainty_reason") or "Gemini confidence below 0.70."
    else:
        fv.level = "medium"
        fv.uncertainty = "The rule parser and Gemini disagree." if (r_raw and g_raw) else \
            "Only one extractor found this value."
    if r_amb and fv.level == "high":
        fv.level = "medium"
        fv.uncertainty = "Label appears several times with different values."

    if is_same_as_consignee(fv.raw_value) and field == "notify_party":
        fv.reference = "same_as_consignee"
    else:
        n: Norm = normalize_field(field, fv.raw_value, fv.source_label)
        fv.normalized, fv.normalization_note, fv.candidates = n.value, n.note, n.candidates
        fv.extra = n.extra
        if n.assumed and fv.level == "high":
            fv.level = "medium"
            fv.uncertainty = n.note
    fv.confidence = min(LEVEL_SCORE[fv.level], g_conf if g_conf is not None else 1.0) \
        if fv.level != "high" else max(LEVEL_SCORE["high"], g_conf or 0)
    return fv


def resolve_references(fields: dict[str, FieldValue]) -> None:
    """Resolve 'SAME AS CONSIGNEE' in notify_party to that document's consignee."""
    np_, cons = fields.get("notify_party"), fields.get("consignee")
    if np_ and np_.reference == "same_as_consignee":
        if cons and cons.normalized is not None:
            np_.normalized = cons.normalized
            np_.normalization_note = f"'{np_.raw_value}' resolved to this document's consignee " \
                                     f"('{collapse_ws(cons.raw_value or '')[:60]}')."
            np_.level = "high" if (np_.level == "high" and cons.level == "high") else "medium"
            np_.confidence = min(np_.confidence or 0.95, cons.confidence or 0.95)
        else:
            np_.normalization_note = "Refers to the consignee, but the consignee could not be read."
            np_.level = "low"


def build_document_fields(parsed_rules: dict | None, gemini: dict | None, text: str | None,
                          gemini_ran: bool) -> dict[str, FieldValue]:
    gfields = (gemini or {}).get("fields") or {}
    out = {f: merge_field(f, (parsed_rules or {}).get(f), gfields.get(f), text, gemini_ran)
           for f in FIELDS}
    resolve_references(out)
    return out
