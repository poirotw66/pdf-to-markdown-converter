"""Tests for Gemini token usage extraction and USD cost estimates."""
from datetime import date
from pathlib import Path

from src.utils.token_usage import (
    build_usage_report,
    estimate_cost_usd,
    extract_usage_from_response,
    resolve_model_rates,
    write_usage_log,
)


class _Meta:
    def __init__(self, **kwargs: int) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Response:
    def __init__(self, **kwargs: int) -> None:
        self.usage_metadata = _Meta(**kwargs)


def test_extract_usage_from_response_reads_metadata() -> None:
    usage = extract_usage_from_response(
        _Response(
            prompt_token_count=1000,
            candidates_token_count=200,
            thoughts_token_count=50,
            total_token_count=1250,
        )
    )
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] == 200
    assert usage["thoughts_tokens"] == 50
    assert usage["total_tokens"] == 1250


def test_estimate_cost_flash_uses_intro_public_rates() -> None:
    # Through 2026-12-31: 1M input + 1M output at $0.75 / $3.75
    cost = estimate_cost_usd(
        "gemini-flash-latest",
        1_000_000,
        1_000_000,
        0,
        as_of=date(2026, 9, 4),
    )
    assert abs(cost - 4.5) < 1e-9


def test_estimate_cost_flash_uses_post_intro_public_rates() -> None:
    # From 2027-01-01: 1M input + 1M output at $1.50 / $7.50
    cost = estimate_cost_usd(
        "gemini-flash-latest",
        1_000_000,
        1_000_000,
        0,
        as_of=date(2027, 1, 1),
    )
    assert abs(cost - 9.0) < 1e-9


def test_resolve_flash_rates_switch_after_intro_end() -> None:
    intro = resolve_model_rates("gemini-flash-latest", as_of=date(2026, 12, 31))
    post = resolve_model_rates("gemini-flash-latest", as_of=date(2027, 1, 1))
    assert intro == {"input": 0.75, "output": 3.75}
    assert post == {"input": 1.50, "output": 7.50}


def test_estimate_cost_counts_thoughts_as_output() -> None:
    cost = estimate_cost_usd(
        "gemini-flash-latest",
        0,
        0,
        1_000_000,
        as_of=date(2026, 9, 4),
    )
    assert abs(cost - 3.75) < 1e-9


def test_estimate_cost_pro_long_context_tier() -> None:
    cost = estimate_cost_usd("gemini-pro-latest", 200_001, 0, 0)
    assert abs(cost - (200_001 / 1_000_000.0) * 4.0) < 1e-9


def test_build_usage_report_sums_pages_and_zeros_cache() -> None:
    report = build_usage_report(
        model="gemini-flash-latest",
        source_filename="demo.pdf",
        pages_data=[
            {
                "page_number": 1,
                "method": "gemini_vision",
                "input_tokens": 1000,
                "output_tokens": 100,
                "thoughts_tokens": 0,
                "usage_from_cache": False,
            },
            {
                "page_number": 2,
                "method": "gemini_vision",
                "input_tokens": 999,
                "output_tokens": 99,
                "thoughts_tokens": 0,
                "usage_from_cache": True,
            },
            {
                "page_number": 3,
                "method": "pymupdf",
                "input_tokens": 0,
                "output_tokens": 0,
                "thoughts_tokens": 0,
            },
        ],
    )
    assert report.input_tokens == 1000
    assert report.output_tokens == 100
    assert report.pages[1].from_cache is True
    assert report.pages[1].input_tokens == 0
    assert report.gemini_api_calls == 1
    assert report.estimated_cost_usd > 0


def test_write_usage_log_creates_json(tmp_path: Path) -> None:
    report = build_usage_report(
        model="gemini-flash-latest",
        source_filename="扣薪入門.docx",
        pages_data=[
            {
                "page_number": 1,
                "method": "gemini_vision",
                "input_tokens": 10,
                "output_tokens": 5,
                "thoughts_tokens": 1,
            }
        ],
    )
    path = write_usage_log(report, tmp_path)
    assert path.is_file()
    # Filename stem must be ASCII-safe for HTTP headers / portable paths.
    assert path.name.isascii()
    text = path.read_text(encoding="utf-8")
    assert "estimated_cost_usd" in text
    assert "pages" in text


def test_usage_response_headers_are_ascii_for_chinese_source(tmp_path: Path) -> None:
    from src.utils.token_usage import usage_response_headers

    report = build_usage_report(
        model="gemini-flash-latest",
        source_filename="金融業生成式AI平台工程.pdf",
        pages_data=[
            {
                "page_number": 1,
                "method": "gemini_vision",
                "input_tokens": 10,
                "output_tokens": 5,
                "thoughts_tokens": 0,
            }
        ],
    )
    path = write_usage_log(report, tmp_path)
    headers = usage_response_headers(report, path)
    for key, value in headers.items():
        assert key.isascii(), key
        assert value.isascii(), f"{key}={value!r}"
    assert headers["X-Usage-Log-Name"] == path.name


def test_resolve_usage_log_file_rejects_traversal(tmp_path: Path) -> None:
    from src.utils.token_usage import resolve_usage_log_file

    report = build_usage_report(
        model="gemini-flash-latest",
        source_filename="demo.pdf",
        pages_data=[
            {
                "page_number": 1,
                "method": "pymupdf",
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ],
    )
    path = write_usage_log(report, tmp_path)
    resolved = resolve_usage_log_file(tmp_path, path.name)
    assert resolved == path.resolve()
    try:
        resolve_usage_log_file(tmp_path, "../secret.json")
        assert False, "expected ValueError"
    except ValueError:
        pass
