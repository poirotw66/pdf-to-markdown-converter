"""PDF to Markdown Converter - Standalone FastAPI Application."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.pdf_convert import router as pdf_convert_router
from app.config import settings
from app.metrics import service_metrics

# Initialize logging
from src.utils.logging_config import setup_logging

setup_logging(
    log_level=settings.log_level,
    log_file=settings.log_file if settings.log_file else None,
    json_logs=settings.json_logs,
    structured=settings.structured_logging,
)

app = FastAPI(
    title="PDF to Markdown Converter",
    description="Convert PDF files to structured Markdown format",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
static_dir = Path("static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(pdf_convert_router, prefix="/api/v1", tags=["PDF Converter"])


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the converter UI."""
    converter_path = static_dir / "converter.html"
    if converter_path.exists():
        return HTMLResponse(converter_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>PDF to Markdown Converter</h1><p>Missing static/converter.html</p>")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "pdf-to-markdown-converter",
        "version": "1.0.0",
    }


@app.get("/metrics")
async def metrics():
    """Basic in-memory metrics endpoint."""
    return service_metrics.snapshot()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", str(settings.api_port)))
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=port,
        reload=True,
    )
