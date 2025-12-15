# 環境變數範例

將以下內容複製為 `.env` 並填入實際值：

```
GOOGLE_API_KEY=your-google-api-key-here
GEMINI_MODEL=gemini-2.5-pro

# PDF Processing
PDF_TEXT_DENSITY_THRESHOLD=0.02
PDF_MAX_WORKERS=4
PDF_MAX_PROCESSES=2
PDF_MAX_REQUESTS_PER_SECOND=50

# Cache
PDF_CACHE_ENABLED=true
PDF_CACHE_DIR=./data/pdf_cache

# Logging
LOG_LEVEL=INFO
LOG_FILE=
JSON_LOGS=false
STRUCTURED_LOGGING=true

# Server
API_HOST=0.0.0.0
API_PORT=8000
```

