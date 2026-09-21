"""Human review decisions. Deterministic: a reviewer's correction is fed back through the same
normalisation and comparison code. The original AI output (systemResult) is never modified."""
from __future__ import annotations

import copy

from .compare import compare_field, summarize
from .fields import CATEGORIES, FIELD_DISPLAY, FIELDS
from .normalize import is_same_as_consignee, normalize_field
from .verify import FieldValue, LEVEL_SCORE

DECISIONS = {
    "confirm_system_result": "Confirm system result",
    "confirm_mismatch": "Confirm mismatch",
    "correct_si_value": "Correct SI value",
    "correct_bl_value": "Correct BL value",
    "formatting_only_difference": "Mark as formatting-only difference",
    "mark_unreadable": "Mark document unreadable",
    "request_updated_document": "Request updated document",
    "retry_extraction": "Retry extraction",
    "change_category": "Change email category",
    "dismiss": "Dismiss / close case",
}

FIELD_DECISIONS = {"confirm_mismatch", "correct_si_value", "correct_bl_value",
                   "formatting_only_difference", "mark_unreadable"}


class ReviewError(ValueError):
    pass


def _fv_from_result(field: str, fr: dict, side: str) -> FieldValue:
    """Rebuild one side of a field comparison from the stored field result."""
    raw = fr.get(f"{side}Original")
    fv = FieldValue(field=field, raw_value=raw, source_label=fr.get(f"{side}Label"),
                    evidence=fr.get(f"{side}Evidence"), level=fr.get(f"{side}Level") or "low",
                    label_found=bool(fr.get(f"{side}Label")))
    fv.confidence = LEVEL_SCORE.get(fv.level, 0.5)
    fv.issue = fr.get("issue") if raw is None else None
    if raw is not None:
        if field == "notify_party" and is_same_as_consignee(raw):
            fv.normalized, fv.normalization_note = fr.get(f"{side}Normalized"), fr.get(f"{side}Note") or ""
        else:
            n = normalize_field(field, raw, fv.source_label)
            fv.normalized, fv.normalization_note, fv.candidates, fv.extra = n.value, n.note, n.candidates, n.extra
    return fv


def _corrected_fv(field: str, value: str, reviewer: str, comment: str) -> FieldValue:
    n = normalize_field(field, value, None)
    return FieldValue(field=field, raw_value=value, source_label="Reviewer correction",
                      evidence=f"Corrected by {reviewer}" + (f": {comment}" if comment else ""),
                      normalized=n.value, normalization_note=n.note, candidates=n.candidates, extra=n.extra,
                      level="high", confidence=1.0, label_found=True, evidence_verified=True)


def apply_decision(effective: dict, case: dict, decision: str, reviewer: str, comment: str,
                   corrected_value: str | None, system: dict | None = None) -> tuple[dict, str, str]:
    """Return (new_effective_result, new_case_status, audit_detail)."""
    if decision not in DECISIONS:
        raise ReviewError(f"Unknown decision '{decision}'.")
    eff = copy.deepcopy(effective or {})
    field = case.get("field")
    if decision in FIELD_DECISIONS and field not in FIELDS:
        raise ReviewError(f"'{DECISIONS[decision]}' needs a field-level case.")
    if decision in ("correct_si_value", "correct_bl_value", "change_category") and not (corrected_value or "").strip():
        raise ReviewError("A corrected value is required for this decision.")

    by = f" (reviewer: {reviewer})"
    detail = f"{DECISIONS[decision]}{by}"
    status = "resolved"

    if decision in FIELD_DECISIONS:
        fields = eff.get("fields") or {}
        fr = fields.get(field)
        if not fr:
            raise ReviewError("This shipment has no field comparison to change.")
        name = FIELD_DISPLAY[field]
        if decision == "confirm_mismatch":
            fr.update(state="mismatch_confirmed", needsReview=False,
                      explanation=fr["explanation"] + f" Mismatch confirmed by {reviewer}.")
        elif decision == "formatting_only_difference":
            fr.update(state="normalized_match", needsReview=False,
                      explanation=fr["explanation"] + f" {reviewer} marked this as a formatting-only difference.")
        elif decision == "mark_unreadable":
            fr.update(state="unreadable", needsReview=True, issue="unreadable",
                      explanation=f"{name}: {reviewer} marked the source as unreadable.")
        else:
            side = "si" if decision == "correct_si_value" else "bl"
            si = _corrected_fv(field, corrected_value, reviewer, comment) if side == "si" else _fv_from_result(field, fr, "si")
            bl = _corrected_fv(field, corrected_value, reviewer, comment) if side == "bl" else _fv_from_result(field, fr, "bl")
            new = compare_field(field, si, bl)
            new["correctedBy"] = reviewer
            new["correctedSide"] = side.upper()
            new["originalValue"] = fr.get(f"{side}Original")
            fields[field] = new
            detail = f"{name}: {side.upper()} value corrected from '{fr.get(f'{side}Original')}' to " \
                     f"'{corrected_value}' -> {new['state']}{by}"
        keep = {k: eff.get(k) for k in ("siFile", "blFile") if k in eff}
        eff = {**summarize(fields), **keep}
        issues = [fields[f].get("issue") for f in FIELDS
                  if fields[f]["state"] not in ("match_confirmed", "normalized_match", "mismatch_confirmed")]
        eff["reviewReason"] = ("unreadable" if "unreadable" in issues else "missing_value") if issues else None
    elif decision == "confirm_system_result":
        if eff.get("provisional") and eff.get("fields"):
            # reviewer checked the OCR values against the scan: accept the provisional comparison
            keep = {k: eff.get(k) for k in ("siFile", "blFile") if k in eff}
            eff = {**summarize(eff["fields"]), **keep, "confirmedOcrBy": reviewer}
            detail = f"OCR values confirmed against the scan{by}"
    elif decision == "request_updated_document":
        status = "waiting_for_document"
    elif decision == "retry_extraction":
        status = "retrying"
    elif decision == "change_category":
        if corrected_value not in CATEGORIES:
            raise ReviewError(f"Category must be one of {CATEGORIES}.")
        detail = f"Category changed to {corrected_value}{by}"
    elif decision == "dismiss":
        status = "dismissed"
    if comment:
        detail += f" - {comment}"
    return eff, status, detail
