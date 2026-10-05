
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const fileNameDisplay = document.getElementById('fileNameDisplay');
        const submitBtn = document.getElementById('submitBtn');
        const statusDiv = document.getElementById('status');
        const outlineEditorBtnGroup = document.getElementById('outlineEditorBtnGroup');
        const outlineEditorBtn = document.getElementById('outlineEditorBtn');

        const templateInput = document.getElementById('templateInput');
        const templateUploadStatus = document.getElementById('templateUploadStatus');
        const currentTemplateName = document.getElementById('currentTemplateName');

        // Preview & Sliders
        const previewContainer = document.getElementById('previewContainer');
        const previewImage = document.getElementById('previewImage');
        const headerSlider = document.getElementById('headerSlider');
        const footerSlider = document.getElementById('footerSlider');
        const leftSlider = document.getElementById('leftSlider');
        const rightSlider = document.getElementById('rightSlider');
        const headerVal = document.getElementById('headerVal');
        const footerVal = document.getElementById('footerVal');
        const leftVal = document.getElementById('leftVal');
        const rightVal = document.getElementById('rightVal');
        const prevPageBtn = document.getElementById('prevPageBtn');
        const nextPageBtn = document.getElementById('nextPageBtn');
        const previewPageDisplay = document.getElementById('previewPageDisplay');
        const totalPagesDisplay = document.getElementById('totalPagesDisplay');

        let currentFile = null;
        let currentFileId = null;
        let currentFileOrigName = "";
        let currentPreviewPage = 1;
        let totalPdfPages = 1;
        let debounceTimer = null;

        // Fetch current template on load
        async function loadCurrentTemplate() {
            try {
                const res = await fetch('/api/get_current_template');
                const data = await res.json();
                currentTemplateName.textContent = data.name;
                if (data.has_custom) {
                    currentTemplateName.style.color = '#ea580c';
                }
                fetchTemplateStyles();
            } catch (err) {
                currentTemplateName.textContent = '無法取得狀態';
            }
        }

        async function fetchTemplateStyles() {
            try {
                const res = await fetch('/api/get_template_styles');
                const data = await res.json();
                if (data.status === 'success' && data.styles.length > 0) {
                    const h1 = document.getElementById('h1Style');
                    const h2 = document.getElementById('h2Style');
                    const h3 = document.getElementById('h3Style');
                    const imgCaption = document.getElementById('imageCaptionStyle');
                    const kaiti = document.getElementById('kaitiStyle');

                    h1.innerHTML = '<option value="">(預設 Heading 1)</option>';
                    h2.innerHTML = '<option value="">(預設 Heading 2)</option>';
                    h3.innerHTML = '<option value="">(預設 Heading 3)</option>';
                    imgCaption.innerHTML = '<option value="">(不套用自訂樣式)</option>';
                    kaiti.innerHTML = '<option value="">(不套用自訂樣式)</option>';

                    data.styles.forEach(s => {
                        const opt = `<option value="${s}">${s}</option>`;
                        h1.innerHTML += opt;
                        h2.innerHTML += opt;
                        h3.innerHTML += opt;
                        imgCaption.innerHTML += opt;
                        kaiti.innerHTML += opt;
                    });

                    document.getElementById('styleMappingSection').style.display = 'block';
                }
            } catch (err) {
                console.error("無法取得樣式", err);
            }
        }
        window.addEventListener('DOMContentLoaded', loadCurrentTemplate);

        templateInput.onchange = async (e) => {
            if (e.target.files.length === 0) return;
            const file = e.target.files[0];
            const formData = new FormData();
            formData.append('file', file);

            templateUploadStatus.textContent = '上傳中...';
            templateUploadStatus.style.color = '#64748b';

            try {
                const res = await fetch('/api/upload_template', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    templateUploadStatus.textContent = '✅ ' + data.message;
                    templateUploadStatus.style.color = '#16a34a';
                    loadCurrentTemplate();
                } else {
                    throw new Error(data.detail);
                }
            } catch (err) {
                templateUploadStatus.textContent = '❌ 上傳失敗: ' + err.message;
                templateUploadStatus.style.color = '#dc2626';
            }
            templateInput.value = '';
        };

        // File Selection & Drag-and-Drop
        dropZone.onclick = () => fileInput.click();
        dropZone.ondragover = (e) => { e.preventDefault(); dropZone.classList.add('dragover'); };
        dropZone.ondragleave = () => dropZone.classList.remove('dragover');
        dropZone.ondrop = (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
        };
        fileInput.onchange = (e) => {
            if (e.target.files.length > 0) handleFile(e.target.files[0]);
        };

        async function handleFile(file) {
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('請選擇 PDF 格式之檔案！');
                return;
            }
            currentFile = file;
            currentFileOrigName = file.name.replace(/\.[^/.]+$/, "");
            const sizeMB = (file.size / (1024 * 1024)).toFixed(2);

            fileNameDisplay.innerHTML = `已選擇: <b>${file.name}</b> (${sizeMB} MB)`;
            submitBtn.disabled = true;
            analyzeFontsBtn.disabled = true;
            submitBtn.textContent = '正在上傳並產生預覽...';
            statusDiv.textContent = '';
            outlineEditorBtnGroup.style.display = 'none';

            // 呼叫 upload_file 取得預覽與頁數
            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/api/upload_file', { method: 'POST', body: formData });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '上傳失敗');

                currentFileId = data.file_id;
                totalPdfPages = data.total_pages || 1;
                currentPreviewPage = 1;
                totalPagesDisplay.textContent = totalPdfPages;
                previewPageDisplay.textContent = currentPreviewPage;

                previewContainer.style.display = 'block';
                updatePreview();

                submitBtn.disabled = false;
                analyzeFontsBtn.disabled = false;
                submitBtn.textContent = '開始執行 OCR / 轉檔';
            } catch (err) {
                alert('無法載入 PDF 預覽: ' + err.message);
                submitBtn.disabled = false;
                analyzeFontsBtn.disabled = false;
                submitBtn.textContent = '開始執行 OCR / 轉檔';
            }
        }

        function updatePreview() {
            if (!currentFileId) return;
            const h = headerSlider.value;
            const f = footerSlider.value;
            const l = leftSlider.value;
            const r = rightSlider.value;

            headerVal.textContent = h;
            footerVal.textContent = f;
            leftVal.textContent = l;
            rightVal.textContent = r;

            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                previewImage.src = `/api/render_preview/${currentFileId}?page=${currentPreviewPage}&header=${h}&footer=${f}&left=${l}&right=${r}&_t=${Date.now()}`;
            }, 300);
        }

        headerSlider.oninput = updatePreview;
        footerSlider.oninput = updatePreview;
        leftSlider.oninput = updatePreview;
        rightSlider.oninput = updatePreview;

        prevPageBtn.onclick = () => {
            if (currentPreviewPage > 1) {
                currentPreviewPage--;
                previewPageDisplay.textContent = currentPreviewPage;
                updatePreview();
            }
        };

        nextPageBtn.onclick = () => {
            if (currentPreviewPage < totalPdfPages) {
                currentPreviewPage++;
                previewPageDisplay.textContent = currentPreviewPage;
                updatePreview();
            }
        };

        // Form Submit
        document.getElementById('uploadForm').onsubmit = async (e) => {
            e.preventDefault();
            if (!currentFile && !currentFileId) return;

            submitBtn.disabled = true;
            analyzeFontsBtn.disabled = true;
            outlineEditorBtnGroup.style.display = 'none';

            const formData = new FormData();
            if (currentFileId) {
                formData.append('file_id', currentFileId);
                formData.append('filename_orig', currentFileOrigName);
            } else if (currentFile) {
                formData.append('file', currentFile);
            }

            const h1Style = document.getElementById('h1Style')?.value;
            const h2Style = document.getElementById('h2Style')?.value;
            const h3Style = document.getElementById('h3Style')?.value;
            const imageCaptionStyle = document.getElementById('imageCaptionStyle')?.value;
            const kaitiStyle = document.getElementById('kaitiStyle')?.value;
            if (h1Style || h2Style || h3Style || imageCaptionStyle || kaitiStyle) {
                formData.append('style_mapping', JSON.stringify({
                    h1: h1Style,
                    h2: h2Style,
                    h3: h3Style,
                    image_caption: imageCaptionStyle,
                    kaiti: kaitiStyle
                }));
            }

            formData.append('engine', document.getElementById('engineSelect')?.value || 'auto');
            formData.append('header_ratio', headerSlider.value);
            formData.append('footer_ratio', footerSlider.value);
            formData.append('left_ratio', leftSlider.value);
            formData.append('right_ratio', rightSlider.value);
            formData.append('start_page', document.getElementById('startPageInput')?.value || 0);
            formData.append('end_page', document.getElementById('endPageInput')?.value || 0);
            formData.append('no_footnote', document.getElementById('noFootnoteToggle')?.checked || false);


            statusDiv.innerHTML = `
                <div style="margin-top:20px; padding:20px; border:1px solid #cbd5e1; border-radius:8px; background:#f8fafc; text-align: left;">
                    <div style="font-weight:bold; margin-bottom:10px; color:#334155;">🚀 伺服器處理進度</div>
                    <div style="width: 100%; background: #e2e8f0; border-radius: 4px; overflow: hidden; height: 12px; margin-bottom:10px;">
                        <div id="progressBar" style="height: 12px; background: #ea580c; width: 0%; transition: width 0.3s;"></div>
                    </div>
                    <div id="progressText" style="color: #475569; font-size: 0.9rem;">正在啟動背景轉檔任務...</div>
                </div>
            `;

            try {
                const response = await fetch('/api/upload_and_run_ocr', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    const errMsg = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail || 'OCR 啟動失敗');
                    throw new Error(errMsg);
                }

                const result = await response.json();
                const stem = result.filename_stem;

                let isFinished = false;
                const pollInterval = setInterval(async () => {
                    if (isFinished) return;
                    try {
                        const res = await fetch(`/api/ocr_progress/${stem}`);
                        const prog = await res.json();

                        const pBar = document.getElementById('progressBar');
                        const pText = document.getElementById('progressText');

                        if (pBar && prog.progress !== undefined) {
                            pBar.style.width = prog.progress + '%';
                        }
                        if (pText && prog.message) {
                            pText.innerText = prog.message;
                        }

                        if (prog.status === 'completed' || prog.progress === 100) {
                            isFinished = true;
                            clearInterval(pollInterval);
                            onComplete(stem);
                        } else if (prog.status === 'failed') {
                            isFinished = true;
                            clearInterval(pollInterval);
                            throw new Error(prog.message || '後端轉檔發生錯誤');
                        }
                    } catch (e) {
                        console.error('Polling error:', e);
                    }
                }, 1000);

                function onComplete(filename_stem) {
                    statusDiv.innerHTML += `<div style="margin-top:1rem; color:#16a34a; font-weight:bold;">✅ 處理完成！請點選以下按鈕另存新檔：</div>`;

                    const btnContainer = document.createElement('div');
                    btnContainer.id = 'saveBtnContainer';
                    btnContainer.style.display = 'flex';
                    btnContainer.style.gap = '10px';
                    btnContainer.style.marginTop = '15px';
                    btnContainer.style.flexWrap = 'wrap';

                    const btnDocx = document.createElement('button');
                    btnDocx.className = 'btn';
                    btnDocx.style.background = '#2563eb';
                    btnDocx.style.flex = '1';
                    btnDocx.innerText = '📁 本機另存 DOCX (原生視窗)';
                    btnDocx.onclick = (e) => nativeSave(filename_stem, 'docx', e.currentTarget);

                    const btnMd = document.createElement('button');
                    btnMd.className = 'btn';
                    btnMd.style.background = '#16a34a';
                    btnMd.style.flex = '1';
                    btnMd.innerText = '📁 本機另存 Markdown (原生視窗)';
                    btnMd.onclick = (e) => nativeSave(filename_stem, 'md', e.currentTarget);

                    btnContainer.appendChild(btnDocx);
                    btnContainer.appendChild(btnMd);
                    statusDiv.appendChild(btnContainer);

                    outlineEditorBtnGroup.style.display = 'block';
                    outlineEditorBtn.dataset.stem = filename_stem;
                    submitBtn.disabled = false;
                    analyzeFontsBtn.disabled = false;
                }

            } catch (err) {
                statusDiv.innerHTML = `<div style="margin-top:1rem; padding:1rem; background: rgba(220, 38, 38, 0.1); border:1px solid rgba(220, 38, 38, 0.3); border-radius:8px; color:#ef4444;">
                    ❌ <b>執行失敗：</b>${err.message} <br>
                    <button type="button" onclick="submitBtn.click()" style="margin-top:10px; padding: 8px 16px; cursor:pointer; background: transparent; color: inherit; border: 1px solid currentColor; border-radius: 6px;">🔄 重新嘗試上傳</button>
                </div>`;
                submitBtn.disabled = false;
                analyzeFontsBtn.disabled = false;
            }
        };

        async function nativeSave(stem, ext, btnElement) {
            const origText = btnElement ? btnElement.innerText : '';
            if (btnElement) {
                btnElement.disabled = true;
                btnElement.innerText = '⏳ 請在開啟的視窗中選擇儲存位置...';
            }
            try {
                const source_path = `data/03_output/${stem}.${ext}`;
                const res = await fetch('/api/native_save_file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source_path, suggested_filename: `${stem}.${ext}` })
                });

                if (!res.ok) {
                    throw new Error(`伺服器回應異常 (${res.status})`);
                }
                const result = await res.json();

                if (result.status === 'success') {
                    if (btnElement) {
                        btnElement.innerText = `✅ 已儲存 ${ext.toUpperCase()}`;
                        btnElement.disabled = false;
                    }

                    let saveInfoId = `savedInfo_${ext}`;
                    let savedInfo = document.getElementById(saveInfoId);
                    if (!savedInfo) {
                        savedInfo = document.createElement('div');
                        savedInfo.id = saveInfoId;
                        savedInfo.style.marginTop = '0.8rem';
                        savedInfo.style.padding = '0.8rem';
                        savedInfo.style.background = '#f0fdf4';
                        savedInfo.style.border = '1px solid #bbf7d0';
                        savedInfo.style.borderRadius = '8px';
                        savedInfo.style.color = '#166534';
                        savedInfo.style.fontSize = '0.9rem';
                        const container = document.getElementById('saveBtnContainer') || statusDiv;
                        container.parentNode.insertBefore(savedInfo, container.nextSibling);
                    }
                    savedInfo.innerHTML = `<div><b>${ext.toUpperCase()} 文件已成功儲存至：</b></div>
                    <div style="margin:4px 0; word-break:break-all; font-family:monospace; background:#fff; padding:6px; border-radius:4px; border:1px solid #dcfce7;">${result.saved_path}</div>
                    <button type="button" class="btn" style="margin-top:6px; padding:6px 12px; background:#15803d; color:white; font-size:0.85rem;" onclick="openSavedPath('${result.saved_path.replace(/\\/g, '\\\\')}')">📂 在 Windows 檔案總管中開啟</button>`;
                } else if (result.status === 'cancelled') {
                    if (btnElement) {
                        btnElement.innerText = origText;
                        btnElement.disabled = false;
                    }
                } else {
                    console.warn('原生另存降級為瀏覽器直接下載:', result.message);
                    window.location.href = `/api/download_ocr_result/${stem}/${ext}`;
                    if (btnElement) {
                        btnElement.innerText = origText;
                        btnElement.disabled = false;
                    }
                }
            } catch (e) {
                console.warn('原生另存發生錯誤，降級為瀏覽器下載:', e);
                window.location.href = `/api/download_ocr_result/${stem}/${ext}`;
                if (btnElement) {
                    btnElement.innerText = origText;
                    btnElement.disabled = false;
                }
            }
        }

        async function openSavedPath(filePath) {
            try {
                await fetch('/api/open_file_folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_path: filePath })
                });
            } catch (err) {
                alert('無法開啟檔案總管: ' + err.message);
            }
        }

        // Outline Editor Logic
        let currentMdLines = [];

        outlineEditorBtn.onclick = async function () {
            const stem = this.dataset.stem;
            if (!stem) return;

            document.getElementById('outlineEditorSection').style.display = 'block';
            document.getElementById('outlineList').innerHTML = '讀取中...';

            try {
                const res = await fetch(`/api/get_markdown/${stem}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail);

                currentMdLines = data.content.split('\n');
                renderOutlineList();
            } catch (err) {
                document.getElementById('outlineList').innerHTML = `<span style="color:red">無法讀取 Markdown 檔案: ${err.message}</span>`;
            }
        };

        function renderOutlineList() {
            const listDiv = document.getElementById('outlineList');
            listDiv.innerHTML = '';

            currentMdLines.forEach((line, index) => {
                const match = line.match(/^(#{1,3})\s+(.*)$/);
                if (match) {
                    const level = match[1].length;
                    const text = match[2];

                    const row = document.createElement('div');
                    row.style.display = 'flex';
                    row.style.gap = '10px';
                    row.style.marginBottom = '8px';
                    row.style.alignItems = 'center';
                    row.style.paddingLeft = `${(level - 1) * 20}px`;

                    const select = document.createElement('select');
                    select.innerHTML = `
                        <option value="0">一般內文</option>
                        <option value="1" ${level === 1 ? 'selected' : ''}>H1</option>
                        <option value="2" ${level === 2 ? 'selected' : ''}>H2</option>
                        <option value="3" ${level === 3 ? 'selected' : ''}>H3</option>
                    `;
                    select.onchange = (e) => {
                        const newLevel = parseInt(e.target.value);
                        let cleanText = line.replace(/^(#{1,3})\s+/, '');
                        if (newLevel > 0) {
                            currentMdLines[index] = '#'.repeat(newLevel) + ' ' + cleanText;
                        } else {
                            currentMdLines[index] = cleanText;
                        }
                    };

                    const span = document.createElement('span');
                    span.textContent = text;
                    span.style.flex = '1';

                    row.appendChild(select);
                    row.appendChild(span);
                    listDiv.appendChild(row);
                }
            });

            if (listDiv.children.length === 0) {
                listDiv.innerHTML = '<span style="color:#64748b;">未偵測到任何標題，這可能是因為全文書籍皆為內文，或者偵測未命中。</span>';
            }
        }

        document.getElementById('saveOutlineBtn').onclick = async function () {
            const stem = outlineEditorBtn.dataset.stem;
            const statusDiv = document.getElementById('outlineSaveStatus');

            statusDiv.textContent = '儲存並重新產生 Word 中...';
            statusDiv.style.color = '#ea580c';
            this.disabled = true;

            try {
                const res = await fetch(`/api/update_and_rebuild_docx/${stem}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: currentMdLines.join('\n') })
                });
                const data = await res.json();
                if (res.ok) {
                    statusDiv.textContent = '✅ ' + data.message;
                    statusDiv.style.color = '#16a34a';
                } else {
                    throw new Error(data.detail);
                }
            } catch (err) {
                statusDiv.textContent = '❌ 失敗: ' + err.message;
                statusDiv.style.color = '#dc2626';
            }
            this.disabled = false;
        };
    