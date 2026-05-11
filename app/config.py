"""Configuration for PDF to Markdown Converter (standalone)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    gemini_model: str = "gemini-pro-latest"

    # PDF Processing
    pdf_text_density_threshold: float = 0.02
    pdf_max_workers: int = 4
    pdf_max_processes: int = 2
    pdf_max_requests_per_second: int = 50
    pdf_force_pymupdf: bool = False
    pdf_max_upload_size_mb: int = 25

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

    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = ""
    json_logs: bool = False
    structured_logging: bool = True

    # Server Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
