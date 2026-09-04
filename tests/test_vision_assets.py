"""Tests for vision asset export and Markdown packaging."""
from pathlib import Path
from zipfile import ZipFile

from src.utils.md_exporter import MDExporter
from src.utils.vision_assets import (
    page_asset_filename,
    vision_page_numbers,
    visual_evidence_markdown,
)


def test_page_asset_filename_pads_by_total() -> None:
    assert page_asset_filename(3, 9) == "p03.png"
    assert page_asset_filename(3, 120) == "p003.png"


def test_vision_page_numbers_skips_pure_errors() -> None:
    pages = [
        {"page_number": 1, "method": "pymupdf"},
        {"page_number": 2, "method": "gemini_vision"},
        {"page_number": 3, "method": "gemini_vision_error"},
        {"page_number": 4, "method": "gemini_vision_error_fallback_pymupdf"},
    ]
    assert vision_page_numbers(pages) == [2, 4]


def test_visual_evidence_markdown_embeds_relative_asset() -> None:
    block = visual_evidence_markdown(5, "assets/p05.png", title="架構圖")
    assert "#### Visual Evidence — 第 5 頁：架構圖" in block
    assert "![架構圖](assets/p05.png)" in block
    assert "- **資產**：assets/p05.png" in block


def test_export_reuses_cached_raster_without_pdf2image(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from PIL import Image

    from src.utils import vision_assets as va

    calls: list[tuple] = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("pdf2image should not be called when reusable")

    monkeypatch.setattr(va, "convert_from_path", boom)

    source = tmp_path / "cached_p02.png"
    Image.new("RGB", (12, 8), color=(1, 2, 3)).save(source, format="PNG")
    assets_dir = tmp_path / "assets"

    exported = va.export_vision_assets(
        tmp_path / "unused.pdf",
        [2],
        assets_dir,
        total_pages=2,
        reusable_sources={2: source},
    )
    assert len(exported) == 1
    assert exported[0].reused is True
    assert exported[0].absolute_path.is_file()
    assert calls == []


def test_export_summary_embeds_and_zips_when_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from PIL import Image

    from src.utils import md_exporter as md_mod

    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def fake_export(pdf_path, page_numbers, assets_dir, *, total_pages, dpi=150, reusable_sources=None):
        from src.utils.vision_assets import ExportedVisionAsset

        assets_dir = Path(assets_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for page in page_numbers:
            name = page_asset_filename(page, total_pages)
            target = assets_dir / name
            Image.new("RGB", (8, 8), color=(20, 40, 60)).save(target, format="PNG")
            written.append(
                ExportedVisionAsset(
                    page_number=page,
                    relative_path=f"assets/{name}",
                    absolute_path=target,
                    width=8,
                    height=8,
                    reused=bool(reusable_sources and page in reusable_sources),
                )
            )
        return written

    monkeypatch.setattr(md_mod, "export_vision_assets", fake_export)

    exporter = MDExporter(output_dir=str(tmp_path / "out"))
    result = exporter.export_summary(
        pdf_path,
        pages_data=[
            {
                "page_number": 1,
                "text": "文字頁",
                "method": "pymupdf",
                "total_pages": 2,
            },
            {
                "page_number": 2,
                "text": "視覺頁內容",
                "method": "gemini_vision",
                "total_pages": 2,
                "vision_asset_path": str(tmp_path / "preexisting.png"),
            },
        ],
        filename="示範簡報.pdf",
        preserve_vision_assets=True,
    )

    assert result is not None
    assert result.suffix == ".zip"
    with ZipFile(result) as archive:
        names = set(archive.namelist())
        assert any(n.endswith(".md") for n in names)
        assert "assets/p02.png" in names
        md_name = next(n for n in names if n.endswith(".md"))
        md_text = archive.read(md_name).decode("utf-8")
    assert "視覺頁內容" in md_text
    assert "![第 2 頁](assets/p02.png)" in md_text
    assert "#### Visual Evidence" in md_text
    assert "文字頁" in md_text
    # Text-only page should not get an empty evidence block
    assert "assets/p01.png" not in md_text


def test_export_summary_stays_markdown_without_vision_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "plain.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    exporter = MDExporter(output_dir=str(tmp_path / "out"))
    result = exporter.export_summary(
        pdf_path,
        pages_data=[
            {"page_number": 1, "text": "only text", "method": "pymupdf"},
        ],
        filename="plain.pdf",
        preserve_vision_assets=True,
    )
    assert result is not None
    assert result.suffix == ".md"
    assert "only text" in result.read_text(encoding="utf-8")
