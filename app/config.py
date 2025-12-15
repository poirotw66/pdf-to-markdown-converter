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
    gemini_model: str = "gemini-2.5-pro"

    # PDF Processing
    pdf_text_density_threshold: float = 0.02
    pdf_max_workers: int = 4
    pdf_max_processes: int = 2
    pdf_max_requests_per_second: int = 50
    pdf_force_pymupdf: bool = False

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

