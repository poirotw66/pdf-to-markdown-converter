# PDF to Markdown Converter (Standalone)

將 PDF 文件轉換為結構化的 Markdown 格式，內建前端介面與後端 API。

## 功能特點
- 📄 PDF 上傳與轉換
- 👁️ 即時 PDF 預覽
- 📝 Markdown 預覽渲染
- 🔄 左右分欄對比
- 💾 一鍵下載轉換結果

## 專案結構
```
pdf-to-markdown-converter/
├── app/
│   ├── main.py              # FastAPI 主程式
│   ├── config.py            # 配置（.env）
│   └── api/
│       └── pdf_convert.py   # PDF 轉換 API
├── src/utils/               # 工具模組 (parser/exporter/cache/logging/retry)
├── static/                  # 前端介面 (converter.html + css/js)
├── requirements.txt
├── ENV_EXAMPLE.md           # 環境變數範例
└── README.md
```

## 安裝
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

系統依賴：poppler
```bash
# macOS
brew install poppler
# Ubuntu/Debian
sudo apt-get install poppler-utils
```

## 環境變數
請依 `ENV_EXAMPLE.md` 建立 `.env`，至少需設定：
```
GOOGLE_API_KEY=your-google-api-key
GEMINI_MODEL=gemini-2.5-pro
```

## 啟動
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 或
python -m app.main
```
前端介面：http://localhost:8000/  
轉換 API：POST http://localhost:8000/api/v1/convert-pdf (multipart/form-data, file=PDF)

## 主要依賴
- FastAPI, Uvicorn
- PyMuPDF, pdf2image, Pillow
- google-generativeai (Gemini Vision)
- loguru, pydantic-settings

## 授權
依原專案授權。

