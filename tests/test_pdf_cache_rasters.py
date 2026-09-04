"""Tests for PDF cache vision raster persistence."""
from pathlib import Path

from src.utils.pdf_cache import PDFCache


def test_write_and_resolve_vision_asset(tmp_path: Path) -> None:
    cache = PDFCache(cache_dir=str(tmp_path / "cache"))
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"

    meta = cache.write_vision_asset(pdf_path, 2, png_bytes, total_pages=12)
    assert meta["vision_asset_name"] == "p02.png"
    assert Path(meta["vision_asset_path"]).is_file()
    assert Path(meta["vision_asset_path"]).read_bytes() == png_bytes

    page = {
        "page_number": 2,
        "total_pages": 12,
        "method": "gemini_vision",
        "vision_asset_name": meta["vision_asset_name"],
        "vision_asset_sha256": meta["vision_asset_sha256"],
    }
    resolved = cache.resolve_vision_asset(pdf_path, page)
    assert resolved is not None
    assert resolved.read_bytes() == png_bytes


def test_save_page_strips_runtime_path_and_hydrates_on_load(tmp_path: Path) -> None:
    cache = PDFCache(cache_dir=str(tmp_path / "cache"))
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"cached"

    meta = cache.write_vision_asset(pdf_path, 1, png_bytes, total_pages=1)
    page_data = {
        "page_number": 1,
        "total_pages": 1,
        "text": "hello",
        "method": "gemini_vision",
        **meta,
    }
    assert cache.save_page(pdf_path, page_data)

    # JSON must not embed absolute runtime path
    cache_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cache_files) == 1
    raw = cache_files[0].read_text(encoding="utf-8")
    assert "vision_asset_path" not in raw
    assert "vision_asset_sha256" in raw

    loaded = cache.get_cached_page(pdf_path, 1)
    assert loaded is not None
    assert loaded["text"] == "hello"
    assert Path(loaded["vision_asset_path"]).is_file()


def test_resolve_rejects_sha_mismatch(tmp_path: Path) -> None:
    cache = PDFCache(cache_dir=str(tmp_path / "cache"))
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    meta = cache.write_vision_asset(pdf_path, 1, b"aaa", total_pages=1)
    page = {
        "page_number": 1,
        "total_pages": 1,
        "vision_asset_name": meta["vision_asset_name"],
        "vision_asset_sha256": "0" * 64,
    }
    assert cache.resolve_vision_asset(pdf_path, page) is None
