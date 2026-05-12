document.addEventListener('DOMContentLoaded', () => {
    // 獲取所有必要的 DOM 元素
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const previewConversionArea = document.getElementById('previewConversionArea');
    const previewContainer = document.getElementById('previewContainer');
    const fileName = document.getElementById('fileName');
    const fileStatus = document.getElementById('fileStatus');
    const promptTemplate = document.getElementById('promptTemplate');
    const progressBar = document.getElementById('progressBar');
    const progressContainer = document.getElementById('progressContainer');
    const convertBtn = document.getElementById('convertBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const resetBtn = document.getElementById('resetBtn');
    const resetBtnPreview = document.getElementById('resetBtnPreview');
    const downloadBtnPreview = document.getElementById('downloadBtnPreview');
    const errorMessage = document.getElementById('errorMessage');
    const uploadErrorMessage = document.getElementById('uploadErrorMessage');
    const pdfPreview = document.getElementById('pdfPreview');
    const pdfPreviewEmbed = document.getElementById('pdfPreviewEmbed');
    const pdfPreviewFallback = document.getElementById('pdfPreviewFallback');
    const pdfPreviewError = document.getElementById('pdfPreviewError');
    const pdfDownloadLink = document.getElementById('pdfDownloadLink');
    const markdownPreview = document.getElementById('markdownPreview');
    const promptCustomSection = document.getElementById('promptCustomSection');
    const customPrompt = document.getElementById('customPrompt');
    const promptPreviewContent = document.getElementById('promptPreviewContent');
    const togglePromptPreview = document.getElementById('togglePromptPreview');
    const apiKeyInput = document.getElementById('apiKeyInput');
    const toggleApiKeyVisibility = document.getElementById('toggleApiKeyVisibility');
    const toggleIcon = document.getElementById('toggleIcon');
    const apiKeyErrorMessage = document.getElementById('apiKeyErrorMessage');

    // Prompt 模板定義（與後端同步）
    const PROMPT_TEMPLATES = {
        "slide": `# 角色

你是一個高度精確的資料結構化引擎。你的唯一任務是分析一張簡報投影片的圖片，並將其中所有具備資訊價值的內容，轉換為一個乾淨、結構化的 Markdown 文字檔案。

# 最終目標

產出的文字將直接作為「檢索增強生成 (RAG)」系統的知識庫。因此，輸出的品質標準是最大化「事實密度」與最小化「描述性噪音」。關於純粹美學設計、裝飾性元素的描述，都會降低知識庫的檢索效率，應予以排除。

# 指導原則 (務必遵守)

1.  **資訊優先，設計其次**：你的焦點是文字、數據、表格、以及明確的邏輯關係（如流程圖）。投影片的背景、顏色、裝飾圖形、或版面風格不屬於資訊範疇。
2.  **區分「資訊圖」與「裝飾圖」**：
    * **資訊圖 (需要分析)**：指傳達具體數據或流程的圖，例如：數據圖表、架構圖、流程圖、軟體介面截圖。
    * **裝飾圖 (需要忽略)**：指僅為美化或營造氛圍的圖，例如：無關的庫存照片 (如會議、握手、城市風景)、通用小圖示 (如燈泡、齒輪)、抽象的幾何形狀。

# 指令

請分析提供的投影片圖片，並嚴格按照以下指令，將所有分析結果整合成一份結構化的 Markdown 文件：

1.  **主要標題擷取**: 識別投影片的主要標題，並將其格式化為 H1 標題 (\`#\`)。
2.  **內文與列表擷取**: 按照邏輯閱讀順序，精確擷取所有文字內容。必須保留原始的項目符號 (\`- \`) 或數字列表 (\`1. \`) 格式。
3.  **表格資料提取**: 若有表格，將其完整轉換為 Markdown 表格格式。確保所有欄位和儲存格資料都被精確轉錄。
4.  **流程/架構圖轉譯 (資訊圖分析)**:
    * 若有流程圖、架構圖或任何使用箭頭/方塊表達邏輯關係的圖表：
    * 嚴禁描述形狀或顏色，例如「一個藍色方塊指向一個綠色圓形」。
    * 必須以文字清晰地說明整個流程的步驟、組件的關係、或數據的流向。
    * 例如，將 \`[A: 輸入資料]\` -> \`[B: 驗證資料]\` 轉譯為：「流程開始於『A: 輸入資料』，接著進入下一步『B: 驗證資料』。」
5.  **圖像內容處理 (區分對待)**:
    * 對於「資訊圖」(如軟體截圖、數據圖表)：簡潔地描述其核心內容及功能。例如：「此為軟體的使用者設定介面截圖，顯示了『通知』、『外觀』和『語言』三個可調整的選項。」
    * 對於「裝飾圖」(如庫存照片、通用圖示)：完全忽略，不要在輸出中描述或提及這些圖片。

# 排除項目
* 禁止描述任何純粹的背景設計元素（如抽象形狀、漸層、線條）。
* 禁止對裝飾性圖片或通用圖示進行任何形式的描述或象徵意義分析。
* 禁止使用任何主觀或形容詞類的詞彙來評論投影片的設計風格（例如「現代感」、「專業」、「簡潔」）。

# 輸出格式

請務必使用「繁體中文」，並以單一、連貫的 Markdown 格式提供所有分析後的內容。`,
        "table": `# 任務
你是表格結構化專家。請從圖片中萃取所有表格，轉為 Markdown 表格；若有純文字也需保留原始段落與列表格式。

# 輸出要求
- 保留所有欄位、列順序與數值。
- 若有合併儲存格，重複填寫內容以保持矩陣完整。
- 沒有表格時，輸出一般文字（保留列表格式）。
- 僅使用繁體中文。`,
        "ocr": `# 任務
進行純 OCR 轉寫，盡量還原原文內容與換行，保持 Markdown 簡單段落與列表。

# 輸出要求
- 不要加入主觀描述。
- 列表使用原始的項目符號或數字。
- 僅使用繁體中文。`
    };

    // 驗證關鍵元素是否存在
    const requiredElements = {
        uploadArea,
        fileInput,
        previewConversionArea,
        previewContainer
    };
    
    const missingElements = Object.entries(requiredElements)
        .filter(([name, el]) => !el)
        .map(([name]) => name);
    
    if (missingElements.length > 0) {
        console.error('缺少必要的 DOM 元素:', missingElements);
        alert('頁面載入錯誤，請刷新頁面重試。缺少元素: ' + missingElements.join(', '));
        return;
    }

    console.log('所有必要的 DOM 元素已載入');

    let currentFile = null;
    let downloadUrl = null;
    let pdfPreviewUrl = null;
    let markdownContent = null;
    let promptPreviewExpanded = true;
    const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.pptx'];

    // Prompt 預覽相關函數
    function updatePromptPreview() {
        if (!promptPreviewContent) return;

        const selectedValue = promptTemplate ? promptTemplate.value : 'slide';
        let promptText = '';

        if (selectedValue === 'custom') {
            promptText = customPrompt ? customPrompt.value.trim() : '';
            if (!promptText) {
                promptText = '請在下方輸入您的自訂 prompt';
            }
        } else {
            promptText = PROMPT_TEMPLATES[selectedValue] || PROMPT_TEMPLATES['slide'];
        }

        // 顯示 prompt 內容（使用 <pre> 保持格式）
        promptPreviewContent.innerHTML = `<pre class="prompt-text">${escapeHtml(promptText)}</pre>`;
    }

    function togglePromptPreviewDisplay() {
        if (!promptPreviewContent) return;
        promptPreviewExpanded = !promptPreviewExpanded;
        if (promptPreviewExpanded) {
            promptPreviewContent.style.display = 'block';
            if (togglePromptPreview) {
                togglePromptPreview.textContent = '▼';
                togglePromptPreview.title = '收起';
            }
        } else {
            promptPreviewContent.style.display = 'none';
            if (togglePromptPreview) {
                togglePromptPreview.textContent = '▶';
                togglePromptPreview.title = '展開';
            }
        }
    }

    // 監聽 prompt 模板選擇變化
    if (promptTemplate) {
        promptTemplate.addEventListener('change', () => {
            const selectedValue = promptTemplate.value;
            if (selectedValue === 'custom') {
                if (promptCustomSection) {
                    promptCustomSection.style.display = 'block';
                }
                if (customPrompt) {
                    customPrompt.focus();
                }
            } else {
                if (promptCustomSection) {
                    promptCustomSection.style.display = 'none';
                }
            }
            updatePromptPreview();
        });
    }

    // 監聽自訂 prompt 輸入變化
    if (customPrompt) {
        customPrompt.addEventListener('input', () => {
            if (promptTemplate && promptTemplate.value === 'custom') {
                updatePromptPreview();
            }
        });
    }

    // 監聽 prompt 預覽展開/收起按鈕
    if (togglePromptPreview) {
        togglePromptPreview.addEventListener('click', togglePromptPreviewDisplay);
    }

    // 初始化 prompt 預覽
    updatePromptPreview();

    // API Key 顯示/隱藏切換
    if (toggleApiKeyVisibility && apiKeyInput) {
        toggleApiKeyVisibility.addEventListener('click', () => {
            if (apiKeyInput.type === 'password') {
                apiKeyInput.type = 'text';
                if (toggleIcon) toggleIcon.textContent = '🙈';
            } else {
                apiKeyInput.type = 'password';
                if (toggleIcon) toggleIcon.textContent = '👁️';
            }
        });
    }

    // 驗證 API Key 函數
    function validateApiKey() {
        if (!apiKeyInput) return false;
        const apiKey = apiKeyInput.value.trim();
        if (!apiKey) {
            if (apiKeyErrorMessage) {
                apiKeyErrorMessage.textContent = '請輸入 Gemini API Key';
                apiKeyErrorMessage.style.display = 'block';
            }
            if (apiKeyInput) {
                apiKeyInput.focus();
                apiKeyInput.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
            return false;
        }
        // 簡單驗證：API key 應該至少有一定長度
        if (apiKey.length < 20) {
            if (apiKeyErrorMessage) {
                apiKeyErrorMessage.textContent = 'API Key 格式似乎不正確，請確認是否正確輸入';
                apiKeyErrorMessage.style.display = 'block';
            }
            if (apiKeyInput) {
                apiKeyInput.focus();
            }
            return false;
        }
        if (apiKeyErrorMessage) {
            apiKeyErrorMessage.style.display = 'none';
        }
        return true;
    }

    // Drag and drop handlers
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        uploadArea.classList.add('dragover');
    }

    function unhighlight(e) {
        uploadArea.classList.remove('dragover');
    }

    uploadArea.addEventListener('drop', handleDrop, false);
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFiles);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles({ target: { files: files } });
    }

    function handleFiles(e) {
        const files = e.target.files;
        if (files.length > 0) {
            const file = files[0];
            console.log('處理文件:', {
                name: file.name,
                type: file.type,
                size: file.size
            });
            
            const lowerFileName = file.name.toLowerCase();
            const hasSupportedExtension = SUPPORTED_EXTENSIONS.some(ext => lowerFileName.endsWith(ext));

            if (!hasSupportedExtension) {
                console.warn('文件類型不符合要求:', file.type, file.name);
                if (uploadErrorMessage) {
                    uploadErrorMessage.textContent = `請上傳 PDF、DOCX 或 PPTX 檔案。您上傳的是：${file.type || '未知類型'} (${file.name})`;
                    uploadErrorMessage.style.display = 'block';
                    // 確保錯誤訊息可見
                    uploadErrorMessage.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else {
                    alert('請上傳 PDF、DOCX 或 PPTX 檔案');
                }
                fileInput.value = ''; // 清除選擇
                return;
            }
            
            // 清除上傳區域的錯誤訊息
            if (uploadErrorMessage) {
                uploadErrorMessage.style.display = 'none';
            }
            
            currentFile = file;
            showPreviewArea(file);
        }
    }

    function showPreviewArea(file) {
        console.log('顯示預覽區域，文件:', file.name);
        
        try {
            // 隱藏上傳區域
            if (uploadArea) {
                uploadArea.style.display = 'none';
            }
            
            // 顯示預覽和轉換區域（必須顯示，包含轉換按鈕）
            if (previewConversionArea) {
                previewConversionArea.style.display = 'block';
                previewConversionArea.style.visibility = 'visible';
                previewConversionArea.style.opacity = '1';
                console.log('✓ 顯示 previewConversionArea');
            } else {
                console.error('✗ previewConversionArea 元素不存在');
                // 即使元素不存在，也要確保用戶能看到轉換按鈕
                // 創建一個簡單的轉換區域
                createFallbackConversionArea(file);
                return;
            }
            
            // 嘗試顯示預覽容器（可選，如果失敗不影響轉換功能）
            if (previewContainer) {
                try {
                    previewContainer.style.display = 'block';
                    previewContainer.style.visibility = 'visible';
                    previewContainer.style.opacity = '1';
                    console.log('✓ 顯示 previewContainer');
                } catch (e) {
                    console.warn('預覽容器顯示失敗，但不影響轉換功能:', e);
                }
            }
            
            // 設置文件信息
            if (fileName) fileName.textContent = file.name;
            if (fileStatus) fileStatus.textContent = '準備就緒';
            if (progressBar) progressBar.style.width = '0%';
            if (progressContainer) progressContainer.style.display = 'none';
            
            // 確保轉換按鈕可見且可用
            if (convertBtn) {
                convertBtn.style.display = 'inline-block';
                convertBtn.disabled = false;
                convertBtn.textContent = '開始轉換';
                console.log('✓ 轉換按鈕已顯示');
            } else {
                console.error('✗ convertBtn 元素不存在');
            }
            
            if (downloadBtn) downloadBtn.style.display = 'none';
            if (resetBtn) resetBtn.style.display = 'inline-block';
            if (errorMessage) errorMessage.style.display = 'none';
            
            // 更新 prompt 預覽
            updatePromptPreview();
            
        } catch (error) {
            console.error('顯示預覽區域時發生錯誤:', error);
            // 即使出錯，也要確保轉換按鈕可用
            createFallbackConversionArea(file);
        }
        
        // 清理之前的預覽 URL
        if (pdfPreviewUrl) {
            URL.revokeObjectURL(pdfPreviewUrl);
            pdfPreviewUrl = null;
        }
        
        const isPDFFile = file.name.toLowerCase().endsWith('.pdf');
        if (!isPDFFile) {
            if (pdfPreviewEmbed) {
                pdfPreviewEmbed.style.display = 'none';
                pdfPreviewEmbed.src = '';
            }
            if (pdfPreview) {
                pdfPreview.style.display = 'none';
                pdfPreview.data = '';
            }
            if (pdfPreviewFallback) {
                pdfPreviewFallback.style.display = 'none';
                pdfPreviewFallback.src = '';
            }
            if (pdfPreviewError) {
                pdfPreviewError.innerHTML = '<p style="margin-bottom: 15px;">Office 檔案不提供原始預覽，系統會先轉成 PDF 再轉換為 Markdown。</p>';
                pdfPreviewError.style.display = 'block';
            }
            return;
        }

        // 預覽 PDF - 使用 embed、object 和 iframe 多重備援
        try {
            pdfPreviewUrl = URL.createObjectURL(file);
            const pdfUrl = pdfPreviewUrl + '#toolbar=1';
            console.log('PDF 預覽 URL 已創建:', pdfUrl);
            
            // 隱藏所有預覽元素
            if (pdfPreviewEmbed) {
                pdfPreviewEmbed.style.display = 'none';
                pdfPreviewEmbed.src = '';
            }
            if (pdfPreview) {
                pdfPreview.style.display = 'none';
                pdfPreview.data = '';
            }
            if (pdfPreviewFallback) {
                pdfPreviewFallback.style.display = 'none';
                pdfPreviewFallback.src = '';
            }
            if (pdfPreviewError) {
                pdfPreviewError.style.display = 'none';
            }
            
            // 優先嘗試使用 embed（只顯示一個）
            if (pdfPreviewEmbed) {
                pdfPreviewEmbed.src = pdfUrl + '#toolbar=1&navpanes=0&scrollbar=0';
                pdfPreviewEmbed.style.display = 'block';
                pdfPreviewEmbed.style.width = '100%';
                pdfPreviewEmbed.style.height = '100%';
                pdfPreviewEmbed.style.position = 'absolute';
                pdfPreviewEmbed.style.top = '0';
                pdfPreviewEmbed.style.left = '0';
                pdfPreviewEmbed.style.right = '0';
                pdfPreviewEmbed.style.bottom = '0';
                // 確保其他元素隱藏
                if (pdfPreview) pdfPreview.style.display = 'none';
                if (pdfPreviewFallback) pdfPreviewFallback.style.display = 'none';
                console.log('使用 embed 顯示 PDF');
            } else if (pdfPreview) {
                // 備用：使用 object（只在 embed 不存在時）
                pdfPreview.data = pdfUrl + '#toolbar=1&navpanes=0&scrollbar=0';
                pdfPreview.style.display = 'block';
                pdfPreview.style.width = '100%';
                pdfPreview.style.height = '100%';
                pdfPreview.style.position = 'absolute';
                pdfPreview.style.top = '0';
                pdfPreview.style.left = '0';
                pdfPreview.style.right = '0';
                pdfPreview.style.bottom = '0';
                // 確保其他元素隱藏
                if (pdfPreviewFallback) pdfPreviewFallback.style.display = 'none';
                console.log('使用 object 顯示 PDF');
            } else if (pdfPreviewFallback) {
                // 備用：使用 iframe（只在前面都不存在時）
                pdfPreviewFallback.src = pdfUrl + '#toolbar=1&navpanes=0&scrollbar=0';
                pdfPreviewFallback.style.display = 'block';
                pdfPreviewFallback.style.width = '100%';
                pdfPreviewFallback.style.height = '100%';
                pdfPreviewFallback.style.position = 'absolute';
                pdfPreviewFallback.style.top = '0';
                pdfPreviewFallback.style.left = '0';
                pdfPreviewFallback.style.right = '0';
                pdfPreviewFallback.style.bottom = '0';
                pdfPreviewFallback.setAttribute('scrolling', 'no');
                console.log('使用 iframe 顯示 PDF');
            }
            
            // 設置下載連結
            if (pdfDownloadLink) {
                pdfDownloadLink.href = pdfPreviewUrl;
                pdfDownloadLink.download = file.name;
            }
            
            // 監聽錯誤事件
            if (pdfPreviewEmbed) {
                pdfPreviewEmbed.onerror = () => {
                    console.log('embed 載入失敗，切換到 object');
                    if (pdfPreviewEmbed) pdfPreviewEmbed.style.display = 'none';
                    if (pdfPreview) pdfPreview.style.display = 'block';
                };
            }
            
            if (pdfPreview) {
                pdfPreview.onerror = () => {
                    console.log('object 載入失敗，切換到 iframe');
                    if (pdfPreview) pdfPreview.style.display = 'none';
                    if (pdfPreviewFallback) pdfPreviewFallback.style.display = 'block';
                };
            }
            
            if (pdfPreviewFallback) {
                pdfPreviewFallback.onerror = () => {
                    console.log('iframe 載入失敗，顯示錯誤訊息');
                    if (pdfPreviewFallback) pdfPreviewFallback.style.display = 'none';
                    if (pdfPreviewError) pdfPreviewError.style.display = 'block';
                };
            }
            
        } catch (error) {
            console.error('PDF 預覽錯誤:', error);
            if (pdfPreviewError) {
                pdfPreviewError.style.display = 'block';
            }
            showError('無法預覽 PDF 檔案，請確認檔案格式是否正確');
        }
        
        // 顯示等待轉換提示
        if (markdownPreview) {
            markdownPreview.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: 200px; color: #6b7280;"><p>點擊「開始轉換」按鈕以生成 Markdown</p></div>';
        }
        markdownContent = null;
        
        // 隱藏預覽容器的標題和操作按鈕（轉換完成後再顯示）
        const previewHeader = document.querySelector('.preview-header');
        if (previewHeader) {
            previewHeader.style.display = 'none';
        }
        
        // 確保預覽容器可見
        console.log('預覽容器顯示狀態:', previewContainer.style.display);
        console.log('預覽轉換區域顯示狀態:', previewConversionArea.style.display);
    }

    function showError(msg) {
        if (errorMessage) {
            errorMessage.textContent = msg;
            errorMessage.style.display = 'block';
            // 確保錯誤訊息顯示在可見區域
            errorMessage.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            console.error('錯誤訊息元素不存在:', msg);
            alert(msg); // 備援方案
        }
    }

    function resetAll() {
        currentFile = null;
        fileInput.value = '';
        uploadArea.style.display = 'block';
        previewConversionArea.style.display = 'none';
        previewContainer.style.display = 'none';
        if (pdfPreview) pdfPreview.data = '';
        if (pdfPreviewEmbed) pdfPreviewEmbed.src = '';
        if (pdfPreviewFallback) pdfPreviewFallback.src = '';
        if (pdfPreviewError) pdfPreviewError.style.display = 'none';
        markdownPreview.innerHTML = '';
        markdownContent = null;
        
        // 重置 prompt 相關
        if (promptTemplate) {
            promptTemplate.value = 'slide';
        }
        if (promptCustomSection) {
            promptCustomSection.style.display = 'none';
        }
        if (customPrompt) {
            customPrompt.value = '';
        }
        updatePromptPreview();
        
        // 不清除 API Key（讓用戶可以繼續使用）
        // 如果需要清除，取消下面的註解
        // if (apiKeyInput) {
        //     apiKeyInput.value = '';
        // }
        promptPreviewExpanded = true;
        if (promptPreviewContent) {
            promptPreviewContent.style.display = 'block';
        }
        if (togglePromptPreview) {
            togglePromptPreview.textContent = '▼';
            togglePromptPreview.title = '收起';
        }
        
        const previewHeader = document.querySelector('.preview-header');
        if (previewHeader) {
            previewHeader.style.display = 'none';
        }
        if (downloadUrl) {
            URL.revokeObjectURL(downloadUrl);
            downloadUrl = null;
        }
        if (pdfPreviewUrl) {
            URL.revokeObjectURL(pdfPreviewUrl);
            pdfPreviewUrl = null;
        }
    }

    resetBtn.addEventListener('click', resetAll);
    resetBtnPreview.addEventListener('click', resetAll);

    function setupDownloadButton(blob, filename) {
        downloadUrl = URL.createObjectURL(blob);
        const downloadHandler = () => {
            const a = document.createElement('a');
            a.href = downloadUrl;
            const outputName = filename.replace(/\.[^.]+$/, '') || 'converted';
            a.download = `${outputName}.md`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        };
        
        if (downloadBtn) {
            downloadBtn.onclick = downloadHandler;
        }
        if (downloadBtnPreview) {
            downloadBtnPreview.onclick = downloadHandler;
        }
    }

    convertBtn.addEventListener('click', async () => {
        if (!currentFile) return;

        // 驗證 API Key
        if (!validateApiKey()) {
            return;
        }

        // 驗證自訂 prompt
        if (promptTemplate && promptTemplate.value === 'custom') {
            if (!customPrompt || !customPrompt.value.trim()) {
                showError('請輸入自訂 prompt 內容');
                if (customPrompt) {
                    customPrompt.focus();
                }
                return;
            }
        }

        convertBtn.disabled = true;
        convertBtn.textContent = '轉換中...';
        fileStatus.textContent = '正在轉換文件...';
        progressContainer.style.display = 'block';
        progressBar.style.width = '30%';
        previewConversionArea.classList.add('processing');
        errorMessage.style.display = 'none';
        
        // 更新右側提示
        markdownPreview.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280;"><p>正在轉換中，請稍候...</p></div>';

        // Simulate progress
        let progress = 30;
        const interval = setInterval(() => {
            if (progress < 90) {
                progress += 5;
                progressBar.style.width = `${progress}%`;
            }
        }, 500);

        const formData = new FormData();
        formData.append('file', currentFile);
        
        // 添加 API Key
        if (apiKeyInput && apiKeyInput.value.trim()) {
            formData.append('api_key', apiKeyInput.value.trim());
        }
        
        // 處理 prompt_template：如果是自訂選項，傳送自訂文字；否則傳送模板 ID
        if (promptTemplate && promptTemplate.value) {
            if (promptTemplate.value === 'custom' && customPrompt && customPrompt.value.trim()) {
                // 自訂 prompt：傳送自訂文字
                formData.append('prompt_template', customPrompt.value.trim());
            } else if (promptTemplate.value !== 'custom') {
                // 模板選項：傳送模板 ID
                formData.append('prompt_template', promptTemplate.value);
            }
        }

        try {
            const response = await fetch('/api/v1/convert-pdf', {
                method: 'POST',
                body: formData
            });

            clearInterval(interval);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: '轉換失敗' }));
                throw new Error(errorData.detail || '轉換失敗');
            }

            const blob = await response.blob();
            
            // 讀取 Markdown 內容
            const text = await blob.text();
            markdownContent = text;
            
            // 渲染 Markdown
            if (typeof marked !== 'undefined') {
                markdownPreview.innerHTML = marked.parse(text);
            } else {
                // 如果 marked.js 未加載，顯示純文本
                markdownPreview.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
            }
            
            progressBar.style.width = '100%';
            fileStatus.textContent = '轉換完成！';
            previewConversionArea.classList.remove('processing');
            
            // 顯示預覽容器的標題和操作按鈕
            const previewHeader = document.querySelector('.preview-header');
            if (previewHeader) {
                previewHeader.style.display = 'flex';
            }
            
            // 隱藏轉換控制區域，只顯示預覽區域
            setTimeout(() => {
                previewConversionArea.style.display = 'none';
                setupDownloadButton(blob, currentFile.name);
            }, 500);

        } catch (error) {
            clearInterval(interval);
            previewConversionArea.classList.remove('processing');
            progressBar.style.width = '0%';
            progressContainer.style.display = 'none';
            fileStatus.textContent = '發生錯誤';
            convertBtn.textContent = '重試';
            convertBtn.disabled = false;
            console.error('轉換錯誤:', error);
            showError(error.message || '轉換過程中發生錯誤，請重試');
        }
    });

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // 備援方案：如果主要元素不存在，創建簡單的轉換區域
    function createFallbackConversionArea(file) {
        console.log('創建備援轉換區域');
        
        // 隱藏上傳區域
        if (uploadArea) {
            uploadArea.style.display = 'none';
        }
        
        // 創建簡單的轉換區域
        const fallbackArea = document.createElement('div');
        fallbackArea.className = 'preview-conversion-area';
        fallbackArea.style.cssText = 'margin-top: 30px; padding: 20px; background: #f9fafb; border-radius: 12px; border: 1px solid #e5e7eb;';
        fallbackArea.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <div>
                    <strong>${escapeHtml(file.name)}</strong>
                    <span style="color: #3b82f6; margin-left: 10px;">準備就緒</span>
                </div>
                <div>
                    <button id="fallbackConvertBtn" class="btn primary-btn" style="margin-right: 10px;">開始轉換</button>
                    <button id="fallbackResetBtn" class="btn secondary-btn">重新選擇</button>
                </div>
            </div>
            <div id="fallbackProgressContainer" style="display: none; height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; margin-bottom: 20px;">
                <div id="fallbackProgressBar" style="height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6); width: 0%; transition: width 0.4s ease;"></div>
            </div>
            <div id="fallbackErrorMessage" class="error-message" style="display: none;"></div>
        `;
        
        // 插入到 main 中
        const main = document.querySelector('main');
        if (main) {
            main.appendChild(fallbackArea);
            
            // 設置事件處理
            const fallbackConvertBtn = document.getElementById('fallbackConvertBtn');
            const fallbackResetBtn = document.getElementById('fallbackResetBtn');
            
            if (fallbackConvertBtn && convertBtn) {
                fallbackConvertBtn.onclick = () => {
                    if (convertBtn && !convertBtn.disabled) {
                        convertBtn.click();
                    } else {
                        // 直接觸發轉換
                        const clickEvent = new MouseEvent('click', { bubbles: true });
                        convertBtn.dispatchEvent(clickEvent);
                    }
                };
            }
            
            if (fallbackResetBtn) {
                fallbackResetBtn.onclick = () => {
                    resetAll();
                    fallbackArea.remove();
                };
            }
        }
    }
});
