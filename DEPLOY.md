# Render 部署指南

## 快速部署步驟

### 1. 準備 GitHub 倉庫
```bash
# 確保所有更改已提交
git add .
git commit -m "準備部署到 Render"
git push origin main
```

### 2. 在 Render 創建服務

1. 訪問 [Render Dashboard](https://dashboard.render.com)
2. 點擊 **"New +"** → **"Web Service"**
3. 連接你的 GitHub 帳號（如果還沒連接）
4. 選擇你的倉庫：`pdf-to-markdown-converter`

### 3. 配置服務設置

**基本設置：**
- **Name**: `pdf-to-markdown-converter`
- **Environment**: 選擇 **Docker**
- **Region**: 選擇最接近你的區域（例如：Singapore）
- **Branch**: `main`
- **Root Directory**: 留空
- **Dockerfile Path**: `./Dockerfile`
- **Docker Context**: `.`

**計劃：**
- 選擇 **Free** 計劃（免費）

**環境變數（可選）：**
- 由於用戶需要在前端輸入 API key，**不需要**設置 `GOOGLE_API_KEY`
- 如果需要後備選項，可以設置：
  - Key: `GOOGLE_API_KEY`
  - Value: 你的 Gemini API key（可選）

### 4. 部署

1. 點擊 **"Create Web Service"**
2. Render 會自動開始構建
3. 構建過程約需 5-10 分鐘
4. 構建完成後，應用會自動啟動

### 5. 訪問應用

- 部署完成後，Render 會提供一個 URL
- 格式：`https://pdf-to-markdown-converter.onrender.com`
- 訪問該 URL 即可使用

## 重要提示

### 免費方案限制
- ⚠️ 應用在 **15 分鐘無活動** 後會進入休眠
- ⚠️ 首次訪問休眠應用需要 **30-60 秒** 喚醒時間
- ⚠️ 每月 **750 小時** 運行時間（約 31 天）

### API Key 說明
- 用戶需要在前端輸入自己的 Google Gemini API key
- 可以在 [Google AI Studio](https://makersuite.google.com/app/apikey) 免費取得
- 不需要在 Render 環境變數中設置（除非需要後備選項）

### 健康檢查
- Render 會自動使用 `/health` 端點進行健康檢查
- 如果健康檢查失敗，服務會自動重啟

## 故障排除

### 構建失敗
1. 檢查 Dockerfile 是否正確
2. 檢查 requirements.txt 是否完整
3. 查看 Render 的構建日誌

### 應用無法啟動
1. 檢查環境變數設置
2. 查看應用日誌（Render Dashboard → Logs）
3. 確認端口設置正確（Render 會自動設置 PORT）

### 應用休眠
- 這是免費方案的正常行為
- 首次訪問需要等待 30-60 秒喚醒
- 考慮升級到付費計劃以獲得無休眠服務

## 升級到付費計劃

如果需要更穩定的服務：
- **Starter**: $7/月，512MB RAM，無休眠
- **Standard**: $25/月，2GB RAM，無休眠

在 Render Dashboard → Settings → Plan 中可以升級。

## 自動部署

- Render 預設會監聽 GitHub push 事件
- 當你推送到 main 分支時，會自動觸發重新部署
- 可以在 Settings → Auto-Deploy 中配置

