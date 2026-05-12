"""Export PDF pages to Markdown files."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


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
        filename: str = None
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
        
        # Get PDF filename without extension
        if filename:
            pdf_name = Path(filename).stem
        else:
            pdf_name = pdf_path.stem
        
        # Create subdirectory for this PDF
        pdf_md_dir = self.output_dir / pdf_name
        pdf_md_dir.mkdir(parents=True, exist_ok=True)
        
        exported_count = 0
        
        for page_data in pages_data:
            page_num = page_data.get("page_number")
            text = page_data.get("text", "")
            method = page_data.get("method", "unknown")
            
            if not page_num:
                continue
            
            # Create MD file path
            md_file = pdf_md_dir / f"page_{page_num:03d}.md"
            
            # Prepare MD content with metadata
            md_content = f"""# Page {page_num}

**Source:** {pdf_path.name}  
**Extraction Method:** {method}  
**Page Number:** {page_num}

---

{text}
"""
            
            try:
                # Write MD file
                with open(md_file, 'w', encoding='utf-8') as f:
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
        filename: str = None
    ) -> Path:
        """
        Export a summary MD file with all pages combined.
        
        Args:
            pdf_path: Path to PDF file
            pages_data: List of page data dictionaries
            filename: Optional custom filename
            
        Returns:
            Path to the summary MD file
        """
        if not pages_data:
            return None
        
        # Get PDF filename without extension
        if filename:
            pdf_name = Path(filename).stem
        else:
            pdf_name = pdf_path.stem
        
        # Create subdirectory for this PDF
        pdf_md_dir = self.output_dir / pdf_name
        pdf_md_dir.mkdir(parents=True, exist_ok=True)
        
        # Create summary file
        summary_file = pdf_md_dir / "summary.md"
        
        # Prepare summary content
        summary_content = f"""# {pdf_name}

**Source:** {pdf_path.name}  
**Total Pages:** {len(pages_data)}  
**Extraction Date:** {_extraction_timestamp_iso(pages_data)}

---

"""
        
        # Add each page
        for page_data in pages_data:
            page_num = page_data.get("page_number")
            text = page_data.get("text", "")
            method = page_data.get("method", "unknown")
            
            summary_content += f"""
## Page {page_num}

**Method:** {method}

{text}

---

"""
        
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary_content)
            print(f"  ✓ Exported summary to {summary_file}")
            return summary_file
        except Exception as e:
            print(f"  Warning: Failed to save summary MD: {str(e)}")
            return None

