"""Shared helpers for local scripts: .env loading and dataset access via the provided loader.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

DATA_DIR = Path(os.getenv("SHIPPEO_DATA_DIR", ROOT / "data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR


def import_loader():
    """Import the organisers' loader.py (from data/ or the repo root)."""
    for p in (DATA_DIR, ROOT):
        if (p / "loader.py").exists():
            sys.path.insert(0, str(p))
            import loader  # type: ignore
            return loader
    raise SystemExit(f"loader.py not found in {DATA_DIR} or {ROOT}. Extract the dataset ZIP into data/.")


def open_inbox(source: str | None):
    loader = import_loader()
    return loader.Inbox(source or str(DATA_DIR))


def make_reader(inbox, source: str | None = None):
    """Return read_attachment(att) -> bytes, using the organisers' loader (works for folder and HTTP)."""
    def read(att: dict) -> bytes:
        return inbox.read_bytes(att.get("path") or att.get("name"))
    return read
