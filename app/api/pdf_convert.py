"""API routes for PDF to Markdown conversion (standalone)."""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
from src.utils.pdf_parser import PDFParser
from src.utils.md_exporter import MDExporter
from src.utils.logging_config import get_logger
from app.config import settings, resolve_gemini_model
from app.metrics import service_metrics
from src.utils.token_usage import (
    build_usage_report,
    resolve_usage_log_file,
    usage_response_headers,
    write_usage_log,
)

log = get_logger(__name__)

router = APIRouter()
UPLOAD_CHUNK_SIZE = 1024 * 1024
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
SUPPORTED_FILE_EXTENSIONS = {".pdf", ".docx", ".pptx"}


def _build_safe_filename(original_filename: str | None) -> str:
    """Return a normalized and safe filename preserving supported extension."""
    base_name = Path(original_filename or "upload.pdf").name
    normalized_name = SAFE_FILENAME_PATTERN.sub("_", base_name).strip("._")
    extension = Path(normalized_name).suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        extension = ".pdf"
    stem = Path(normalized_name).stem or "upload"
    return f"{stem}{extension}"


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
                    detail=f"Uploaded file is too large. Maximum allowed size is {settings.pdf_max_upload_size_mb} MB.",
                )
            destination.write(chunk)
    await upload_file.seek(0)
    return total_bytes


def _convert_office_to_pdf(source_path: Path, temp_dir: Path) -> Path:
    """Convert docx/pptx file to PDF using LibreOffice in headless mode."""
    output_dir = temp_dir / "converted_pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    # Isolated user profile per request so parallel soffice processes do not lock the default profile.
    profile_dir = temp_dir / "lo_user_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    command = [
        settings.office_converter_bin,
        f"-env:UserInstallation={profile_uri}",
        "--headless",
        "--norestore",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.office_conversion_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Office conversion service is unavailable. Please install LibreOffice on the server.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Office to PDF conversion timed out. Please try a smaller file.",
        ) from exc

    if completed.returncode != 0:
        log.error(
            "Office to PDF conversion failed",
            extra={"stderr": completed.stderr, "stdout": completed.stdout, "code": completed.returncode},
        )
        raise HTTPException(
            status_code=422,
            detail="Failed to convert Office file to PDF. Please verify the file format.",
        )

    converted_pdf_path = output_dir / f"{source_path.stem}.pdf"
    if converted_pdf_path.exists():
        return converted_pdf_path

    generated_files = sorted(output_dir.glob("*.pdf"))
    if generated_files:
        return generated_files[0]

    raise HTTPException(
        status_code=422,
        detail="Failed to convert Office file to PDF. Please verify the file format.",
    )


def _save_office_converted_pdf_copy(temp_pdf_path: Path, original_filename: str) -> None:
    """Copy intermediate PDF to configured directory after Office -> PDF step."""
    save_dir_raw = (settings.office_intermediate_pdf_save_dir or "").strip()
    if not save_dir_raw:
        return
    save_dir = Path(save_dir_raw).expanduser()
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error(
            f"Cannot create office intermediate PDF save directory: {save_dir}",
            exc_info=True,
        )
        return
    stem = Path(original_filename or "upload").stem or "converted"
    destination = save_dir / f"{stem}.pdf"
    if destination.exists():
        destination = save_dir / f"{stem}_{int(time.time())}.pdf"
    try:
        shutil.copy2(temp_pdf_path, destination)
        log.info(f"Saved intermediate PDF (Office conversion) to {destination}")
    except OSError as exc:
        log.error(f"Failed to copy intermediate PDF to {destination}: {exc}", exc_info=True)


def cleanup_temp_dir(path: Path):
    """Cleanup temporary directory."""
    try:
        if path.exists():
            shutil.rmtree(path)
            log.info(f"Cleaned up temporary directory: {path}")
    except OSError as e:
        log.error(f"Error cleaning up temporary directory {path}: {e}")


@router.get("/usage-logs/{log_name}")
async def download_usage_log(log_name: str):
    """Download a detailed token usage JSON written during conversion."""
    try:
        path = resolve_usage_log_file(settings.pdf_usage_log_dir, log_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Usage log not found") from exc
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/json",
    )


