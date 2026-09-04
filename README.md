# PDF to Markdown Converter (Standalone)

將 PDF 文件轉換為結構化的 Markdown 格式，內建前端介面與後端 API。

## 📌 關於文件結構化

在文件處理流程中，我們將 PDF、Word、PPT、圖片與其他非結構化文件轉換為 **Markdown** 格式，以便後續進行 AI 解析、RAG 構建與內容分析。此步驟並非傳統的「資料清洗」，而是 **將非結構化內容標準化、格式化、可解析化** 的前置工程。

**文件結構化的核心，是將非結構化文件轉換為 LLM 最能理解、最能高效解析的格式──Markdown。**

## 📘 為什麼選擇 Markdown？

根據 MarkItDown 的設計理念，Markdown 之所以被選為核心輸出格式，是因為：

### **1. Markdown 接近純文字，但能保留重要結構**

* 具備標題、段落、清單、表格、連結等輕量結構表示法
* 適合表示文件的重要資訊，而不會像 HTML/PDF 那麼冗長
* 在 token 成本與解析便利性之間達到最佳平衡

### **2. LLM 天生對 Markdown 非常熟悉**

> 主流 LLM（如 GPT、Gemini）「原生理解 Markdown」，並且常在回答時自動使用 Markdown。  
> 代表模型在訓練過程中大量接觸 Markdown，能自然解析其結構與語意。

因此 Markdown 是目前最適合作為 **文件 → LLM 的中間層格式**。

### **3. Markdown 對 LLM 來說極度 token-efficient**

比 PDF/XML/HTML 少非常多的無用標記，因此：

* token 花費大幅降低
* 模型上下文更乾淨
* 對 RAG、摘要、QA 解析的效果更好

### **4. Markdown 是結構化但不複雜的格式**

文件經過 Markdown 化後：

* 標題層級井然有序
* 表格可由模型準確閱讀
* 段落、清單等語意清晰
* 不需要繁重的 parser 就能被 AI 使用

有助於 RAG pipeline、embedding、index 建立更準確。

## 功能特點

- 📄 PDF / DOCX / PPTX 上傳與轉換（Office 會先轉 PDF）
- 👁️ 即時 PDF 預覽
- 📝 Markdown 預覽渲染
- 🔄 左右分欄對比
- 💾 一鍵下載轉換結果
- 🎨 可自訂 Prompt 樣板
- ⚡ 混合解析策略（PyMuPDF 快速路徑 + Gemini Vision）

## 專案結構

```
pdf-to-markdown-converter/
├── app/
│   ├── main.py              # FastAPI 主程式
│   ├── config.py            # 配置（.env）
│   └── api/
│       └── pdf_convert.py   # PDF 轉換 API
├── src/utils/               # 工具模組
│   ├── pdf_parser.py        # PDF 解析器（混合策略）
│   ├── pdf_cache.py          # PDF 快取機制
│   ├── md_exporter.py        # Markdown 匯出器
│   ├── prompts.py            # Prompt 樣板管理
│   ├── logging_config.py     # 日誌配置
│   └── retry.py              # 重試機制
├── static/                   # 前端介面
│   ├── converter.html        # 主頁面
│   ├── css/
│   │   └── style.css         # 樣式表
│   └── js/
│       └── main.js           # 前端邏輯
├── pyproject.toml           # 專案與依賴定義（uv）
├── uv.lock                  # 依賴鎖定檔
├── ENV_EXAMPLE.md           # 環境變數範例
├── 文件結構化.md            # 文件結構化說明文件
└── README.md                # 本文件
```

## 安裝

