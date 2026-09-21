"""Deterministic SI-vs-BL comparison engine. Gemini never decides the outcome here."""
from __future__ import annotations

from .fields import FIELDS, FIELD_DISPLAY, MAJOR_FIELDS, MATCH_STATES, NO_MISMATCH_TEXT, PORT_FIELDS, STATUS_LABELS
from .normalize import collapse_ws, norm_text
from .verify import FieldValue


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,}" if isinstance(v, int) else f"{v:,.3f}".rstrip("0").rstrip(".")
    return collapse_ws(str(v))


def _q(fv: FieldValue) -> str:
    lbl = fv.source_label or "?"
    return f"{lbl}: {collapse_ws(fv.raw_value or '')}"


def _why_missing(fv: FieldValue) -> str:
    if fv.issue == "missing_value" and fv.label_found:
        return "was left blank" + (f" ({fv.uncertainty.split('(', 1)[-1].rstrip('.')}" if fv.uncertainty and "(" in fv.uncertainty else "")
    return "could not be read" if fv.label_found else "was not found"


def compare_field(field: str, si: FieldValue, bl: FieldValue) -> dict:
    name = FIELD_DISPLAY[field]
    res = {
        "field": field,
        "siOriginal": si.raw_value, "blOriginal": bl.raw_value,
        "siNormalized": si.normalized, "blNormalized": bl.normalized,
        "siLabel": si.source_label, "blLabel": bl.source_label,
        "siEvidence": si.evidence, "blEvidence": bl.evidence,
        "siNote": si.normalization_note, "blNote": bl.normalization_note,
        "siLevel": si.level, "blLevel": bl.level,
        "confidence": round(min(si.confidence or 0, bl.confidence or 0), 2),
        "needsReview": False,
        "issue": si.issue or bl.issue,
    }

    def done(state, explanation, review=False):
        res.update(state=state, explanation=explanation, needsReview=review or res["needsReview"])
        return res

    # 1. missing
    if si.raw_value is None and bl.raw_value is None:
        return done("missing_in_si", f"{name} was not found in either document.", True)
    if si.raw_value is None:
        st = "unreadable" if si.label_found and si.issue != "missing_value" else "missing_in_si"
        return done(st, f"{name} {_why_missing(si)} in the SI. "
                        f"BL records {_q(bl)}. Not treated as a match or a mismatch.", True)
    if bl.raw_value is None:
        st = "unreadable" if bl.label_found and bl.issue != "missing_value" else "missing_in_bl"
        return done(st, f"{name} {_why_missing(bl)} in the BL. "
                        f"SI records {_q(si)}. Not treated as a match or a mismatch.", True)

    # 2. low confidence -> never a confirmed mismatch
    if si.level == "low" or bl.level == "low":
        side = "SI" if si.level == "low" else "BL"
        why = (si if side == "SI" else bl).uncertainty or "low extraction confidence"
        exact = collapse_ws(si.raw_value).lower() == collapse_ws(bl.raw_value).lower()
        if exact:
            return done("ambiguous_needs_review",
                        f"SI and BL text look identical ({_q(si)}), but the {side} value is uncertain: "
                        f"{why}. Confirm before treating it as a match.", True)
        return done("unreadable" if (si if side == "SI" else bl).normalized is None else "ambiguous_needs_review",
                    f"SI records {_q(si)}; BL records {_q(bl)}. The {side} value is uncertain ({why}), "
                    f"so this is NOT reported as a mismatch. Human confirmation required.", True)

    # 3. normalisation failed on one side -> try to settle with the other side's value
    if si.normalized is None or bl.normalized is None:
        amb, other = (si, bl) if si.normalized is None else (bl, si)
        side = "SI" if amb is si else "BL"
        if amb.candidates and other.normalized in amb.candidates:
            return done("normalized_match",
                        f"The {side} value '{collapse_ws(amb.raw_value)}' is ambiguous ({amb.normalization_note}) "
                        f"but one reading equals the other document's value ({_fmt(other.normalized)}). "
                        f"Result: normalized match (please glance at it).", True)
        return done("ambiguous_needs_review",
                    f"The {side} value '{collapse_ws(amb.raw_value)}' could not be normalised safely: "
                    f"{amb.normalization_note} Human confirmation required.", True)

    medium = "medium" in (si.level, bl.level)
    # ports: when BOTH sides carry a UN/LOCODE or a qualifier, those decide
    if field in PORT_FIELDS:
        sc, bc = (si.extra or {}).get("code"), (bl.extra or {}).get("code")
        sq, bq = (si.extra or {}).get("qualifier"), (bl.extra or {}).get("qualifier")
        if sc and bc and sc != bc:
            return done("mismatch_confirmed",
                        f"SI records {_q(si)}; BL records {_q(bl)}. The UN/LOCODEs differ "
                        f"({sc.upper()} vs {bc.upper()}). Result: mismatch.", medium)
        if sq and bq and norm_text(sq) != norm_text(bq):
            return done("mismatch_confirmed",
                        f"SI records {_q(si)}; BL records {_q(bl)}. The terminal/qualifier differs "
                        f"('{sq}' vs '{bq}'). Result: mismatch.", medium)
        if sc and bc and sc == bc and si.normalized != bl.normalized:
            return done("normalized_match",
                        f"SI uses '{_q(si)}'. BL uses '{_q(bl)}'. Both carry UN/LOCODE {sc.upper()}. "
                        f"Result: normalized match.")
    # 4. exact
    if collapse_ws(si.raw_value) == collapse_ws(bl.raw_value):
        return done("match_confirmed", f"SI and BL both record {_q(si).split(': ', 1)[1]}. Result: match.")
    # 5. normalised
    if si.normalized == bl.normalized:
        return done("normalized_match",
                    f"SI uses '{_q(si)}'. BL uses '{_q(bl)}'. The labels map to the same field and the values "
                    f"are equal after normalisation ({_fmt(si.normalized)}). Result: normalized match.")
    # 6. mismatch
    conf_txt = "Both values were verified in their documents with high confidence." if not medium else \
        "At least one value has medium confidence, so a reviewer should confirm."
    return done("mismatch_confirmed",
                f"SI records {_q(si)}. BL records {_q(bl)}. Normalised: SI {_fmt(si.normalized)} vs "
                f"BL {_fmt(bl.normalized)}. {conf_txt} Result: mismatch.", medium)