@router.post("/convert-pdf")
async def convert_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prompt_template: str | None = Form(None),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
):
    """
    Convert uploaded PDF/DOCX/PPTX to Markdown.

    Args:
        file: PDF, DOCX, or PPTX file to convert
        prompt_template: Prompt template ID or custom prompt string
        api_key: Google Gemini API key (required if not set in environment)
        model: Optional Gemini model override (`gemini-pro-latest` or `gemini-flash-latest`)
    """
    service_metrics.increment("conversion_requests_total")

    if not file.filename:
        service_metrics.increment("conversion_rejected_total")
        raise HTTPException(status_code=400, detail="A file is required")

    input_extension = Path(file.filename).suffix.lower()
    if input_extension not in SUPPORTED_FILE_EXTENSIONS:
        service_metrics.increment("conversion_rejected_total")
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, and PPTX files are supported")

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

    try:
        selected_model = resolve_gemini_model(model)
    except ValueError as exc:
        service_metrics.increment("conversion_rejected_total")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    temp_dir = Path(tempfile.mkdtemp())
    safe_filename = _build_safe_filename(file.filename)
    temp_input_path = temp_dir / safe_filename

    try:
        max_upload_bytes = settings.pdf_max_upload_size_mb * 1024 * 1024
        uploaded_bytes = await _save_upload_file(
            upload_file=file,
            destination_path=temp_input_path,
            max_bytes=max_upload_bytes,
        )
        service_metrics.increment("conversion_uploaded_bytes_total", uploaded_bytes)

        temp_pdf_path = temp_input_path
        if input_extension in {".docx", ".pptx"}:
            log.info(f"Converting Office document to PDF: {file.filename}")
            temp_pdf_path = _convert_office_to_pdf(source_path=temp_input_path, temp_dir=temp_dir)
            _save_office_converted_pdf_copy(temp_pdf_path, file.filename or "upload")

        log.info(f"Processing document: {file.filename}")

        # Initialize parser and exporter with API key
        parser = PDFParser(
            prompt_template=prompt_template,
            api_key=api_key_to_use,
            gemini_model=selected_model,
        )
        md_output_dir = temp_dir / "md_output"
        exporter = MDExporter(output_dir=str(md_output_dir))

        # Parse PDF
        pages_data = parser.parse_pdf(str(temp_pdf_path), prompt_template=prompt_template)

        if not pages_data:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")

        usage_report = build_usage_report(
            model=selected_model,
            source_filename=file.filename or safe_filename,
            pages_data=pages_data,
        )
        usage_log_path = None
        try:
            usage_log_path = write_usage_log(
                usage_report,
                settings.pdf_usage_log_dir,
            )
            log.info(
                "Wrote token usage log",
                extra={
                    "path": str(usage_log_path),
                    "input_tokens": usage_report.input_tokens,
                    "output_tokens": usage_report.output_tokens,
                    "estimated_cost_usd": usage_report.estimated_cost_usd,
                },
            )
        except Exception:
            log.warning("Failed to write token usage log", exc_info=True)

        # Export summary (single MD file)
        summary_path = exporter.export_summary(
            temp_pdf_path,
            pages_data,
            file.filename,
            usage_summary={
                "model": usage_report.model,
                "input_tokens": usage_report.input_tokens,
                "output_tokens": usage_report.output_tokens,
                "thoughts_tokens": usage_report.thoughts_tokens,
                "estimated_cost_usd": usage_report.estimated_cost_usd,
            },
        )

        if not summary_path or not summary_path.exists():
            raise HTTPException(status_code=500, detail="Failed to generate Markdown file")

        # Schedule cleanup after response is sent
        background_tasks.add_task(cleanup_temp_dir, temp_dir)

        service_metrics.increment("conversion_success_total")
        return FileResponse(
            path=summary_path,
            filename=f"{Path(file.filename).stem}.md",
            media_type="text/markdown",
            headers=usage_response_headers(usage_report, usage_log_path),
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