先安裝 [uv](https://docs.astral.sh/uv/getting-started/installation/)，再同步依賴：

```bash
# 若尚未安裝 uv（擇一）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 或：brew install uv

uv sync
```

`uv sync` 會自動建立 `.venv` 並安裝 `pyproject.toml` / `uv.lock` 中的依賴。開發與測試可加上：

```bash
uv sync --group dev
```

系統依賴：poppler
```bash
# macOS
brew install poppler
# Ubuntu/Debian
sudo apt-get install poppler-utils
```

若要支援 DOCX / PPTX，需安裝 LibreOffice（用於先轉 PDF）：
```bash
# macOS
brew install --cask libreoffice
# Ubuntu/Debian
sudo apt-get install libreoffice
```

## 環境變數

請依 `ENV_EXAMPLE.md` 建立 `.env`，至少需設定：

```env
GOOGLE_API_KEY=your-google-api-key
GEMINI_MODEL=gemini-flash-latest
```

`GEMINI_MODEL` 目前支援：`gemini-pro-latest`、`gemini-flash-latest`。

### 可選配置

```env
# PDF 處理配置
# 密度 = 擷取字元數 / (頁面寬×高，PDF points)。舊版預設 0.02 在 A4 上約需上萬字才「不算低密度」，幾乎整份都走 Gemini。
# 僅在 PDF_GEMINI_ON_LOW_TEXT_DENSITY=true 時會用此閾值做路由。
PDF_TEXT_DENSITY_THRESHOLD=0.0008
PDF_GEMINI_ON_LOW_TEXT_DENSITY=false   # true 時恢復「低密度即走 Vision」行為（類似舊版）
PDF_GEMINI_ON_VISUAL_STRUCTURE=true    # 表格／圖表類訊號（文字 tab、向量圖、嵌入圖）走 Gemini
PDF_GEMINI_VECTOR_PATH_MIN=40          # 單頁向量繪圖筆數門檻（圖表常較高）
PDF_GEMINI_EMBEDDED_IMAGE_AREA_RATIO_MIN=0.0  # 嵌入圖面積占頁面比例；0 表示任一幅圖即視為圖表頁
PDF_GEMINI_IF_CHARS_BELOW=55           # PyMuPDF 擷取字數低於此則走 Vision（封面、掃描稀疏頁）
PDF_MAX_WORKERS=4                # 最大工作線程數
PDF_MAX_PROCESSES=2               # 最大進程數
PDF_MAX_REQUESTS_PER_SECOND=50    # Gemini API 每秒最大請求數
PDF_FORCE_PYMUPDF=false           # 強制僅使用 PyMuPDF
PDF_MAX_UPLOAD_SIZE_MB=25         # 單檔上傳大小上限（MB）
PDF_RETRY_ENABLED=true            # 啟用重試
PDF_RETRY_MAX_ATTEMPTS=3          # 最大重試次數
PDF_RETRY_INITIAL_DELAY=1.0       # 初始重試延遲秒數
PDF_RETRY_MAX_DELAY=60.0          # 最大重試延遲秒數
PDF_RETRY_EXPONENTIAL_BASE=2.0    # 重試退避倍數
PDF_RETRY_JITTER=true             # 重試是否加入隨機抖動
PDF_GRACEFUL_DEGRADATION_ENABLED=true         # 啟用優雅降級
PDF_CIRCUIT_BREAKER_ENABLED=true              # 啟用斷路器
PDF_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5       # 斷路器失敗閾值
PDF_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60.0     # 斷路器恢復秒數
OFFICE_CONVERTER_BIN=soffice                  # Office 轉 PDF 執行檔（macOS Homebrew 常為 soffice；Linux 亦可）
OFFICE_CONVERSION_TIMEOUT_SECONDS=120          # Office 轉 PDF 逾時秒數
OFFICE_INTERMEDIATE_PDF_SAVE_DIR=               # 選填：DOCX/PPTX 轉出的中繼 PDF 要複製到的目錄（空則不儲存）

# 快取配置
PDF_CACHE_ENABLED=true            # 啟用快取
PDF_CACHE_DIR=./data/pdf_cache    # 快取目錄

# 日誌配置
LOG_LEVEL=INFO                    # 日誌級別
LOG_FILE=                         # 日誌文件（空則輸出到控制台）
JSON_LOGS=false                   # JSON 格式日誌
STRUCTURED_LOGGING=true           # 結構化日誌

# 伺服器配置
API_HOST=0.0.0.0                 # API 主機
API_PORT=8000                     # API 端口
```

## 啟動

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 或
uv run python -m app.main
```

執行測試：

```bash
uv run pytest
```

### 訪問地址

* **前端介面**：http://localhost:8000/
* **健康檢查**：http://localhost:8000/health
* **基本指標**：http://localhost:8000/metrics
* **轉換 API**：POST http://localhost:8000/api/v1/convert-pdf

### API 使用範例

```bash
# 使用預設樣板（支援 .pdf / .docx / .pptx）
curl -X POST "http://localhost:8000/api/v1/convert-pdf" \
  -F "file=@document.pdf" \
  -F "prompt_template=slide"

# 使用自訂 prompt
curl -X POST "http://localhost:8000/api/v1/convert-pdf" \
  -F "file=@document.pdf" \
  -F "prompt_template=你的自訂 prompt 內容"

# 指定 Gemini 模型
curl -X POST "http://localhost:8000/api/v1/convert-pdf" \
   -F "file=@document.pdf" \
   -F "model=gemini-flash-latest"
```

### 批次腳本

```bash
python scripts/test_docx_convert.py --batch-dir test --recursive --workers 4 --model gemini-flash-latest
```

### Prompt 樣板選項

* `slide` - 簡報/一般（預設）
* `table` - 表格強化
* `ocr` - 純 OCR
* 自訂文字 - 直接輸入自訂 prompt

## 技術架構

### 解析策略

本專案採用**混合解析策略**，結合兩種方法的優勢：

1. **PyMuPDF 快速路徑**：多數內容頁直接擷取文字，速度快、成本低
2. **Gemini Vision**：擷取字數過少、偵測到**表格／圖表類版面訊號**（tab／多空格文字、大量向量繪圖、嵌入圖片），或你手動開啟的「低密度」規則成立時，使用視覺模型

預設**不再**用「密度 < 0.02」當主路由。需要舊行為時，請在 `.env` 設定 `PDF_GEMINI_ON_LOW_TEXT_DENSITY=true` 並調整 `PDF_TEXT_DENSITY_THRESHOLD`。  
圖表／表格相關路由見 `PDF_GEMINI_ON_VISUAL_STRUCTURE` 與 `PDF_GEMINI_VECTOR_PATH_MIN`、`PDF_GEMINI_EMBEDDED_IMAGE_AREA_RATIO_MIN`。

### 主要依賴

* **Web 框架**：FastAPI, Uvicorn
* **PDF 處理**：PyMuPDF (fitz), pdf2image, Pillow
* **AI 模型**：google-genai (Gemini Vision)
* **配置管理**：pydantic-settings, python-dotenv
* **日誌系統**：loguru
* **前端**：原生 HTML/CSS/JavaScript (Marked.js for Markdown rendering)

### 核心功能

* ✅ 智能文字密度檢測
* ✅ 自動快取機制（支援斷點續傳）
* ✅ 重試機制與斷路器
* ✅ 多進程圖片轉換 + 多線程 API 調用
* ✅ 速率限制保護
* ✅ 結構化日誌記錄
* ✅ 每次轉換記錄 Gemini token（input／output）與估算 USD（Markdown 標頭 + `data/usage_logs/`）

## 使用場景

* **RAG 系統**：將 PDF 文件轉換為 Markdown 後進行 embedding 和檢索
* **AI 分析**：為 LLM 提供結構化的文件內容
* **文件處理**：批量處理 PDF 文件，提取結構化內容
* **知識庫構建**：將非結構化文件轉換為可索引的 Markdown 格式

## 部署到 Render

本專案可以輕鬆部署到 [Render](https://render.com) 平台。

### 部署步驟

1. **準備 GitHub 倉庫**
   - 確保所有代碼已推送到 GitHub
   - 確認包含 `Dockerfile`、`.dockerignore` 和 `render.yaml`

2. **在 Render 創建新服務**
   - 登入 [Render Dashboard](https://dashboard.render.com)
   - 點擊 "New +" → "Web Service"
   - 連接你的 GitHub 倉庫

3. **配置服務**
   - **Name**: `pdf-to-markdown-converter`（或自訂名稱）
   - **Environment**: `Docker`
   - **Region**: 選擇最接近你的區域
   - **Branch**: `main`（或你的主分支）
   - **Root Directory**: 留空（使用根目錄）
   - **Dockerfile Path**: `./Dockerfile`
   - **Docker Context**: `.`

4. **環境變數（可選）**
   - 由於現在用戶需要在前端輸入自己的 API key，**不需要**設置 `GOOGLE_API_KEY`
   - 如果需要後備選項，可以在 Render Dashboard 的 Environment 頁面設置：
     - `GOOGLE_API_KEY`: 你的 Gemini API key（可選，作為後備）

5. **計劃選擇**
   - 選擇 **Free** 計劃（免費方案）
   - 免費方案限制：512MB RAM，每月 750 小時運行時間

6. **部署**
   - 點擊 "Create Web Service"
   - Render 會自動開始構建和部署
   - 構建過程可能需要 5-10 分鐘

7. **訪問應用**
   - 部署完成後，Render 會提供一個 URL（例如：`https://pdf-to-markdown-converter.onrender.com`）
   - 訪問該 URL 即可使用應用

### 注意事項

- **免費方案限制**：
  - 應用在 15 分鐘無活動後會進入休眠狀態
  - 首次訪問休眠應用需要約 30-60 秒喚醒時間
  - 每月 750 小時運行時間（約 31 天）

- **API Key**：
  - 用戶需要在前端輸入自己的 Google Gemini API key
  - 可以在 [Google AI Studio](https://makersuite.google.com/app/apikey) 免費取得 API key

- **健康檢查**：
  - Render 會自動使用 `/health` 端點進行健康檢查

### 升級到付費計劃

如果需要更穩定的服務（無休眠、更多資源），可以升級到付費計劃：
- **Starter**: $7/月，512MB RAM，無休眠
- **Standard**: $25/月，2GB RAM，無休眠

## 授權

依原專案授權。

