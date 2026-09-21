"""Deterministic label-based parser for SI/BL text (plain text, or xlsx/docx/pdf converted
by core.readers into 'Key: value' lines with indented continuation lines).

It is the second, independent extractor used to cross-check Gemini."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .fields import FIELDS, PARTY_FIELDS

# Ordered: first match wins. Patterns run on a cleaned key (lowercase, no brackets,
# ASCII only, single spaces).
_KEY_RULES: list[tuple[str, re.Pattern]] = [
    ("notify_party", re.compile(r"^(also )?notify( part(y|ies))?$|^notification party$")),
    ("consignee", re.compile(r"^(consignee|consigned to|to the order of|to order of|to order)$")),
    ("shipper", re.compile(r"^(shipper|exporter|shipped by|shipper ?/ ?exporter)$")),
    ("port_of_loading", re.compile(r"^(port of loading|load(ing)? port|pol|port of load|place of loading)$")),
    ("port_of_discharge", re.compile(r"^(port of discharg(e|ing)|discharg(e|ing) port|pod|place of discharge)$")),
    ("container_count", re.compile(r"^(total )?(no\.? of|number of|qty of|quantity of)? ?containers?"
                                   r"( count| quantity| qty)?( or packages)?$|^total containers$|^container count$|"
                                   r"^no\.? of containers?( or packages)?$|^cntrs?$")),
    ("gross_weight_kg", re.compile(r"^(total )?(gross (weight|wt\.?)|g\.? ?w\.?)( kgs?)?$")),
]

_LABEL_START = re.compile(
    r"^(?P<key>(also )?notify( party)?|notification party|consignee|consigned to|to the order of|shipper(/exporter)?|"
    r"exporter|shipped by|port of loading|load port|loading port|pol|port of discharge|discharge port|pod|"
    r"(total )?no\.? of containers( or packages)?|total containers|container count|(total )?gross (weight|wt\.?))"
    r"(?P<paren>(\s*\([^)]*\))*)\s+(?P<val>\S.*)$", re.I)


def clean_key(key: str) -> str:
    k = re.sub(r"\([^)]*\)", " ", key)            # drop (POL), (KG), (Non-Negotiable), (发货人)
    k = re.sub(r"[^\x00-\x7f]+", " ", k)          # drop non-ASCII (e.g. 毛重)
    k = k.lower().replace("_", " ")
    k = re.sub(r"[:;]+", " ", k)
    k = re.sub(r"\s+", " ", k).strip(" .-")
    return k


def field_for_key(key: str) -> str | None:
    k = clean_key(key)
    if not k or re.search(r"\bnet\b", k):
        return None
    # "Notify Party/Intermediate Consignee", "Shipper/Exporter": try the whole key, then the first part
    for cand in (k, k.split("/")[0].strip()):
        for f, rx in _KEY_RULES:
            if rx.search(cand):
                return f
    return None


@dataclass
class RuleHit:
    field: str
    raw_value: str | None
    source_label: str
    line_number: int  # 1-based
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def match_label(line: str) -> tuple[str, str, str] | None:
    """Return (field, label_as_written, value_on_line) if an unindented line starts with a label."""
    if not line.strip() or line[:1].isspace():
        return None
    if ":" in line:
        key, _, rest = line.partition(":")
        if len(key) <= 70:
            f = field_for_key(key)
            if f:
                return f, key.strip(), rest.strip()
    m = _LABEL_START.match(line.strip())
    if m:
        key = (m.group("key") + (m.group("paren") or "")).strip()
        f = field_for_key(key)
        if f:
            return f, key, m.group("val").strip()
    return None


def _is_label_like(line: str) -> bool:
    """Any 'Key: value' line (even an unknown key) ends a party block."""
    return bool(line.strip()) and not line[:1].isspace() and bool(re.match(r"^[^:]{1,60}:", line))


def parse_document(text: str) -> dict:
    """Return {field: {"hits": [...], "value": hit|None, "ambiguous": bool}}."""
    lines = text.splitlines()
    hits: dict[str, list[RuleHit]] = {f: [] for f in FIELDS}
    i = 0
    while i < len(lines):
        m = match_label(lines[i])
        if not m:
            i += 1
            continue
        field, label, rest = m
        block = [rest] if rest else []
        j = i + 1
        if field in PARTY_FIELDS:
            while j < len(lines) and lines[j].strip() and not match_label(lines[j]) \
                    and (lines[j][:1].isspace() or not _is_label_like(lines[j])):
                block.append(lines[j].strip())
                j += 1
        if not block:  # value on the next indented / non-label line
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and not match_label(lines[k]) and not _is_label_like(lines[k]):
                block.append(lines[k].strip())
                j = k + 1
        value = "\n".join(b for b in block if b) or None
        evidence = "\n".join(l.rstrip() for l in lines[i:max(j, i + 1)])
        hits[field].append(RuleHit(field, value, label, i + 1, evidence.strip()))
        i = max(j, i + 1)

    out = {}
    for f in FIELDS:
        hs = hits[f]
        chosen, ambiguous = None, False
        if hs:
            totals = [h for h in hs if "total" in h.source_label.lower()]
            pool = totals or hs
            distinct = {re.sub(r"\s+", " ", (h.raw_value or "")).strip().lower() for h in pool}
            chosen = pool[0]
            ambiguous = len(distinct) > 1
        out[f] = {"hits": [h.to_dict() for h in hs],
                  "value": chosen.to_dict() if chosen else None,
                  "ambiguous": ambiguous}
    return out


# ------------------------------------------------------------------ document type

_SI_HEAD = re.compile(r"shipping\s*instructions?|(bill\s*of\s*lading|b/?l)\s*instructions?|\bS\.?I\.?\b", re.I)
_BL_HEAD = re.compile(r"bill\s*of\s*lading|\bB/L\b|\bdraft\s*BL\b|\bsea\s*waybill", re.I)
_OTHER_HEAD = re.compile(r"commercial\s*invoice|packing\s*list|proforma|debit\s*note|credit\s*note|"
                         r"certificate\s*of\s*origin|booking\s*confirmation|arrival\s*notice|"
                         r"not\s+a\s+(shipping\s*instruction|bill\s*of\s*lading)", re.I)


def detect_doc_type(text: str) -> tuple[str, str]:
    """From content: SI | BL | OTHER | unknown, with the heading that decided it."""
    head_lines = [l.strip() for l in text.splitlines() if l.strip()][:6]
    head = "\n".join(head_lines)
    other = _OTHER_HEAD.search(text)
    if other and not re.search(r"shipper|consignee", head, re.I):
        return "OTHER", other.group(0)
    for l in head_lines:
        if _OTHER_HEAD.search(l):
            return "OTHER", l
        if re.search(r"instruction", l, re.I) and _SI_HEAD.search(l):
            return "SI", l
        if _BL_HEAD.search(l) and not re.search(r"no\.?|number", l, re.I):
            return "BL", l
    return "unknown", head_lines[0] if head_lines else ""


def guess_role(name: str = "", text: str = "") -> tuple[str, str]:
    """Role from filename (…_SI.txt / …_BL.pdf), else from the document heading."""
    base = re.sub(r"[_\-.]+", " ", name or "")
    si_n = bool(re.search(r"\bSI\b|shipping instruction", base, re.I))
    bl_n = bool(re.search(r"\bB ?L\b|\bBOL\b|bill of lading", base, re.I))
    if si_n != bl_n:
        return ("SI" if si_n else "BL"), f"filename '{name}'"
    if text:
        t, why = detect_doc_type(text)
        if t in ("SI", "BL"):
            return t, f"document heading '{why}'"
    return "unknown", "no clear SI/BL signal in filename or heading"
