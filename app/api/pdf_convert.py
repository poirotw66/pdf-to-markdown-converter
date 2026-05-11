"""API routes for PDF to Markdown conversion (standalone)."""
import re
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from src.utils.pdf_parser import PDFParser
from src.utils.md_exporter import MDExporter
from src.utils.logging_config import get_logger
from app.config import settings
from app.metrics import service_metrics

log = get_logger(__name__)

router = APIRouter()
UPLOAD_CHUNK_SIZE = 1024 * 1024
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _build_safe_pdf_filename(original_filename: str | None) -> str:
    """Return a normalized and safe PDF filename."""
    base_name = Path(original_filename or "upload.pdf").name
    normalized_name = SAFE_FILENAME_PATTERN.sub("_", base_name).strip("._")
    if not normalized_name.lower().endswith(".pdf"):
        normalized_name = f"{Path(normalized_name).stem}.pdf"
    stem = Path(normalized_name).stem or "upload"
    return f"{stem}.pdf"


async def _save_upload_file(upload_file: UploadFile, destination_path: Path, max_bytes: int) -> int:
    """Save upload file with chunked writes and enforce file size limits."""
    total_bytes = 0
    with destination_path.open("wb") as destination:
        while True:
            chunk = await upload_file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF file is too large. Maximum allowed size is {settings.pdf_max_upload_size_mb} MB.",
                )
            destination.write(chunk)
    await upload_file.seek(0)
    return total_bytes


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
    service_metrics.increment("conversion_requests_total")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        service_metrics.increment("conversion_rejected_total")
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Use provided API key or fall back to environment variable
    # If neither is available, raise an error
    api_key_to_use = None
    if api_key and api_key.strip():
        api_key_to_use = api_key.strip()
    elif hasattr(settings, "google_api_key") and settings.google_api_key:
        api_key_to_use = settings.google_api_key

    if not api_key_to_use:
        service_metrics.increment("conversion_rejected_total")
        raise HTTPException(
            status_code=400,
            detail=(
                "API key is required. Please provide your Google Gemini API key in "
                "the form or set GOOGLE_API_KEY in environment variables."
            ),
        )

    temp_dir = Path(tempfile.mkdtemp())
    safe_filename = _build_safe_pdf_filename(file.filename)
    temp_pdf_path = temp_dir / safe_filename

    try:
        max_upload_bytes = settings.pdf_max_upload_size_mb * 1024 * 1024
        uploaded_bytes = await _save_upload_file(
            upload_file=file,
            destination_path=temp_pdf_path,
            max_bytes=max_upload_bytes,
        )
        service_metrics.increment("conversion_uploaded_bytes_total", uploaded_bytes)

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

        service_metrics.increment("conversion_success_total")
        return FileResponse(
            path=summary_path,
            filename=f"{Path(file.filename).stem}.md",
            media_type="text/markdown",
        )

    except HTTPException:
        service_metrics.increment("conversion_failure_total")
        cleanup_temp_dir(temp_dir)
        raise
    except Exception as exc:
        service_metrics.increment("conversion_failure_total")
        cleanup_temp_dir(temp_dir)
        log.error("Error converting PDF", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to convert PDF due to an internal error.",
        ) from exc

