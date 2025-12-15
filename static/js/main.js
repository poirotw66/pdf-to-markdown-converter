document.addEventListener('DOMContentLoaded', () => {
    // 獲取所有必要的 DOM 元素
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const previewConversionArea = document.getElementById('previewConversionArea');
    const previewContainer = document.getElementById('previewContainer');
    const fileName = document.getElementById('fileName');
    const fileStatus = document.getElementById('fileStatus');
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
            
            // 檢查文件類型（允許 PDF 或沒有類型的情況，因為某些瀏覽器可能不正確識別 PDF）
            const isPDF = file.type === 'application/pdf' || 
                         file.name.toLowerCase().endsWith('.pdf') ||
                         (file.type === '' && file.name.toLowerCase().endsWith('.pdf'));
            
            if (!isPDF) {
                console.warn('文件類型不符合要求:', file.type, file.name);
                if (uploadErrorMessage) {
                    uploadErrorMessage.textContent = `請上傳 PDF 檔案（.pdf 格式）。您上傳的是：${file.type || '未知類型'} (${file.name})`;
                    uploadErrorMessage.style.display = 'block';
                    // 確保錯誤訊息可見
                    uploadErrorMessage.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else {
                    alert('請上傳 PDF 檔案（.pdf 格式）');
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
            a.download = filename.replace('.pdf', '.md');
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

        convertBtn.disabled = true;
        convertBtn.textContent = '轉換中...';
        fileStatus.textContent = '正在轉換 PDF...';
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
