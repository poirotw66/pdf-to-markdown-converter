"""Gemini token usage aggregation and USD cost estimates."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


# Paid-tier public rates (USD per 1M tokens). Estimates only — not invoices.
# Source: https://ai.google.dev/gemini-api/docs/pricing (synced 2026-09-04).
# Prefer pinned IDs (`gemini-3.8-flash`, `gemini-3.1-pro-preview`) for stable estimates;
# `*-latest` aliases float and reuse the same rate families below.
PRICING_SYNCED_AT = date(2026, 9, 4)
FLASH_LATEST_BASIS_MODEL = "gemini-3.8-flash"
PRO_LATEST_BASIS_MODEL = "gemini-3.1-pro-preview"
# Gemini 3.6+ Flash introductory discount ends end of day UTC 2026-12-31.
FLASH_INTRO_PRICING_END = date(2026, 12, 31)

_FLASH_FAMILY_RATES: dict[str, float] = {
    "input": 0.75,
    "output": 3.75,
    "input_after_intro": 1.50,
    "output_after_intro": 7.50,
}
_PRO_FAMILY_RATES: dict[str, float] = {
    "input": 2.00,
    "output": 12.00,
    "input_over_200k": 4.00,
    "output_over_200k": 18.00,
}

GEMINI_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "gemini-flash-latest": dict(_FLASH_FAMILY_RATES),
    "gemini-3.8-flash": dict(_FLASH_FAMILY_RATES),
    "gemini-pro-latest": dict(_PRO_FAMILY_RATES),
    "gemini-3.1-pro-preview": dict(_PRO_FAMILY_RATES),
}
PRO_LONG_CONTEXT_TOKEN_THRESHOLD = 200_000
_FLASH_MODELS = frozenset({"gemini-flash-latest", "gemini-3.8-flash"})
_PRO_MODELS = frozenset({"gemini-pro-latest", "gemini-3.1-pro-preview"})


def resolve_model_rates(
    model: str,
    *,
    as_of: date | None = None,
) -> dict[str, float] | None:
    """
    Return effective input/output USD-per-1M rates for ``model``.

    Flash intro rates apply through ``FLASH_INTRO_PRICING_END`` (inclusive, UTC).
    """
    base = GEMINI_PRICING_USD_PER_1M.get(model)
    if base is None:
        return None
    if model in _FLASH_MODELS:
        day = as_of or datetime.now(timezone.utc).date()
        if day <= FLASH_INTRO_PRICING_END:
            return {"input": base["input"], "output": base["output"]}
        return {
            "input": base["input_after_intro"],
            "output": base["output_after_intro"],
        }
    return dict(base)


@dataclass
class PageTokenUsage:
    page_number: int
    method: str
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    estimated_cost_usd: float = 0.0
    from_cache: bool = False


@dataclass
class ConversionUsageReport:
    model: str
    source_filename: str
    created_at: str
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    estimated_cost_usd: float
    pricing_note: str
    pages: list[PageTokenUsage] = field(default_factory=list)
    gemini_api_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def extract_usage_from_response(response: Any) -> dict[str, int]:
    """
    Read token counts from a Gemini generate_content response.

    Returns zeros when usage_metadata is missing.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None and isinstance(response, Mapping):
        meta = response.get("usage_metadata")
    if meta is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
        }

    def _get(name: str, *aliases: str) -> int:
        for key in (name, *aliases):
            value = getattr(meta, key, None)
            if value is None and isinstance(meta, Mapping):
                value = meta.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        return 0

    input_tokens = _get("prompt_token_count", "input_tokens")
    output_tokens = _get("candidates_token_count", "output_tokens")
    thoughts_tokens = _get("thoughts_token_count", "thinking_tokens")
    total_tokens = _get("total_token_count", "total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens + thoughts_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thoughts_tokens": thoughts_tokens,
        "total_tokens": total_tokens,
    }


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    thoughts_tokens: int = 0,
    *,
    as_of: date | None = None,
) -> float:
    """
    Estimate USD cost for one request (or aggregated totals).

    Thoughts/reasoning tokens are billed like output for estimation.
    Pro long-context rates apply when input_tokens > 200K for that unit.
    Flash rates follow the public intro → post-intro schedule.
    """
    rates = resolve_model_rates(model, as_of=as_of)
    if rates is None:
        # Unknown model: refuse silent invent — zero estimate.
        return 0.0
    billable_output = max(0, output_tokens) + max(0, thoughts_tokens)
    billable_input = max(0, input_tokens)
    if model in _PRO_MODELS and billable_input > PRO_LONG_CONTEXT_TOKEN_THRESHOLD:
        input_rate = rates["input_over_200k"]
        output_rate = rates["output_over_200k"]
    else:
        input_rate = rates["input"]
        output_rate = rates["output"]
    return (billable_input / 1_000_000.0) * input_rate + (
        billable_output / 1_000_000.0
    ) * output_rate


