"""Email classification: Gemini first, keyword rules as an offline fallback and a
second signal. needs_review is an internal flag, never a submitted category."""
from __future__ import annotations

import json
import re

from . import gemini
from .fields import CATEGORIES

CLASSIFY_SYSTEM = """You are a shipping-operations email classifier.
Classify the email into exactly one category:
- document_comparison: asks to check, compare, verify, review, validate or approve a draft Bill of Lading (BL, B/L, draft BL) or shipping document against a Shipping Instruction (SI).
- new_si_request: asks to prepare, create, amend, submit or update a Shipping Instruction.
- invoice_query: about invoices, billing, payments, charges, credit notes, debit notes or financial amounts.
- general_message: an operational update, schedule, coordination note or general communication that fits no other category.
- spam: irrelevant, promotional, phishing, scam or unsolicited content.

Important distinctions:
- A request to SEND a draft BL ("please send the draft BL for checking") has nothing to compare yet: general_message, not document_comparison.
- An email that asks to compare/check an SI against a draft BL is document_comparison even if the attachments are missing, broken, or one of them is the wrong document.
- An email that sends or asks for a Shipping Instruction to be prepared/submitted is new_si_request.
- Invoice, GR, THC/local charges, detention/D&D and invoice cancellation are invoice_query.
- Reports, reminders, notifications, schedules and greetings are general_message.

Rules:
- Use the subject, body, sender and attachment names together. Never decide from the subject alone: subjects can be misleading, and the body states the actual request.
- If signals conflict, choose the most likely category, lower the confidence and set conflicting_signals to true.
- Do not invent information.
- suggested_action: locate_si_and_bl | create_si_task | route_invoice_query | classify_only | ignore_spam | human_review.
Return JSON only."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "conflicting_signals": {"type": "boolean"},
        "suggested_action": {"type": "string"},
    },
    "required": ["category", "confidence", "reason", "conflicting_signals", "suggested_action"],
}

_ACTION = {
    "document_comparison": "locate_si_and_bl",
    "new_si_request": "create_si_task",
    "invoice_query": "route_invoice_query",
    "general_message": "classify_only",
    "spam": "ignore_spam",
}


def email_prompt(email: dict) -> str:
    atts = email.get("attachments") or []
    body = clean_body(email.get("body") or "")
    att_lines = "\n".join(f"- {a.get('name')} ({a.get('type') or 'unknown type'})" for a in atts) or "(none)"
    return (f"From: {email.get('sender')}\nSubject: {email.get('subject')}\n"
            f"Attachments ({len(atts)}):\n{att_lines}\n\nBody (banner, quoted replies and signature removed):\n{body}")


_BANNER = re.compile(r"^\s*(warning|caution|external email)[^\n]*(\n[^\n]+)*?\n\s*\n", re.I)
_QUOTE_SPLIT = re.compile(r"\n_{5,}\s*\n|\n-{2,}\s*original message\s*-{2,}|\nFrom: .+\nSent: ", re.I)
_SIGNOFF = re.compile(r"\n\s*(best regards|kind regards|regards|thanks(?: and| &) regards|thank you|best|cheers)\s*,?\s*\n", re.I)


def clean_body(body: str) -> str:
    """Remove the external-mail warning banner, quoted earlier messages and the signature,
    so the classifier only sees what THIS email asks for."""
    b = (body or "").replace("\r\n", "\n")
    b = _BANNER.sub("", b, count=1)
    b = _QUOTE_SPLIT.split(b)[0]
    m = _SIGNOFF.search(b)
    if m:
        b = b[:m.start()]
    return b.strip()


_RULES = [
    ("spam", r"\b(congratulations|you have won|claim your|click here to claim|gift card|lottery|prize|"
             r"urgent business proposal|bank officer|limited time offer|% off|buy now|unpaid customs fee|"
             r"mailbox has exceeded|verify your account|avoid (suspension|deactivation)|free-iphone)"),
    ("document_comparison", r"\b(compare|check|verify|validate|confirm|review)\b[^.]{0,80}\b(draft\s*b/?l|b/?l|bill of lading)\b[^.]{0,60}"
                            r"\b(si|shipping instruction)\b|"
                            r"\b(si|shipping instruction)\b[^.]{0,40}\b(and|&)\b[^.]{0,20}\b(draft\s*b/?l|draft bill of lading)\b[\s\S]{0,160}?"
                            r"\b(check|confirm|verify|compare|review|advise)|"
                            r"\bkindly confirm the b/?l is in order\b"),
    ("new_si_request", r"\bplease find (the )?shipping instruction\b|\b(prepare|create|submit|raise|amend|update)\b[^.]{0,40}"
                       r"\b(shipping instruction|s\.?i\.?)\b"),
    ("invoice_query", r"\b(invoice|billing|billed|debit note|credit note|thc|local charges?|d&d|detention|demurrage|"
                      r"payment|remittance|statement of account|\bgr\b is still missing)\b"),
]


def classify_rules(email: dict) -> dict:
    """Keyword fallback over the cleaned body. The subject is only a weak tie-breaker,
    because subjects in this inbox are often misleading (e.g. 'TO CONFIRM DOCS' on a
    request to *send* a draft BL)."""
    body = clean_body(email.get("body") or "").lower()
    subject = (email.get("subject") or "").lower()
    n_att = len(email.get("attachments") or [])
    for cat, rx in _RULES:
        if re.search(rx, body):
            conf = 0.8
            if cat == "document_comparison":
                conf = 0.9 if n_att >= 2 else 0.75
            return {"category": cat, "confidence": conf, "reason": f"Keyword rule matched in body ({cat}).",
                    "conflicting_signals": False, "suggested_action": _ACTION[cat], "source": "rules"}
    if re.search(r"\bsend (the |us )?(draft )?b/?l\b", body):
        return {"category": "general_message", "confidence": 0.75,
                "reason": "Body asks for a draft BL to be sent (no documents to compare yet).",
                "conflicting_signals": "confirm docs" in subject, "suggested_action": "classify_only",
                "source": "rules"}
    return {"category": "general_message", "confidence": 0.6, "reason": "No specific request detected in the body.",
            "conflicting_signals": False, "suggested_action": "classify_only", "source": "rules"}


def classify(email: dict, use_gemini: bool = True) -> dict:
    """Return {category, confidence, reason, conflicting_signals, suggested_action,
    needsHumanReview, source, rules, geminiRaw, error}."""
    rules = classify_rules(email)
    out = dict(rules)
    out.update(rules=rules, geminiRaw=None, error=None)
    rules_sure = rules["confidence"] >= 0.8 and not rules.get("conflicting_signals")
    if use_gemini and gemini.available() and (gemini.MODE == "full" or not rules_sure):
        r = gemini.call_json(CLASSIFY_SYSTEM, text=email_prompt(email), schema=CLASSIFY_SCHEMA)
        out["geminiRaw"] = r.raw_text
        if r.ok and r.data.get("category") in CATEGORIES:
            out.update({k: r.data.get(k) for k in CLASSIFY_SCHEMA["required"]})
            out["source"] = "gemini"
            if rules["category"] != out["category"] and rules["confidence"] >= 0.75:
                out["reason"] += f" (Keyword rules suggested {rules['category']}.)"
        else:
            out["error"] = r.error or f"Invalid category in Gemini output: {json.dumps(r.data)[:200]}"
            out["reason"] = "Gemini classification failed; keyword fallback used. " + rules["reason"]
    out["confidence"] = float(out.get("confidence") or 0)
    out["needsHumanReview"] = out["confidence"] < 0.70 or bool(out.get("conflicting_signals")) or bool(out["error"])
    return out
