"""Canonical field names, equivalent labels, categories and comparison states."""
from __future__ import annotations

FIELDS: list[str] = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]

PARTY_FIELDS = {"shipper", "consignee", "notify_party"}
PORT_FIELDS = {"port_of_loading", "port_of_discharge"}
MAJOR_FIELDS = {"port_of_loading", "port_of_discharge", "container_count", "gross_weight_kg"}

FIELD_DISPLAY = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}

# Equivalent labels. Matching is case-insensitive and longest-label-first,
# so "Notify Party" wins over "Notify".
LABELS: dict[str, list[str]] = {
    "shipper": ["shipper", "exporter", "shipped by", "shipper/exporter", "shipper / exporter"],
    "consignee": ["consignee", "consigned to"],
    "notify_party": ["notify party", "notify parties", "notification party", "notify", "also notify"],
    "port_of_loading": ["port of loading", "load port", "loading port", "pol", "port of load",
                        "place of loading"],
    "port_of_discharge": ["port of discharge", "discharge port", "pod", "port of discharging",
                          "place of discharge"],
    "container_count": ["container count", "no. of containers", "no of containers",
                        "no. of container", "no of container", "number of containers",
                        "container quantity", "qty of containers", "containers",
                        "container qty", "total containers", "total no. of containers"],
    "gross_weight_kg": ["total gross weight", "gross weight", "gross wt.", "gross wt", "g.w.",
                        "g.w", "gw", "gross weight (kg)", "gross weight (kgs)", "total gross wt"],
}

# The five dataset categories. Confirm the exact strings against sample_submission.json.
CATEGORIES: list[str] = [
    "document_comparison",
    "new_si_request",
    "invoice_query",
    "general_message",
    "spam",
]

STATES = [
    "match_confirmed",
    "normalized_match",
    "mismatch_confirmed",
    "missing_in_si",
    "missing_in_bl",
    "unreadable",
    "ambiguous_needs_review",
]

MATCH_STATES = {"match_confirmed", "normalized_match"}

# Shipment-level status: (plain label, theme label)
STATUS_LABELS = {
    "match": ("Match", "Converged Reality"),
    "mismatch": ("Mismatch", "Diverging Reality"),
    "needs_review": ("Needs review", "Unresolved Reality"),
    "incomplete": ("Incomplete", "Incomplete Reality"),
}

NO_MISMATCH_TEXT = "No mismatch detected."