def risk_for(field_results: dict, status: str, incomplete_reason: str | None = None) -> tuple[str, str]:
    if status == "incomplete":
        return "critical", incomplete_reason or "SI or BL is missing, so verification cannot happen."
    mism = [f for f, r in field_results.items() if r["state"] == "mismatch_confirmed"]
    major = [f for f in mism if f in MAJOR_FIELDS]
    unread = [f for f, r in field_results.items() if r["state"] in ("unreadable", "missing_in_si", "missing_in_bl")]
    if len(major) >= 2:
        return "critical", "Multiple major fields differ: " + ", ".join(FIELD_DISPLAY[f] for f in major) + "."
    if len(unread) >= 4:
        return "critical", "Most required fields could not be read; no dependable result."
    if major:
        return "high", f"Confirmed discrepancy in {FIELD_DISPLAY[major[0]]} (a cargo/route field)."
    if mism:
        return "medium", "Party name differs: " + ", ".join(FIELD_DISPLAY[f] for f in mism) + "."
    if status == "needs_review":
        return "medium", "One or more fields are uncertain and need confirmation."
    return "low", "All fields match (formatting differences only)."


def compare_shipment(si_fields: dict[str, FieldValue], bl_fields: dict[str, FieldValue]) -> dict:
    fields = {f: compare_field(f, si_fields[f], bl_fields[f]) for f in FIELDS}
    return summarize(fields)


def summarize(fields: dict[str, dict]) -> dict:
    """Shipment-level result from the 7 field results (also used after reviewer corrections)."""
    mismatched = [f for f in FIELDS if fields[f]["state"] == "mismatch_confirmed"]
    unresolved = [f for f in FIELDS if fields[f]["state"] not in MATCH_STATES | {"mismatch_confirmed"}]
    needs_review = any(r["needsReview"] for r in fields.values())
    if mismatched:
        status = "mismatch"
    elif unresolved:
        status = "needs_review"
    else:
        status = "match"
    risk, risk_reason = risk_for(fields, status)
    if status == "match":
        headline = NO_MISMATCH_TEXT
    elif status == "mismatch":
        headline = "Mismatch detected at " + ", ".join(FIELD_DISPLAY[f] for f in mismatched) + "."
    else:
        headline = "Human confirmation required before verification can be completed."
    reasons = [f"{FIELD_DISPLAY[f]}: {fields[f]['explanation']}" for f in FIELDS if fields[f]["needsReview"]]
    return {
        "status": status,
        "statusLabel": STATUS_LABELS[status][0],
        "themeLabel": STATUS_LABELS[status][1],
        "headline": headline,
        "mismatch": bool(mismatched),
        "mismatchedFields": mismatched,
        "mismatchCount": len(mismatched),
        "unresolvedFields": unresolved,
        "needsHumanReview": needs_review or bool(unresolved),
        "reviewReasons": reasons,
        "overallConfidence": round(min(r["confidence"] for r in fields.values()), 2),
        "riskLevel": risk,
        "riskReason": risk_reason,
        "fields": fields,
    }


def incomplete_result(reason: str) -> dict:
    return {
        "status": "incomplete",
        "statusLabel": STATUS_LABELS["incomplete"][0],
        "themeLabel": STATUS_LABELS["incomplete"][1],
        "headline": f"Comparison cannot begin because {reason}.",
        "mismatch": False,
        "mismatchedFields": [],
        "mismatchCount": 0,
        "unresolvedFields": list(FIELDS),
        "needsHumanReview": True,
        "reviewReasons": [reason[0].upper() + reason[1:] + "."],
        "overallConfidence": 0.0,
        "riskLevel": "critical",
        "riskReason": f"{reason[0].upper() + reason[1:]}; verification is blocked.",
        "fields": {},
    }
