"""Thin Gemini wrapper: JSON output, retries with backoff, timeouts, on-disk cache.
The raw response text is always returned so callers can store it for audit."""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
# full  = Gemini classifies every email and extracts every SI/BL (two-extractor cross-check everywhere)
# smart = Gemini only where the deterministic rules are unsure or cannot read the file (fits free-tier quotas)
MODE = os.getenv("GEMINI_MODE", "smart").lower()
CACHE_DIR = Path(os.getenv("SHIPPEO_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache" / "gemini"))


class GeminiUnavailable(RuntimeError):
    pass


@dataclass
class GeminiResult:
    ok: bool
    data: dict | None
    raw_text: str | None
    error: str | None
    model: str
    cached: bool = False
    attempts: int = 0


def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


_client = None


def _get_client():
    global _client
    if _client is None:
        if not available():
            raise GeminiUnavailable("GEMINI_API_KEY is not set")
        from google import genai
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return _client


def _cache_key(model: str, system: str, parts_fingerprint: str, schema: dict | None) -> str:
    h = hashlib.sha256()
    for s in (model, system, parts_fingerprint, json.dumps(schema or {}, sort_keys=True)):
        h.update(s.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _strip_fences(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def call_json(system: str, text: str | None = None, file_bytes: bytes | None = None,
              mime_type: str | None = None, schema: dict | None = None,
              model: str | None = None, retries: int = 3, timeout_s: int = 90,
              use_cache: bool = True) -> GeminiResult:
    """Send a system prompt plus text and/or a file; expect a JSON object back."""
    model = model or DEFAULT_MODEL
    fp = hashlib.sha256((text or "").encode("utf-8") + (file_bytes or b"") + (mime_type or "").encode()).hexdigest()
    key = _cache_key(model, system, fp, schema)
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        c = json.loads(cache_file.read_text(encoding="utf-8"))
        return GeminiResult(True, c["data"], c["raw_text"], None, model, cached=True)

    from google.genai import types
    client = _get_client()
    parts = []
    if file_bytes is not None:
        parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type or "application/octet-stream"))
    if text is not None:
        parts.append(types.Part.from_text(text=text))
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0,
        http_options=types.HttpOptions(timeout=timeout_s * 1000),
    )
    if schema:
        cfg.response_json_schema = schema

    last_err, raw = None, None
    for attempt in range(1, retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=parts, config=cfg)
            raw = resp.text or ""
            data = json.loads(_strip_fences(raw))
            if not isinstance(data, dict):
                raise ValueError("response is not a JSON object")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"data": data, "raw_text": raw}, ensure_ascii=False), encoding="utf-8")
            return GeminiResult(True, data, raw, None, model, attempts=attempt)
        except Exception as e:  # noqa: BLE001 — surface every failure
            last_err = f"{type(e).__name__}: {e}"
            msg = str(e).lower()
            if attempt < retries:
                wait = (2 ** attempt) + random.random()
                if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
                    wait = max(wait, 20 * attempt)  # free-tier per-minute limits
                time.sleep(wait)
    return GeminiResult(False, None, raw, last_err, model, attempts=retries)