def pricing_note_text() -> str:
    """Short disclaimer embedded in usage reports."""
    return (
        "Estimated USD from public Gemini API paid-tier rates "
        f"(synced {PRICING_SYNCED_AT.isoformat()}; "
        f"flash ≈ {FLASH_LATEST_BASIS_MODEL}: "
        f"$0.75/$3.75 per 1M through {FLASH_INTRO_PRICING_END.isoformat()}, "
        f"then $1.50/$7.50; "
        f"pro ≈ {PRO_LATEST_BASIS_MODEL}: $2/$12, "
        f">200K prompt $4/$18). "
        "Prefer pinned model IDs for stable estimates. "
        "Thoughts tokens counted as output. Not an official invoice."
    )


def _page_usage_from_dict(page: Mapping[str, Any], model: str) -> PageTokenUsage:
    method = str(page.get("method") or "unknown")
    from_cache = bool(page.get("usage_from_cache"))
    if from_cache:
        input_tokens = 0
        output_tokens = 0
        thoughts_tokens = 0
    else:
        input_tokens = int(page.get("input_tokens") or 0)
        output_tokens = int(page.get("output_tokens") or 0)
        thoughts_tokens = int(page.get("thoughts_tokens") or 0)
    cost = estimate_cost_usd(model, input_tokens, output_tokens, thoughts_tokens)
    return PageTokenUsage(
        page_number=int(page.get("page_number") or 0),
        method=method,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thoughts_tokens=thoughts_tokens,
        estimated_cost_usd=round(cost, 6),
        from_cache=from_cache,
    )


def build_usage_report(
    *,
    model: str,
    source_filename: str,
    pages_data: list[Mapping[str, Any]],
) -> ConversionUsageReport:
    pages = [_page_usage_from_dict(page, model) for page in pages_data]
    input_tokens = sum(p.input_tokens for p in pages)
    output_tokens = sum(p.output_tokens for p in pages)
    thoughts_tokens = sum(p.thoughts_tokens for p in pages)
    # Sum of per-page estimates (each page rated on its own prompt size).
    estimated = sum(p.estimated_cost_usd for p in pages)
    gemini_calls = sum(
        1
        for p in pages
        if p.method.startswith("gemini") and not p.from_cache and (p.input_tokens + p.output_tokens) > 0
    )
    return ConversionUsageReport(
        model=model,
        source_filename=source_filename,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thoughts_tokens=thoughts_tokens,
        estimated_cost_usd=round(estimated, 6),
        pricing_note=pricing_note_text(),
        pages=pages,
        gemini_api_calls=gemini_calls,
    )


def _safe_stem(name: str) -> str:
    stem = Path(name).stem if name else "upload"
    # ASCII-only so paths can safely appear in HTTP response headers.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned[:80] or "upload"


def write_usage_log(
    report: ConversionUsageReport,
    usage_dir: Path | str,
) -> Path:
    """Write usage JSON under usage_dir; return path."""
    directory = Path(usage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = directory / f"{stamp}_{_safe_stem(report.source_filename)}.json"
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def usage_response_headers(report: ConversionUsageReport, log_path: Optional[Path]) -> dict[str, str]:
    # HTTP headers must be Latin-1/ASCII; never put raw Unicode paths here.
    log_name = ""
    log_header = ""
    if log_path is not None:
        log_name = log_path.name
        if not log_name.isascii():
            log_name = ""
        log_header = str(log_path.resolve()).encode("ascii", errors="replace").decode("ascii")
    return {
        "X-Usage-Model": report.model,
        "X-Usage-Input-Tokens": str(report.input_tokens),
        "X-Usage-Output-Tokens": str(report.output_tokens),
        "X-Usage-Thoughts-Tokens": str(report.thoughts_tokens),
        "X-Usage-Estimated-Cost-Usd": f"{report.estimated_cost_usd:.6f}",
        "X-Usage-Log-Name": log_name,
        "X-Usage-Log-Path": log_header,
        "Access-Control-Expose-Headers": (
            "X-Usage-Model, X-Usage-Input-Tokens, X-Usage-Output-Tokens, "
            "X-Usage-Thoughts-Tokens, X-Usage-Estimated-Cost-Usd, "
            "X-Usage-Log-Name, X-Usage-Log-Path, X-Output-Package"
        ),
    }


USAGE_LOG_NAME_PATTERN = re.compile(r"^[0-9]{8}_[0-9]{6}_[A-Za-z0-9._-]+\.json$")


def resolve_usage_log_file(usage_dir: Path | str, log_name: str) -> Path:
    """
    Resolve a usage log filename under usage_dir (no path traversal).

    Raises:
        ValueError: invalid name
        FileNotFoundError: missing file
    """
    name = Path(log_name).name
    if name != log_name or not USAGE_LOG_NAME_PATTERN.fullmatch(name):
        raise ValueError("Invalid usage log name")
    base = Path(usage_dir).resolve()
    candidate = (base / name).resolve()
    if candidate.parent != base:
        raise ValueError("Invalid usage log path")
    if not candidate.is_file():
        raise FileNotFoundError(name)
    return candidate
