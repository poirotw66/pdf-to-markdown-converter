"""Export vision-page PNGs for Markdown packages (llm-wiki-style assets)."""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pdf2image import convert_from_path
from PIL import Image

from src.utils.logging_config import get_logger

log = get_logger(__name__)

ASSETS_DIR_NAME = "assets"


@dataclass(frozen=True)
class ExportedVisionAsset:
    """One PNG exported for a vision-routed PDF page."""

    page_number: int
    relative_path: str
    absolute_path: Path
    width: int
    height: int
    reused: bool = False


def page_asset_filename(page_number: int, total_pages: int) -> str:
    """Return ``pNN.png`` with zero-padding based on document length."""
    width = max(2, len(str(max(total_pages, 1))))
    return f"p{page_number:0{width}d}.png"


def embedded_asset_filename(
    page_number: int,
    image_index: int,
    total_pages: int,
) -> str:
    """Return ``pNN_eMM.png`` for an embedded image on a text-path page."""
    width = max(2, len(str(max(total_pages, 1))))
    return f"p{page_number:0{width}d}_e{image_index:02d}.png"


def vision_page_numbers(pages_data: Sequence[dict]) -> list[int]:
    """Pages whose extraction used Gemini vision (the rasters we actually read)."""
    pages: list[int] = []
    for page in pages_data:
        method = str(page.get("method") or "")
        if not method.startswith("gemini_vision"):
            continue
        if method.endswith("_error"):
            continue
        page_number = int(page.get("page_number") or 0)
        if page_number > 0:
            pages.append(page_number)
    return sorted(set(pages))


def reusable_sources_from_pages(
    pages_data: Sequence[dict],
) -> dict[int, Path]:
    """Collect full-page raster paths already attached to page dicts."""
    sources: dict[int, Path] = {}
    for page in pages_data:
        page_number = int(page.get("page_number") or 0)
        if page_number <= 0:
            continue
        raw = page.get("vision_asset_path")
        if not raw:
            continue
        path = Path(str(raw))
        if path.is_file():
            sources[page_number] = path
    return sources


def embedded_sources_from_pages(
    pages_data: Sequence[dict],
) -> dict[int, list[Path]]:
    """Collect embedded-image asset paths from PyMuPDF text-path pages."""
    sources: dict[int, list[Path]] = {}
    for page in pages_data:
        page_number = int(page.get("page_number") or 0)
        if page_number <= 0:
            continue
        assets = page.get("embedded_image_assets") or []
        paths: list[Path] = []
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            raw = asset.get("vision_asset_path") or asset.get("path")
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_file():
                paths.append(path)
        if paths:
            sources[page_number] = paths
    return sources


def extract_embedded_pngs_from_pdf_page(
    pdf_path: Path | str,
    page_number: int,
    *,
    min_area: int = 10_000,
    max_images: int = 8,
) -> list[tuple[bytes, int, int]]:
    """
    Extract significant embedded images from one PDF page as PNG bytes.

    Skips tiny icons below ``min_area`` (width * height in pixels).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    pdf = Path(pdf_path)
    results: list[tuple[bytes, int, int]] = []
    seen_xrefs: set[int] = set()
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        log.warning(f"Failed to open PDF for embedded images: {pdf}", exc_info=True)
        return []

    try:
        if page_number < 1 or page_number > doc.page_count:
            return []
        page = doc[page_number - 1]
        images = page.get_images(full=True) or []
        for entry in images:
            if len(results) >= max_images:
                break
            xref = int(entry[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            if not extracted:
                continue
            width = int(extracted.get("width") or 0)
            height = int(extracted.get("height") or 0)
            if width * height < max(0, min_area):
                continue
            raw = extracted.get("image") or b""
            if not raw:
                continue
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGB")
                    elif image.mode == "RGBA":
                        background = Image.new("RGB", image.size, (255, 255, 255))
                        background.paste(image, mask=image.split()[-1])
                        image = background
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    results.append((buffer.getvalue(), image.width, image.height))
            except Exception:
                log.debug(
                    f"Skip undecodable embedded image xref={xref} on page {page_number}"
                )
                continue
    finally:
        doc.close()
    return results


def _record_exported(
    *,
    page_number: int,
    target: Path,
    reused: bool,
) -> ExportedVisionAsset | None:
    try:
        with Image.open(target) as image:
            width, height = image.size
    except Exception:
        width, height = 0, 0
        if not target.is_file():
            return None
    return ExportedVisionAsset(
        page_number=page_number,
        relative_path=f"{ASSETS_DIR_NAME}/{target.name}",
        absolute_path=target,
        width=width,
        height=height,
        reused=reused,
    )


def export_vision_assets(
    pdf_path: Path | str,
    page_numbers: Iterable[int],
    assets_dir: Path | str,
    *,
    total_pages: int,
    dpi: int = 150,
    reusable_sources: Mapping[int, Path] | None = None,
) -> list[ExportedVisionAsset]:
    """
    Place selected PDF page PNGs under ``assets_dir``.

    Prefer ``reusable_sources`` (rasters already produced during Gemini parsing
    or loaded from cache). Only missing pages are re-rendered via pdf2image.
    """
    pages = sorted({int(p) for p in page_numbers if int(p) > 0})
    if not pages:
        return []

    pdf = Path(pdf_path)
    out_dir = Path(assets_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = reusable_sources or {}

    written: list[ExportedVisionAsset] = []
    for page_number in pages:
        filename = page_asset_filename(page_number, total_pages)
        target = out_dir / filename
        source = sources.get(page_number)
        try:
            if source is not None and Path(source).is_file():
                source_path = Path(source).resolve()
                target_path = target.resolve()
                if source_path != target_path:
                    shutil.copy2(source_path, target)
                recorded = _record_exported(
                    page_number=page_number,
                    target=target,
                    reused=True,
                )
                if recorded:
                    written.append(recorded)
                continue

            images = convert_from_path(
                str(pdf),
                dpi=dpi,
                first_page=page_number,
                last_page=page_number,
                single_file=True,
            )
            if not images:
                log.warning(f"No raster produced for page {page_number}")
                continue
            image: Image.Image = images[0]
            image.save(target, format="PNG")
            recorded = _record_exported(
                page_number=page_number,
                target=target,
                reused=False,
            )
            if recorded:
                written.append(recorded)
        except Exception:
            log.warning(
                f"Failed to export vision asset for page {page_number}",
                exc_info=True,
            )
    return written


def visual_evidence_markdown(
    page_number: int,
    relative_path: str,
    *,
    title: str | None = None,
) -> str:
    """
    Inline Visual Evidence block (llm-wiki convention).

    Placed under the page body so readers see the original raster in context.
    """
    heading = title or f"第 {page_number} 頁"
    return (
        f"#### Visual Evidence — 第 {page_number} 頁：{heading}\n\n"
        f"![{heading}]({relative_path})\n\n"
        f"- **資產**：{relative_path}\n"
        f"- **來源位置**：PDF 第 {page_number} 頁\n"
    )
