# 環境變數範例

將以下內容複製為 `.env` 並填入實際值：

```
GOOGLE_API_KEY=your-google-api-key-here
GEMINI_MODEL=gemini-flash-latest
# Supported values: gemini-pro-latest, gemini-flash-latest

# PDF Processing
# Density = chars / (page width * height in PDF points). Used only if PDF_GEMINI_ON_LOW_TEXT_DENSITY=true.
PDF_TEXT_DENSITY_THRESHOLD=0.0008
# Legacy behavior: route to Gemini when density is below the threshold (often sends almost every page).
PDF_GEMINI_ON_LOW_TEXT_DENSITY=false
# Tables/charts: PyMuPDF signals (tabular text, vector paths, embedded images) -> Gemini when true.
PDF_GEMINI_ON_VISUAL_STRUCTURE=true
# Minimum PyMuPDF drawing records on a page to treat as vector chart/diagram.
PDF_GEMINI_VECTOR_PATH_MIN=40
# Image bbox area / page area; 0 = any embedded image counts. Example 0.015 = 1.5% of page.
PDF_GEMINI_EMBEDDED_IMAGE_AREA_RATIO_MIN=0.0
# Fewer extracted characters than this -> Gemini (covers title slides / scanned sparse pages).
PDF_GEMINI_IF_CHARS_BELOW=55
PDF_MAX_WORKERS=4
PDF_MAX_PROCESSES=2
PDF_MAX_REQUESTS_PER_SECOND=50
PDF_FORCE_PYMUPDF=false
PDF_MAX_UPLOAD_SIZE_MB=25
PDF_RETRY_ENABLED=true
PDF_RETRY_MAX_ATTEMPTS=3
PDF_RETRY_INITIAL_DELAY=1.0
PDF_RETRY_MAX_DELAY=60.0
PDF_RETRY_EXPONENTIAL_BASE=2.0
PDF_RETRY_JITTER=true
PDF_GRACEFUL_DEGRADATION_ENABLED=true
PDF_CIRCUIT_BREAKER_ENABLED=true
PDF_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
PDF_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60.0
OFFICE_CONVERTER_BIN=soffice
OFFICE_CONVERSION_TIMEOUT_SECONDS=120
# After DOCX/PPTX -> PDF, copy that PDF here (leave empty to disable)
OFFICE_INTERMEDIATE_PDF_SAVE_DIR=

# Cache
PDF_CACHE_ENABLED=true
PDF_CACHE_DIR=./data/pdf_cache
# Token usage JSON logs (totals + per-page); estimate USD from public Gemini rates
PDF_USAGE_LOG_DIR=./data/usage_logs
# Preserve Gemini vision page rasters as assets/pNN.png (API returns zip when present)
PDF_PRESERVE_VISION_ASSETS=true
PDF_VISION_ASSET_DPI=150

# Logging
LOG_LEVEL=INFO
LOG_FILE=
JSON_LOGS=false
STRUCTURED_LOGGING=true

# Server
API_HOST=0.0.0.0
API_PORT=8000
```

