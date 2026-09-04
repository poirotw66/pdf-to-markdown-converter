# Token Usage and Cost Estimation Design

**Date:** 2026-07-14  
**Status:** Approved for implementation

## Goal

For each conversion job, report Gemini input/output token usage and an estimated USD cost in:
1. Markdown summary header (totals only)
2. Frontend UI + console/script logs
3. A separate JSON file under `data/usage_logs/` with totals and per-page detail

## Pricing (estimate only, not billing)

Synced to [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) on **2026-09-04**.
Prefer pinned IDs for stable estimates; `*-latest` aliases float.

| Model | Input $/1M | Output $/1M | Notes |
|-------|------------|-------------|-------|
| `gemini-flash-latest` / `gemini-3.8-flash` | 0.75 | 3.75 | Intro rate through 2026-12-31 |
| `gemini-flash-latest` / `gemini-3.8-flash` | 1.50 | 7.50 | From 2027-01-01 |
| `gemini-pro-latest` / `gemini-3.1-pro-preview` (prompt ≤200K) | 2.00 | 12.00 | |
| `gemini-pro-latest` / `gemini-3.1-pro-preview` (prompt >200K) | 4.00 | 18.00 | |

Thoughts/reasoning tokens count toward output for estimation.

## Data flow

1. Each Gemini `generate_content` response → read `usage_metadata`
2. Attach per-page token fields on page dicts; PyMuPDF / cache-hit pages use 0 tokens for this run
3. Aggregate + estimate cost
4. Write `data/usage_logs/YYYYMMDD_HHMMSS_<stem>.json`
5. MD header gets model + totals + estimated USD
6. API `FileResponse` headers expose totals + log path
7. Frontend and `scripts/test_docx_convert.py` display totals

## Non-goals

- Official invoice / Google billing sync
- Embedding usage logs inside the Markdown body
