import pytest

from core.extract_rules import parse_document, guess_role
from core.verify import build_document_fields
from core.compare import compare_shipment
from core.normalize import normalize_container_count, normalize_weight, normalize_port, normalize_party
from core import classify as classify_mod

SI_ALIGNED = """SHIPPING INSTRUCTION
SI No: SI-8821
Shipper: Global Foods Pte Ltd
12 Jurong Port Road, Singapore
Consignee: Euro Retail BV
Notify Party: Ocean Partners
Port of Loading: Singapore
Port of Discharge: Rotterdam
Container Count: 3
Gross Weight: 22,000 kg
"""

BL_ALIGNED = """BILL OF LADING (DRAFT)
Shipper: Global Foods Pte. Ltd.
12 Jurong Port Road, Singapore
Consignee: Euro Retail B.V.
Notify: Ocean Partners
Load Port: SINGAPORE
Discharge Port: Rotterdam
No. of Containers: 3
Gross Wt: 22000 KG
"""


def run(si_text, bl_text, si_gem=None, bl_gem=None):
    gem_ran = si_gem is not None or bl_gem is not None
    si = build_document_fields(parse_document(si_text), si_gem, si_text, gem_ran)
    bl = build_document_fields(parse_document(bl_text), bl_gem, bl_text, gem_ran)
    return compare_shipment(si, bl)


def test_a_aligned_no_mismatch():
    r = run(SI_ALIGNED, BL_ALIGNED)
    assert r["status"] == "match", r["reviewReasons"]
    assert r["headline"] == "No mismatch detected."
    assert r["mismatchedFields"] == []
    assert r["fields"]["shipper"]["state"] == "normalized_match"
    assert r["fields"]["consignee"]["state"] == "normalized_match"
    assert r["fields"]["port_of_loading"]["state"] == "normalized_match"
    assert r["fields"]["notify_party"]["state"] == "match_confirmed"
    assert r["riskLevel"] == "low"


def test_b_container_mismatch_only():
    bl = BL_ALIGNED.replace("No. of Containers: 3", "No. of Containers: 4")
    r = run(SI_ALIGNED, bl)
    assert r["status"] == "mismatch"
    assert r["mismatchedFields"] == ["container_count"]
    f = r["fields"]["container_count"]
    assert (f["siNormalized"], f["blNormalized"]) == (3, 4)
    assert r["fields"]["gross_weight_kg"]["state"] in ("match_confirmed", "normalized_match")
    assert r["riskLevel"] == "high"
    assert r["headline"] == "Mismatch detected at Container Count."


def _gem(fields_override):
    base = {f: {"raw_value": None, "source_label": None, "evidence": None, "confidence": 0.0,
                "uncertainty_reason": "not provided"} for f in
            ["shipper", "consignee", "notify_party", "port_of_loading", "port_of_discharge",
             "container_count", "gross_weight_kg"]}
    base.update(fields_override)
    return {"document_type": "BL", "document_confidence": 0.9, "fields": base, "document_uncertainties": []}


def _gem_from_text(text, overrides=None, conf=0.97):
    parsed = parse_document(text)
    fields = {}
    for f, v in parsed.items():
        hit = v["value"]
        fields[f] = {"raw_value": hit["raw_value"] if hit else None,
                     "source_label": hit["source_label"] if hit else None,
                     "evidence": hit["evidence"] if hit else None,
                     "confidence": conf if hit else 0.0, "uncertainty_reason": None}
    fields.update(overrides or {})
    return _gem(fields)


def test_c_unreadable_port_is_not_mismatch():
    bl = BL_ALIGNED.replace("Discharge Port: Rotterdam", "Discharge Port: R...erdam")
    bl_gem = _gem_from_text(bl, {"port_of_discharge": {
        "raw_value": "R...erdam", "source_label": "Discharge Port", "evidence": "Discharge Port: R...erdam",
        "confidence": 0.54, "uncertainty_reason": "Characters partly illegible"}})
    r = run(SI_ALIGNED, bl, si_gem=_gem_from_text(SI_ALIGNED), bl_gem=bl_gem)
    f = r["fields"]["port_of_discharge"]
    assert f["state"] in ("unreadable", "ambiguous_needs_review")
    assert "port_of_discharge" not in r["mismatchedFields"]
    assert r["status"] == "needs_review"
    assert r["needsHumanReview"] is True


def test_d_missing_bl_role_detection():
    assert guess_role("SI-8821.txt", SI_ALIGNED)[0] == "SI"
    assert guess_role("draft_BL_8821.txt", BL_ALIGNED)[0] == "BL"
    assert guess_role("doc1.txt", BL_ALIGNED)[0] == "BL"
    assert guess_role("notes.txt", "hello")[0] == "unknown"


def test_e_container_lines_sum():
    assert normalize_container_count("2 x 20GP + 1 x 40HC").value == 3
    assert normalize_container_count("3 x 40'HC").value == 3
    assert normalize_container_count("3 (THREE) CONTAINERS").value == 3
    assert normalize_container_count("3 containers").value == 3
    assert normalize_container_count("3 or 4").value is None


def test_f_metric_tonnes():
    assert normalize_weight("22 MT").value == 22000
    assert normalize_weight("22,000.00 KGS").value == 22000
    assert normalize_weight("22 000 kg").value == 22000
    assert normalize_weight("22000", "Gross Weight (KG)").value == 22000


def test_g_ambiguous_european_separator():
    n = normalize_weight("22.000 kg")
    assert n.value is None and 22000 in n.candidates


