"""Tests for PDF conversion API behavior."""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.config import settings
from app.metrics import service_metrics


class FakeParserSuccess:
    """Fake parser that returns deterministic output."""

    def __init__(self, prompt_template: str | None = None, api_key: str | None = None) -> None:
        self.prompt_template = prompt_template
        self.api_key = api_key

    def parse_pdf(self, pdf_path: str, prompt_template: str | None = None) -> list[dict]:
        return [{"page_number": 1, "text": "hello", "total_pages": 1, "method": "pymupdf"}]


class FakeParserFailure:
    """Fake parser that raises a controlled exception."""

    def __init__(self, prompt_template: str | None = None, api_key: str | None = None) -> None:
        self.prompt_template = prompt_template
        self.api_key = api_key

    def parse_pdf(self, pdf_path: str, prompt_template: str | None = None) -> list[dict]:
        raise RuntimeError("boom secret")


class FakeExporter:
    """Fake exporter that creates a markdown output file."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)

    def export_summary(self, temp_pdf_path: Path, pages_data: list[dict], original_name: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / "result.md"
        output_file.write_text("# converted\n", encoding="utf-8")
        return output_file


def _make_pdf_bytes(size: int = 64) -> bytes:
    payload = b"%PDF-1.4\n%test\n" + (b"A" * size) + b"\n%%EOF\n"
    return payload


@pytest.mark.anyio
async def test_convert_pdf_success(monkeypatch) -> None:
    service_metrics.reset()
    monkeypatch.setattr("app.api.pdf_convert.PDFParser", FakeParserSuccess)
    monkeypatch.setattr("app.api.pdf_convert.MDExporter", FakeExporter)
    monkeypatch.setattr(settings, "google_api_key", "test-key")
    monkeypatch.setattr(settings, "pdf_max_upload_size_mb", 5)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert-pdf",
            files={"file": ("sample.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        metrics = (await client.get("/metrics")).json()

    assert response.status_code == 200
    assert response.text.startswith("# converted")
    assert response.headers["content-type"].startswith("text/markdown")
    assert metrics["conversion_requests_total"] == 1
    assert metrics["conversion_success_total"] == 1
    assert metrics["conversion_failure_total"] == 0


@pytest.mark.anyio
async def test_convert_pdf_internal_error_hides_details(monkeypatch) -> None:
    service_metrics.reset()
    monkeypatch.setattr("app.api.pdf_convert.PDFParser", FakeParserFailure)
    monkeypatch.setattr("app.api.pdf_convert.MDExporter", FakeExporter)
    monkeypatch.setattr(settings, "google_api_key", "test-key")
    monkeypatch.setattr(settings, "pdf_max_upload_size_mb", 5)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/convert-pdf",
            files={"file": ("sample.pdf", _make_pdf_bytes(), "application/pdf")},
        )
        metrics = (await client.get("/metrics")).json()

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to convert PDF due to an internal error."
    assert "boom secret" not in response.text
    assert metrics["conversion_requests_total"] == 1
    assert metrics["conversion_failure_total"] == 1


@pytest.mark.anyio
async def test_convert_pdf_rejects_oversized_upload(monkeypatch) -> None:
    service_metrics.reset()
    monkeypatch.setattr(settings, "google_api_key", "test-key")
    monkeypatch.setattr(settings, "pdf_max_upload_size_mb", 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        oversized_body = _make_pdf_bytes(size=2 * 1024 * 1024)
        response = await client.post(
            "/api/v1/convert-pdf",
            files={"file": ("large.pdf", oversized_body, "application/pdf")},
        )
        metrics = (await client.get("/metrics")).json()

    assert response.status_code == 413
    assert "Maximum allowed size is 1 MB" in response.json()["detail"]
    assert metrics["conversion_requests_total"] == 1
    assert metrics["conversion_failure_total"] == 1
