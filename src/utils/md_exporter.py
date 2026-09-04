"""Export PDF pages to Markdown files (optionally with vision assets)."""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.vision_assets import (
    ASSETS_DIR_NAME,
    export_vision_assets,
    vision_page_numbers,
    visual_evidence_markdown,
)


def _extraction_timestamp_iso(pages_data: List[Dict[str, Any]]) -> str:
    """
    Prefer cache timestamps from page dicts (when loaded from disk cache).
    Otherwise use the moment this summary file is written (UTC).
    """
    stamps: list[str] = []
    for page in pages_data:
        ts = page.get("cached_at")
        if ts:
            stamps.append(str(ts))
    if stamps:
        return max(stamps)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_stem(name: str) -> str:
    stem = Path(name).stem if name else "document"
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)
    return cleaned.strip("._")[:80] or "document"


class MDExporter:
    """Export PDF pages to Markdown files."""

    def __init__(self, output_dir: str = None):
        """
        Initialize MD exporter.

        Args:
            output_dir: Directory to save MD files (default: ./data/pdf_md/)
        """
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path("./data/pdf_md")

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_pages(
        self,
        pdf_path: Path,
        pages_data: List[Dict[str, Any]],
        filename: str = None,
    ) -> int:
        """
        Export PDF pages to Markdown files.

        Args:
            pdf_path: Path to PDF file
            pages_data: List of page data dictionaries with 'page_number' and 'text'
            filename: Optional custom filename (default: PDF filename without extension)

        Returns:
            Number of pages exported
        """
        if not pages_data:
            return 0

        if filename:
            pdf_name = Path(filename).stem
        else:
            pdf_name = pdf_path.stem

        pdf_md_dir = self.output_dir / pdf_name
        pdf_md_dir.mkdir(parents=True, exist_ok=True)

        exported_count = 0

        for page_data in pages_data:
            page_num = page_data.get("page_number")
            text = page_data.get("text", "")
            method = page_data.get("method", "unknown")

            if not page_num:
                continue

            md_file = pdf_md_dir / f"page_{page_num:03d}.md"
            md_content = f"""# Page {page_num}

**Source:** {pdf_path.name}  
**Extraction Method:** {method}  
**Page Number:** {page_num}

---

{text}
"""

            try:
                with open(md_file, "w", encoding="utf-8") as f:
                    f.write(md_content)
                exported_count += 1
            except Exception as e:
                print(f"  Warning: Failed to save page {page_num} to MD: {str(e)}")

        if exported_count > 0:
            print(f"  ✓ Exported {exported_count} pages to {pdf_md_dir}")

        return exported_count

    def export_summary(
        self,
        pdf_path: Path,
        pages_data: List[Dict[str, Any]],
        filename: str = None,
        usage_summary: Dict[str, Any] | None = None,
        *,
        preserve_vision_assets: bool = True,
        vision_asset_dpi: int = 150,
    ) -> Optional[Path]:
        """
        Export a summary MD file with all pages combined.

        When ``preserve_vision_assets`` is True, Gemini vision pages are also
        rendered to ``assets/pNN.png`` and embedded inline (llm-wiki style).
        If any assets exist, a zip package (``.md`` + ``assets/``) is returned
        instead of a bare markdown file.

        Args:
            pdf_path: Path to PDF file
            pages_data: List of page data dictionaries
            filename: Optional custom filename
            usage_summary: Optional token/cost totals for the markdown header
            preserve_vision_assets: Export and embed vision-page rasters
            vision_asset_dpi: DPI for exported page PNGs

        Returns:
            Path to the summary ``.md`` or package ``.zip``
        """
        if not pages_data:
            return None

        if filename:
            pdf_name = _safe_stem(filename)
        else:
            pdf_name = _safe_stem(pdf_path.name)

        pdf_md_dir = self.output_dir / pdf_name
        pdf_md_dir.mkdir(parents=True, exist_ok=True)

        assets_by_page: dict[int, str] = {}
        if preserve_vision_assets:
            vision_pages = vision_page_numbers(pages_data)
            total_pages = max(
                (int(p.get("page_number") or 0) for p in pages_data),
                default=len(pages_data),
            )
            if vision_pages:
                assets_dir = pdf_md_dir / ASSETS_DIR_NAME
                exported = export_vision_assets(
                    pdf_path,
                    vision_pages,
                    assets_dir,
                    total_pages=total_pages or len(vision_pages),
                    dpi=vision_asset_dpi,
                )
                assets_by_page = {
                    item.page_number: item.relative_path for item in exported
                }
                if exported:
                    print(
                        f"  ✓ Exported {len(exported)} vision assets to {assets_dir}"
                    )

        summary_file = pdf_md_dir / f"{pdf_name}.md"

        usage_block = ""
        if usage_summary:
            model = usage_summary.get("model", "N/A")
            input_tokens = usage_summary.get("input_tokens", 0)
            output_tokens = usage_summary.get("output_tokens", 0)
            thoughts_tokens = usage_summary.get("thoughts_tokens", 0)
            cost = usage_summary.get("estimated_cost_usd", 0.0)
            usage_block = (
                f"**Model:** {model}  \n"
                f"**Input Tokens:** {input_tokens}  \n"
                f"**Output Tokens:** {output_tokens}  \n"
                f"**Thoughts Tokens:** {thoughts_tokens}  \n"
                f"**Estimated Cost (USD):** {float(cost):.6f}  \n"
                f"**Cost Note:** estimate from public API rates, not an invoice\n"
            )

        asset_note = ""
        if assets_by_page:
            asset_note = (
                f"**Vision Assets:** {len(assets_by_page)} page image(s) under "
                f"`{ASSETS_DIR_NAME}/`  \n"
            )

        summary_content = f"""# {pdf_name}

**Source:** {pdf_path.name}  
**Total Pages:** {len(pages_data)}  
**Extraction Date:** {_extraction_timestamp_iso(pages_data)}
{usage_block}{asset_note}
---

"""

        for page_data in pages_data:
            page_num = page_data.get("page_number")
            text = page_data.get("text", "")
            method = page_data.get("method", "unknown")

            summary_content += f"""
## Page {page_num}

**Method:** {method}

{text}
"""
            relative = assets_by_page.get(int(page_num or 0))
            if relative:
                summary_content += "\n" + visual_evidence_markdown(
                    int(page_num),
                    relative,
                )

            summary_content += "\n---\n\n"

        try:
            summary_file.write_text(summary_content, encoding="utf-8")
            print(f"  ✓ Exported summary to {summary_file}")
        except Exception as e:
            print(f"  Warning: Failed to save summary MD: {str(e)}")
            return None

        if not assets_by_page:
            return summary_file

        zip_path = pdf_md_dir / f"{pdf_name}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(summary_file, arcname=f"{pdf_name}.md")
                assets_dir = pdf_md_dir / ASSETS_DIR_NAME
                for png in sorted(assets_dir.glob("p*.png")):
                    archive.write(png, arcname=f"{ASSETS_DIR_NAME}/{png.name}")
            print(f"  ✓ Packaged Markdown + assets → {zip_path}")
            return zip_path
        except Exception as e:
            print(f"  Warning: Failed to build zip package: {str(e)}")
            return summary_file