def test_g2_ambiguous_weight_settled_by_other_document():
    si = SI_ALIGNED.replace("Gross Weight: 22,000 kg", "Gross Weight: 22.000 kg")
    r = run(si, BL_ALIGNED)
    assert r["fields"]["gross_weight_kg"]["state"] == "normalized_match"
    assert r["fields"]["gross_weight_kg"]["needsReview"] is True


def test_g3_net_weight_not_used_as_gross():
    assert normalize_weight("20,500 kg", "Net Weight").value is None


def test_h_same_as_consignee():
    bl = BL_ALIGNED.replace("Notify: Ocean Partners", "Notify: SAME AS CONSIGNEE")
    si = SI_ALIGNED.replace("Notify Party: Ocean Partners", "Notify Party: Euro Retail BV")
    r = run(si, bl)
    assert r["fields"]["notify_party"]["state"] == "normalized_match", r["fields"]["notify_party"]


def test_i_port_alias():
    assert normalize_port("SGSIN").value == normalize_port("Singapore").value
    assert normalize_port("Singapore, SG").value == "singapore"
    assert normalize_port("Port Klang").value != normalize_port("Penang").value


def test_party_normalisation():
    assert normalize_party("Global Foods Pte Ltd").value == normalize_party("GLOBAL FOODS PTE. LTD.").value
    assert normalize_party("Euro Retail BV").value == normalize_party("Euro Retail B.V.").value
    assert normalize_party("Alpha Trading Sdn Bhd").value != normalize_party("Alpha Trading Co Ltd").value
    assert normalize_party("Global Foods Pte Ltd").value != normalize_party("Global Food Pte Ltd").value


def test_missing_field_is_not_a_match():
    bl = BL_ALIGNED.replace("Notify: Ocean Partners\n", "")
    r = run(SI_ALIGNED, bl)
    assert r["fields"]["notify_party"]["state"] == "missing_in_bl"
    assert r["status"] == "needs_review"


def test_j_misleading_subject_uses_body(monkeypatch):
    monkeypatch.setattr(classify_mod.gemini, "available", lambda: False)
    email = {"sender": "ops@example.com", "subject": "Invoice attached",
             "body": "Hi team, please check the draft BL against the SI before we release it.",
             "attachments": [{"name": "SI-1.txt"}, {"name": "BL-1.txt"}]}
    out = classify_mod.classify(email)
    assert out["category"] == "document_comparison"


def test_classify_uses_gemini_result(monkeypatch):
    from core.gemini import GeminiResult
    monkeypatch.setattr(classify_mod.gemini, "available", lambda: True)
    monkeypatch.setattr(classify_mod.gemini, "MODE", "full")
    monkeypatch.setattr(classify_mod.gemini, "call_json", lambda *a, **k: GeminiResult(
        True, {"category": "spam", "confidence": 0.93, "reason": "promo", "conflicting_signals": False,
               "suggested_action": "ignore_spam"}, "{}", None, "m"))
    out = classify_mod.classify({"subject": "x", "body": "Win a prize now", "attachments": []})
    assert out["category"] == "spam" and out["source"] == "gemini" and not out["needsHumanReview"]


def test_slash_and_bracket_labels():
    from core.extract_rules import field_for_key
    assert field_for_key("Notify Party/Intermediate Consignee") == "notify_party"
    assert field_for_key("Shipper (Principal or Seller) (发货人)") == "shipper"
    assert field_for_key("Consignee (Non-Negotiable)") == "consignee"
    assert field_for_key("To the Order of") == "consignee"
    assert field_for_key("Gross Weight毛重(KGS)") == "gross_weight_kg"
    assert field_for_key("No. of Containers or Packages") == "container_count"
    assert field_for_key("Port of Loading (POL)") == "port_of_loading"
    assert field_for_key("NET WEIGHT") is None
    assert field_for_key("Container No.") is None


def test_placeholder_is_missing_value():
    si = SI_ALIGNED.replace("Gross Weight: 22,000 kg", "Gross Weight: N/A")
    r = run(si, BL_ALIGNED)
    f = r["fields"]["gross_weight_kg"]
    assert f["state"] == "missing_in_si" and f["issue"] == "missing_value"
    assert r["status"] == "needs_review"


def test_locode_ports():
    si = SI_ALIGNED.replace("Port of Loading: Singapore", "Port of Loading: PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")
    bl = BL_ALIGNED.replace("Load Port: SINGAPORE", "Load Port: Port Klang, Malaysia")
    assert run(si, bl)["fields"]["port_of_loading"]["state"] == "normalized_match"
    bl2 = BL_ALIGNED.replace("Load Port: SINGAPORE", "Load Port: PORT KLANG (NORTHPORT), MALAYSIA (MYPKG)")
    assert run(si, bl2)["fields"]["port_of_loading"]["state"] == "mismatch_confirmed"


def test_wrong_doc_type_detection():
    from core.extract_rules import detect_doc_type
    assert detect_doc_type("COMMERCIAL INVOICE\n=====\nInvoice No.: 1")[0] == "OTHER"
    assert detect_doc_type("PACKING LIST\n====\nShipper: X")[0] == "OTHER"
    assert detect_doc_type("BILL OF LADING INSTRUCTION\nB/L NUMBER: 1")[0] == "SI"
    assert detect_doc_type("BILL OF LADING (DRAFT)\nB/L NUMBER: 1")[0] == "BL"


def test_clean_body_strips_banner_and_quotes():
    from core.classify import clean_body
    b = ("WARNING: This email originated outside of our organisation. Be careful.\n\nHi Elisa,\n\n"
         "Attached are the SI and draft BL. Please check.\n\nBest Regards,\nX\n\n______________________________\n"
         "From: Y\nSent: Z\n\nPlease follow the previous instruction.")
    out = clean_body(b)
    assert "WARNING" not in out and "previous instruction" not in out and "draft BL" in out
