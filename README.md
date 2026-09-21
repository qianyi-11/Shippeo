# Shippeo

**Where shipping documents reveal their parallel realities.**

Shippeo is an AI-powered verification tool for shipping operations. It reads every email in an
inbox, classifies it, and — for document-comparison requests — compares a **Shipping Instruction
(SI)** against a **draft Bill of Lading (BL)** across seven fields, explaining every discrepancy
with source evidence. Anything it can't confidently decide is escalated to a human instead of
guessed at.

Built for the **Averis x Monash Hackathon 2026**, *Shipping Document Verification* use case.

| | |
|---|---|
| **GitHub Repository** | <https://github.com/qianyi-11/Shippeo> |
| **Live Prototype / Demo** | _TODO: add Vercel URL_ |
| **Slide Deck / Document** | _TODO: add link_ |
| **Video Demo** | _TODO: add link_ |

> **AI reads. Code decides.**
> Gemini extracts and classifies. Deterministic code normalises and compares. A low-confidence
> reading can never become a confirmed mismatch, and missing data is never a match.

---

## The problem

A shipping operations team works from one shared inbox — comparison requests, new SI requests,
invoice queries, updates and spam, all mixed together. Checking a draft BL against its SI means
manually cross-referencing seven fields across two documents, where the same information is often
labelled differently ("Port of Loading" vs "Load Port") or formatted differently
(`Global Foods Pte Ltd` vs `Global Foods Pte. Ltd.`). It's slow, repetitive, and one missed
discrepancy causes real delays.

## Features

- **Classification** of every email into one of five categories, using free keyword rules first
  and Gemini only when they're unsure
- **Field extraction** from plain text, Excel, Word, PDF, and scanned/image-only documents — each
  field read by two independent extractors and cross-checked for confidence
- **Deterministic comparison** of shipper, consignee, notify party, ports, container count and
  gross weight — no AI involved in the final verdict
- **Evidence-first UI** — every value traces back to the exact line it was read from in the
  original document
- **Human review queue** with full context (both values, confidence, evidence, a recommended
  action) for anything uncertain, plus a no-login reviewer flow
- **Real-time processing** — drop in a new email and watch it classify, read, and compare live
- **Interactive route map** (Leaflet/OpenStreetMap) drawn from the ports each document actually
  names
- **Printable discrepancy reports** and a self-evaluation pipeline scored against the organisers'
  hidden answer key

## Screens

| Screen | What it does |
|---|---|
| **Command Center** | Inbox with a real-data morning briefing, KPI tiles, filters, search, and a "New email" uploader |
| **Shipment Twin** | SI vs BL side by side, one connector per field, a live route map, and a status banner |
| **Document Forensics** | Both source documents with the relevant values highlighted in place |
| **Review Desk** | Every open case, with evidence and a no-login decision form |
| **Report** | A printable, per-shipment discrepancy report |
| **Insights** | Mismatch trends, category breakdown, and self-evaluation score history |

## Tech stack

| | |
|---|---|
| AI | Google Gemini (`gemini-3.6-flash`) — classification, extraction, OCR |
| Backend | Python 3.12, FastAPI, deployed as a Vercel Function |
| Database | Firebase Firestore |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Maps | Leaflet + OpenStreetMap |
| Hosting | Vercel |

## Setup

**Prerequisites:** Python 3.12+ (3.11 also works), Node.js 18+, and a free
[Gemini API key](https://aistudio.google.com).

**1. Clone and install**

```powershell
git clone https://github.com/qianyi-11/Shippeo.git
cd Shippeo
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

**2. Configure**

```powershell
copy .env.example .env
```

Open `.env` and add your Gemini key:

```
GEMINI_API_KEY=your-key-from-aistudio.google.com
```

By default `STORE=local`, which persists data to `.localdb/` on disk — no database setup needed
to run locally. To use Firebase Firestore instead, see [DEPLOY.md](DEPLOY.md).

**3. Load the dataset and run**

```powershell
python scripts/ingest.py --direct          # loads + processes the dataset into .localdb/
python -m uvicorn api.index:app --port 8000
```

Open <http://localhost:8000>.

**4. (Optional) Frontend hot reload**

```powershell
cd web
npm install
npm run dev
```

This runs the UI on its own dev server (proxying `/api` to port 8000) instead of the build served
by the backend.

**5. Run the tests**

```powershell
python -m pytest
```

Full configuration reference, the CLI and API reference, the data model, and Vercel deployment
instructions are all in [DEPLOY.md](DEPLOY.md).

## Results

Scored against the organisers' hidden answer key:

| Metric | Score |
|---|---|
| Mismatch-detection precision (no false alarms) | **1.000** |
| Correctly escalated to human review | **0.950** |
| Field-level F1 | 0.875 |

Full run: 520 emails processed, 0 processing failures, 93.8% average extraction confidence.

## Project structure

```
core/       business logic — classification, extraction, normalisation, comparison
api/        FastAPI app (the Vercel backend)
web/        React frontend
scripts/    CLI tools for ingesting data and self-evaluation
tests/      pytest suite
```

## License

Built for the Averis x Monash Hackathon 2026.
