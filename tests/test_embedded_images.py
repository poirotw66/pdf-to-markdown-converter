"""Tests for embedded-image extraction helpers."""
from pathlib import Path

import fitz
from PIL import Image

from src.utils.vision_assets import extract_embedded_pngs_from_pdf_page


def _make_pdf_with_embedded_image(path: Path, size: tuple[int, int] = (120, 90)) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    image = Image.new("RGB", size, color=(10, 20, 30))
    image_path = path.with_suffix(".png")
    image.save(image_path, format="PNG")
    page.insert_image(fitz.Rect(40, 40, 40 + size[0], 40 + size[1]), filename=str(image_path))
    page.insert_text((40, 30), "caption")
    doc.save(path)
    doc.close()
    image_path.unlink(missing_ok=True)


def test_extract_embedded_pngs_keeps_large_images(tmp_path: Path) -> None:
    pdf_path = tmp_path / "with_image.pdf"
    _make_pdf_with_embedded_image(pdf_path, size=(120, 90))
    extracted = extract_embedded_pngs_from_pdf_page(
        pdf_path,
        1,
        min_area=1000,
        max_images=4,
    )
    assert len(extracted) >= 1
    png_bytes, width, height = extracted[0]
    assert png_bytes.startswith(b"\x89PNG")
    assert width * height >= 1000


def test_extract_embedded_pngs_filters_tiny_icons(tmp_path: Path) -> None:
    pdf_path = tmp_path / "tiny.pdf"
    _make_pdf_with_embedded_image(pdf_path, size=(8, 8))
    extracted = extract_embedded_pngs_from_pdf_page(
        pdf_path,
        1,
        min_area=10_000,
        max_images=4,
    )
    assert extracted == []
