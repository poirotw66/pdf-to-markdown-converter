# 使用 Python 3.11 作為基礎映像
FROM python:3.11-slim

# 設置工作目錄
WORKDIR /app

# 安裝系統依賴（poppler 用於 PDF 處理）
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴文件
COPY requirements.txt .

# 安裝 Python 依賴
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY . .

# 暴露端口（Render 會自動設置 PORT 環境變數）
EXPOSE 8000

# 啟動命令
# Render 會自動設置 PORT 環境變數，main.py 中已經處理了 PORT 環境變數
# 使用 shell 形式以支持環境變數
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

