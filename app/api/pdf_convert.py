"""API routes for PDF to Markdown conversion (standalone)."""
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from src.utils.pdf_parser import PDFParser
from src.utils.md_exporter import MDExporter
from src.utils.logging_config import get_logger
from app.config import settings

log = get_logger(__name__)

router = APIRouter()


def cleanup_temp_dir(path: Path):
    """Cleanup temporary directory."""
    try:
        if path.exists():
            shutil.rmtree(path)
            log.info(f"Cleaned up temporary directory: {path}")
    except Exception as e:
        log.error(f"Error cleaning up temporary directory {path}: {e}")


@router.post("/convert-pdf")
async def convert_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prompt_template: str | None = Form(None),
    api_key: str | None = Form(None),
):
    """
    Convert uploaded PDF to Markdown.
    
    Args:
        file: PDF file to convert
        prompt_template: Prompt template ID or custom prompt string
        api_key: Google Gemini API key (required if not set in environment)
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Use provided API key or fall back to environment variable
    # If neither is available, raise an error
    api_key_to_use = None
    if api_key and api_key.strip():
        api_key_to_use = api_key.strip()
    elif hasattr(settings, 'google_api_key') and settings.google_api_key:
        api_key_to_use = settings.google_api_key
    
    if not api_key_to_use:
        raise HTTPException(
            status_code=400, 
            detail="API key is required. Please provide your Google Gemini API key in the form or set GOOGLE_API_KEY in environment variables."
        )

    temp_dir = Path(tempfile.mkdtemp())
    temp_pdf_path = temp_dir / file.filename

    try:
        # Save uploaded file
        with open(temp_pdf_path, "wb") as f:
            content = await file.read()
            f.write(content)

        log.info(f"Processing PDF: {file.filename}")

        # Initialize parser and exporter with API key
        parser = PDFParser(prompt_template=prompt_template, api_key=api_key_to_use)
        md_output_dir = temp_dir / "md_output"
        exporter = MDExporter(output_dir=str(md_output_dir))

        # Parse PDF
        pages_data = parser.parse_pdf(str(temp_pdf_path), prompt_template=prompt_template)

        if not pages_data:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")

        # Export summary (single MD file)
        summary_path = exporter.export_summary(temp_pdf_path, pages_data, file.filename)

        if not summary_path or not summary_path.exists():
            raise HTTPException(status_code=500, detail="Failed to generate Markdown file")

        # Schedule cleanup after response is sent
        background_tasks.add_task(cleanup_temp_dir, temp_dir)

        return FileResponse(
            path=summary_path,
            filename=f"{Path(file.filename).stem}.md",
            media_type="text/markdown",
        )

    except Exception as e:
        cleanup_temp_dir(temp_dir)
        log.error(f"Error converting PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error converting PDF: {str(e)}")

