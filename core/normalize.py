"""Deterministic normalisation. Every function returns (value, note) where value is
None when the input cannot be normalised safely, and note explains what was done or why
it failed. Original values are never modified; callers keep them for display."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PARTY_COMPARE_MODE = os.getenv("PARTY_COMPARE_MODE", "name_only")  # or "full_block"

_ALIAS_PATH = Path(__file__).with_name("port_aliases.json")


@dataclass
class Norm:
    value: object | None
    note: str
    candidates: list = field(default_factory=list)  # possible values when ambiguous
    assumed: bool = False  # True when an assumption (e.g. unit) lowered certainty
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- text / parties

_SUFFIX_WORDS = {
    "limited": "ltd",
    "private": "pte",
    "pvt": "pte",
    "corporation": "corp",
    "incorporated": "inc",
    "company": "co",
    "berhad": "bhd",
    "sendirian": "sdn",
    "and": "&",
}


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def norm_text(s: str) -> str:
    """Lowercase, strip harmless punctuation, collapse spaces, unify company suffixes."""
    t = s.lower()
    t = t.replace("&amp;", "&")
    t = re.sub(r"[.,;:'\"`()\[\]]", " ", t)
    t = re.sub(r"(?<=\w)-(?=\w)", " ", t)
    t = re.sub(r"(?<=\w)/(?=\w)", " ", t)
    t = collapse_ws(t)
    words = [_SUFFIX_WORDS.get(w, w) for w in t.split(" ")]
    t = " ".join(words)
    # "b v" (from B.V.) -> "bv", "n v" -> "nv", "s a" -> "sa", "l l c" -> "llc", "g m b h" -> "gmbh"
    t = re.sub(r"\b([a-z]) ([a-z])(?: ([a-z]))?(?: ([a-z]))?\b",
               lambda m: "".join(g for g in m.groups() if g), t)
    return t


def party_name(raw: str) -> str:
    """Company name = first non-empty line of a party block."""
    for line in raw.splitlines():
        if line.strip():
            return line.strip()
    return raw.strip()


_SAME_AS = re.compile(r"^\s*(?:same\s+as|as\s+per|idem)\s+(?:the\s+)?consignee\b", re.I)


def is_same_as_consignee(raw: str | None) -> bool:
    return bool(raw) and bool(_SAME_AS.match(raw))


def normalize_party(raw: str, mode: str | None = None) -> Norm:
    mode = mode or PARTY_COMPARE_MODE
    if mode == "full_block":
        return Norm(norm_text(raw), "Compared full party block (lowercase, punctuation and suffixes unified).")
    name = party_name(raw)
    note = "Compared company name (first line)"
    if name != raw.strip():
        note += "; address lines ignored"
    return Norm(norm_text(name), note + "; lowercase, punctuation and suffixes unified.")


# ---------------------------------------------------------------- ports

def _load_aliases() -> dict[str, str]:
    try:
        data = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {k.lower(): v.lower() for k, v in data.get("aliases", {}).items()}


_ALIASES = _load_aliases()
_COUNTRY_SUFFIXES = {
    "sg", "singapore", "my", "malaysia", "nl", "netherlands", "the netherlands", "cn", "china",
    "de", "germany", "be", "belgium", "us", "usa", "united states", "gb", "uk", "united kingdom",
    "jp", "japan", "kr", "korea", "south korea", "th", "thailand", "vn", "vietnam", "id",
    "indonesia", "in", "india", "ae", "uae", "united arab emirates", "au", "australia", "hk",
    "hong kong", "tw", "taiwan", "ph", "philippines", "fr", "france", "es", "spain", "it", "italy",
}


def normalize_port(raw: str) -> Norm:
    """Canonical port = city name (before the first comma, bracket qualifiers removed),
    mapped through the alias table. The UN/LOCODE (e.g. MYPKG) and any qualifier such as
    '(WESTPORT)' are kept in extra so compare.py can use them when BOTH documents have them."""
    t = collapse_ws(raw).lower().rstrip(".")
    notes = ["Lowercase and spacing normalised"]
    codes = re.findall(r"\(([a-z]{2}\s?[a-z0-9]{3})\)", t)
    code = codes[-1].replace(" ", "") if codes else None
    compact = t.replace(" ", "")
    if not code and re.fullmatch(r"[a-z]{5}", compact):
        code = compact
    quals = [q.strip() for q in re.findall(r"\(([^)]*)\)", t) if q.replace(" ", "") != code]
    base = re.sub(r"\([^)]*\)", " ", t)
    city = collapse_ws(base.split(",")[0]) if "," in base else collapse_ws(base)
    if "," in base:
        notes.append("country part after the comma ignored")
    if quals:
        notes.append(f"qualifier '({quals[0]})' kept aside")
    if code:
        notes.append(f"UN/LOCODE {code.upper()} noted")
    city = city.replace(".", "").strip()
    if not city and code:
        city = _ALIASES.get(code, code)
        notes.append(f"city taken from code {code.upper()}")
    if city in _ALIASES:
        notes.append(f"'{city}' mapped to '{_ALIASES[city]}' via alias table")
        city = _ALIASES[city]
    n = Norm(city, "; ".join(notes) + ".")
    n.extra = {"code": code, "qualifier": quals[0] if quals else None}
    return n


# ---------------------------------------------------------------- container count

_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}

_CTYPE = r"(?:\d{2}\s*'?\s*(?:ft|foot)?\s*(?:gp|dc|dv|hc|hq|rf|rh|ot|fr|tk|std|st|hcrf|nor)?|" \
         r"gp|dc|hc|hq|rf|reefer|dry|teu|feu)"


def normalize_container_count(raw: str) -> Norm:
    t = collapse_ws(raw).lower()
    if not t:
        return Norm(None, "Empty value.")
    # "2 x 20GP + 1 x 40HC", "3x40'HC", "3 X 40' HC"
    mult = re.findall(r"(\d+)\s*[x×\*]\s*" + _CTYPE, t)
    if mult:
        total = sum(int(n) for n in mult)
        if len(mult) == 1:
            return Norm(total, f"Read '{mult[0]} x <type>' as {total} container(s).")
        return Norm(total, f"Summed container lines {' + '.join(mult)} = {total}.")
    # "3", "3 containers", "3 (three) containers", "3 cntrs", "three (3)"
    digits = [int(d) for d in re.findall(r"(?<![\d.,])(\d+)(?![\d.,]*\s*(?:kg|kgs|mt|ft|'|gp|hc|dc))", t)]
    words = [_NUM_WORDS[w] for w in re.findall(r"[a-z]+", t) if w in _NUM_WORDS]
    values = set(digits) | set(words)
    if len(values) == 1:
        v = values.pop()
        note = "Read container quantity" + (" (digits and words agree)" if digits and words else "")
        return Norm(v, note + f": {v}.")
    if not values:
        return Norm(None, "No container quantity found in the value.")
    return Norm(None, f"Several different numbers found ({sorted(values)}); count is ambiguous.",
                candidates=sorted(values))


# ---------------------------------------------------------------- weight

_UNIT_RE = r"(kgs?|kilo(?:gram)?s?|kilo|mt|m/t|metric\s*tons?|metric\s*tonnes?|tonnes?|tons?|t|lbs?|pounds?)"


def _parse_number(s: str) -> tuple[float | None, list[float], str]:
    """Return (value, candidates, note). value None + candidates when separator is ambiguous."""
    s = s.strip().replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d+", s):
        return float(s), [], ""
    if "," in s and "." in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        return float(s.replace(thou, "").replace(dec, ".")), [], "thousands separator removed"
    sep = "," if "," in s else "."
    groups = s.split(sep)
    if len(groups) > 2:  # 1,234,567 / 1.234.567
        if all(len(g) == 3 for g in groups[1:]):
            return float("".join(groups)), [], "thousands separator removed"
        return None, [], "unrecognised number format"
    head, tail = groups
    if len(tail) == 3:  # 22,000 or 22.000 — thousands or decimal?
        if sep == ",":
            return float(head + tail), [], "thousands separator removed"
        return None, [float(head + tail), float(f"{head}.{tail}")], \
            "'.' followed by 3 digits could be a thousands separator or a decimal point"
    return float(f"{head}.{tail}"), [], "decimal separator read"


def normalize_weight(raw: str, source_label: str | None = None) -> Norm:
    t = collapse_ws(raw).lower()
    label = (source_label or "").lower()
    if re.search(r"\bnet\b|\bn\.?w\.?\b", t + " " + label) and "gross" not in t + " " + label:
        return Norm(None, "Value is a NET weight; gross weight not found.")
    m = re.search(r"(\d[\d.,\s ]*\d|\d)\s*" + _UNIT_RE + r"?\b", t)
    if not m:
        return Norm(None, "No numeric weight found.")
    num_s, unit = m.group(1), (m.group(2) or "")
    # a number directly followed by more text may belong to another quantity; keep simple
    value, cands, num_note = _parse_number(num_s)
    unit = unit.replace(" ", "")
    assumed = False
    if not unit:
        if re.search(r"\bkgs?\b|kilo", label):
            unit, unit_note = "kg", "unit taken from label"
        elif re.search(r"\bmt\b|tonne|\btons?\b", label):
            unit, unit_note = "mt", "unit taken from label"
        else:
            unit, unit_note, assumed = "kg", "no unit stated; assumed kg", True
    else:
        unit_note = ""
    if unit.startswith(("kg", "kilo")):
        factor, unit_desc = 1.0, "kg"
    elif unit in {"mt", "m/t", "t"} or unit.startswith(("metric", "tonne")):
        factor, unit_desc = 1000.0, "metric tonnes → kg (×1000)"
    elif unit.startswith("ton"):
        factor, unit_desc = 1000.0, "tons read as metric tonnes → kg (×1000)"
        assumed = True
    elif unit.startswith(("lb", "pound")):
        factor, unit_desc = 0.45359237, "lbs → kg (×0.45359237)"
    else:
        return Norm(None, f"Unrecognised unit '{unit}'.")
    notes = [n for n in (num_note, unit_note, unit_desc) if n]
    if value is None:
        cvals = sorted({round(c * factor, 3) for c in cands})
        return Norm(None, "Ambiguous number: " + "; ".join(notes) + f". Candidates (kg): {cvals}.",
                    candidates=cvals, assumed=assumed)
    kg = round(value * factor, 3)
    if kg == int(kg):
        kg = int(kg)
    return Norm(kg, "; ".join(notes).capitalize() + f". Result: {kg} kg.", assumed=assumed)


# ---------------------------------------------------------------- dispatch

def normalize_field(field: str, raw: str | None, source_label: str | None = None) -> Norm:
    if raw is None or not str(raw).strip():
        return Norm(None, "No value.")
    raw = str(raw)
    if field in {"shipper", "consignee", "notify_party"}:
        return normalize_party(raw)
    if field in {"port_of_loading", "port_of_discharge"}:
        return normalize_port(raw)
    if field == "container_count":
        return normalize_container_count(raw)
    if field == "gross_weight_kg":
        return normalize_weight(raw, source_label)
    raise ValueError(field)
