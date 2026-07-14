"""Configuration for PDF to Markdown Converter (standalone)."""
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
SUPPORTED_GEMINI_MODELS = (
    "gemini-pro-latest",
    "gemini-flash-latest",
)


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Google API Configuration (required for Gemini vision)
    google_api_key: str = ""

    # Model Configuration
    gemini_model: str = DEFAULT_GEMINI_MODEL

    # PDF Processing
    # chars / (page width * height in PDF points). Old default 0.02 required ~10k chars on A4
    # to stay on PyMuPDF; routing now uses this only when pdf_gemini_on_low_text_density is True.
    pdf_text_density_threshold: float = 0.0008
    # When True, pages with density below pdf_text_density_threshold use Gemini (legacy-style gate).
    pdf_gemini_on_low_text_density: bool = False
    # When True, route pages with tables/charts signals to Gemini (text tabs/spaces,
    # many vector paths, or large embedded images).
    pdf_gemini_on_visual_structure: bool = True
    # Minimum vector drawing ops (PyMuPDF get_drawings length) to treat as chart/diagram.
    pdf_gemini_vector_path_min: int = 40
    # Embedded image bbox area / page area must reach this ratio to count (0 = any image).
    pdf_gemini_embedded_image_area_ratio_min: float = 0.0
    # When PyMuPDF extracted fewer than this many non-whitespace characters, try Gemini vision.
    pdf_gemini_if_chars_below: int = 55
    pdf_max_workers: int = 4
    pdf_max_processes: int = 2
    pdf_max_requests_per_second: int = 50
    pdf_force_pymupdf: bool = False
    pdf_max_upload_size_mb: int = 25
    office_converter_bin: str = "soffice"
    office_conversion_timeout_seconds: int = 120
    # When set, after DOCX/PPTX -> PDF conversion, copy the intermediate PDF here (empty = disabled).
    office_intermediate_pdf_save_dir: str = ""

    # Reliability and fallback behavior
    pdf_retry_enabled: bool = True
    pdf_retry_max_attempts: int = 3
    pdf_retry_initial_delay: float = 1.0
    pdf_retry_max_delay: float = 60.0
    pdf_retry_exponential_base: float = 2.0
    pdf_retry_jitter: bool = True
    pdf_graceful_degradation_enabled: bool = True
    pdf_circuit_breaker_enabled: bool = True
    pdf_circuit_breaker_failure_threshold: int = 5
    pdf_circuit_breaker_recovery_timeout: float = 60.0

    # Cache Configuration
    pdf_cache_enabled: bool = True
    pdf_cache_dir: str = "./data/pdf_cache"
    # Per-conversion token usage JSON (totals + per-page). Still covered by data/ in .gitignore.
    pdf_usage_log_dir: str = "./data/usage_logs"

    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = ""
    json_logs: bool = False
    structured_logging: bool = True

    # Server Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()


def resolve_gemini_model(selected_model: str | None) -> str:
    """Return a validated Gemini model name, falling back to configured default."""
    requested = (selected_model or "").strip().lower()
    configured = (settings.gemini_model or "").strip().lower()
    candidate = requested or configured or DEFAULT_GEMINI_MODEL
    if candidate not in SUPPORTED_GEMINI_MODELS:
        allowed = ", ".join(SUPPORTED_GEMINI_MODELS)
        raise ValueError(f"Unsupported Gemini model: {candidate}. Allowed values: {allowed}")
    return candidate
