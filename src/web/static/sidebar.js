document.addEventListener("DOMContentLoaded", () => {
    // Check if sidebar already exists
    if (document.getElementById('sidebar')) return;

    const currentPath = window.location.pathname;
    
    const sidebarHtml = `
    <div id="sidebar">
        <a href="/" class="brand">📚 轉檔工具箱</a>
        <nav>
            <a href="/static/formula.html" class="nav-link ${currentPath.includes('formula') ? 'active' : ''}">
                <span class="nav-icon">🔍</span> 公式提取
            </a>
            <a href="/static/extract_images.html" class="nav-link ${currentPath.includes('extract_images') ? 'active' : ''}">
                <span class="nav-icon">🖼️</span> 圖片提取
            </a>
            <a href="/static/founder_repair.html" class="nav-link ${currentPath.includes('founder_repair') ? 'active' : ''}">
                <span class="nav-icon">🛠️</span> 方正修復
            </a>
            <a href="/static/ocr_pipeline.html" class="nav-link ${currentPath.includes('ocr_pipeline') ? 'active' : ''}">
                <span class="nav-icon">📄</span> 自動 OCR
            </a>
        </nav>
        <div style="padding: 1.5rem; margin-top: auto; display: flex; flex-direction: column; gap: 8px;">
            <div id="versionDisplay" style="font-size: 0.8rem; color: #64748b; text-align: center;">版本: 讀取中...</div>
            <button id="modeToggleBtn" style="width: 100%; background: #1e293b; color: #94a3b8; border: 1px dashed #475569; padding: 6px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; display: flex; align-items: center; justify-content: center; gap: 4px;">
                🏢 模式：編輯專用 (點擊切換)
            </button>
            <button id="checkUpdateBtn" style="width: 100%; background: #0284c7; color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
                🔄 檢查更新
            </button>
            <button id="globalReportBtn" style="width: 100%; background: #334155; color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
                💬 問題回報
            </button>
        </div>
    </div>
    
    <div id="updateModal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1001;">
        <div style="background: white; padding: 2rem; border-radius: 12px; width: 450px; max-width: 90%;">
            <h3 style="margin-top: 0;">🚀 發現新版本！</h3>
            <p id="updateVersionText" style="font-size: 1rem; font-weight: bold; color: #0f172a;"></p>
            <div id="updateReleaseNotes" style="font-size: 0.9rem; color: #475569; background: #f8fafc; padding: 10px; border-radius: 8px; max-height: 150px; overflow-y: auto; margin-bottom: 1rem; white-space: pre-wrap;"></div>
            <div id="updateMsg" style="margin-bottom: 1rem; font-size: 0.9rem; font-weight: bold; color: #0284c7;"></div>
            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="closeUpdateBtn" style="padding: 8px 16px; border: none; background: #e2e8f0; border-radius: 6px; cursor: pointer;">稍後再說</button>
                <button id="applyUpdateBtn" style="padding: 8px 16px; border: none; background: #059669; color: white; border-radius: 6px; cursor: pointer;">立即下載並重啟</button>
            </div>
        </div>
    </div>
    `;

    // Wrap body content in main-content
    const bodyContents = Array.from(document.body.childNodes);
    const mainContent = document.createElement('div');
    mainContent.id = 'main-content';
    bodyContents.forEach(node => mainContent.appendChild(node));

    document.body.appendChild(mainContent);
    document.body.insertAdjacentHTML('afterbegin', sidebarHtml);

    // Inject sidebar CSS if not already there
    if (!document.querySelector('link[href*="sidebar.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/sidebar.css';
        document.head.appendChild(link);
    }

    // Modal HTML for Issue Reporting
    const modalHtml = `
    <div id="issueModal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1000;">
        <div style="background: white; padding: 2rem; border-radius: 12px; width: 400px; max-width: 90%;">
            <h3 style="margin-top: 0;">💬 提交問題回報</h3>
            <p style="font-size: 0.9rem; color: #64748b;">請用簡單的描述告訴我們您遇到了什麼問題，或希望新增什麼功能。送出後將自動建立內部任務。</p>
            <textarea id="issueDesc" rows="5" style="width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; margin-bottom: 1rem; box-sizing: border-box;" placeholder="例如：我上傳的 PDF 檔案一直轉圈圈沒有反應..."></textarea>
            <div id="issueMsg" style="margin-bottom: 1rem; font-size: 0.9rem; font-weight: bold;"></div>
            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="closeIssueBtn" style="padding: 8px 16px; border: none; background: #e2e8f0; border-radius: 6px; cursor: pointer;">取消</button>
                <button id="submitIssueBtn" style="padding: 8px 16px; border: none; background: #0f172a; color: white; border-radius: 6px; cursor: pointer;">送出回報</button>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Modal logic
    const modal = document.getElementById('issueModal');
    const openBtn = document.getElementById('globalReportBtn');
    const closeBtn = document.getElementById('closeIssueBtn');
    const submitBtn = document.getElementById('submitIssueBtn');
    const issueDesc = document.getElementById('issueDesc');
    const issueMsg = document.getElementById('issueMsg');

    openBtn.onclick = () => { modal.style.display = 'flex'; issueMsg.textContent = ''; issueDesc.value = ''; };
    closeBtn.onclick = () => { modal.style.display = 'none'; };
    
    // Wire any in-page report links to also open this modal
    document.querySelectorAll('a[href*="issues"]').forEach(link => {
        link.onclick = (e) => {
            e.preventDefault();
            modal.style.display = 'flex';
            issueMsg.textContent = '';
            issueDesc.value = '';
        };
    });
    
    submitBtn.onclick = async () => {
        if (!issueDesc.value.trim()) {
            issueMsg.style.color = '#dc2626';
            issueMsg.textContent = '內容不可為空';
            return;
        }
        submitBtn.disabled = true;
        submitBtn.textContent = '傳送中...';
        issueMsg.style.color = '#0284c7';

        try {
            const res = await fetch('/api/report_issue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description: issueDesc.value.trim() })
            });
            const data = await res.json();
            if (data.status === 'success') {
                issueMsg.style.color = '#15803d';
                issueMsg.textContent = '✅ 回報成功！Issue 已建立。';
                setTimeout(() => { modal.style.display = 'none'; }, 2000);
            } else {
                issueMsg.style.color = '#dc2626';
                issueMsg.textContent = '❌ 發生錯誤: ' + (data.msg || '未知錯誤');
                submitBtn.disabled = false;
                submitBtn.textContent = '送出回報';
            }
        } catch (e) {
            issueMsg.style.color = '#dc2626';
            issueMsg.textContent = '❌ 網路錯誤，請稍後再試。';
            submitBtn.disabled = false;
            submitBtn.textContent = '送出回報';
        }
    };

    // --- Version and Update Logic ---
    const versionDisplay = document.getElementById('versionDisplay');
    const checkUpdateBtn = document.getElementById('checkUpdateBtn');
    const updateModal = document.getElementById('updateModal');
    const closeUpdateBtn = document.getElementById('closeUpdateBtn');
    const applyUpdateBtn = document.getElementById('applyUpdateBtn');
    const updateVersionText = document.getElementById('updateVersionText');
    const updateReleaseNotes = document.getElementById('updateReleaseNotes');
    const updateMsg = document.getElementById('updateMsg');
    let currentDownloadUrl = null;

    // Fetch local version
    fetch('/api/version').then(res => res.json()).then(data => {
        versionDisplay.textContent = `App v${data.app_version} | Model v${data.model_version}`;
    }).catch(e => {
        versionDisplay.textContent = '無法讀取版本資訊';
    });

    closeUpdateBtn.onclick = () => updateModal.style.display = 'none';

    checkUpdateBtn.onclick = async () => {
        checkUpdateBtn.disabled = true;
        const originalText = checkUpdateBtn.innerHTML;
        checkUpdateBtn.innerHTML = '⏳ 檢查中...';

        try {
            const res = await fetch('/api/check_update', { method: 'POST' });
            const data = await res.json();
            
            if (data.has_update) {
                updateVersionText.textContent = `最新版本: v${data.latest_version}`;
                updateReleaseNotes.textContent = data.release_notes || '無提供發布說明。';
                currentDownloadUrl = data.download_url;
                updateMsg.textContent = '';
                updateModal.style.display = 'flex';
                applyUpdateBtn.disabled = !currentDownloadUrl;
                if (!currentDownloadUrl) {
                    updateMsg.textContent = '⚠️ 此 Release 尚未包含執行檔。';
                }
            } else {
                alert(data.msg || '您目前使用的是最新版本！');
            }
        } catch (e) {
            alert('檢查更新失敗，請確認網路連線。');
        } finally {
            checkUpdateBtn.disabled = false;
            checkUpdateBtn.innerHTML = originalText;
        }
    };

    applyUpdateBtn.onclick = async () => {
        if (!currentDownloadUrl) return;
        
        applyUpdateBtn.disabled = true;
        closeUpdateBtn.disabled = true;
        updateMsg.style.color = '#0284c7';
        updateMsg.textContent = '🚀 正在背景下載新版程式，請勿關閉視窗...';

        try {
            const res = await fetch('/api/apply_update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ download_url: currentDownloadUrl })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                updateMsg.style.color = '#15803d';
                updateMsg.textContent = '✅ 下載完成！系統即將重新啟動...';
            } else {
                updateMsg.style.color = '#dc2626';
                updateMsg.textContent = '❌ 更新失敗: ' + (data.msg || '未知錯誤');
                applyUpdateBtn.disabled = false;
                closeUpdateBtn.disabled = false;
            }
        } catch (e) {
            updateMsg.style.color = '#dc2626';
            updateMsg.textContent = '❌ 網路錯誤，請稍後再試。';
            applyUpdateBtn.disabled = false;
            closeUpdateBtn.disabled = false;
        }
    };

    // --- Mode Toggle Logic (Editor vs Dev) ---
    const modeToggleBtn = document.getElementById('modeToggleBtn');
    if (modeToggleBtn) {
        function updateModeBtnUI(mode) {
            if (mode === 'dev') {
                modeToggleBtn.innerHTML = '🛠️ 模式：工程師除錯 (點擊切換)';
                modeToggleBtn.style.color = '#38bdf8';
                modeToggleBtn.style.borderColor = '#0284c7';
                modeToggleBtn.style.background = '#0f172a';
            } else {
                modeToggleBtn.innerHTML = '🏢 模式：編輯專用 (點擊切換)';
                modeToggleBtn.style.color = '#94a3b8';
                modeToggleBtn.style.borderColor = '#475569';
                modeToggleBtn.style.background = '#1e293b';
            }
        }

        // 讀取當前模式
        fetch('/api/app_mode').then(r => r.json()).then(d => {
            if (d && d.mode) updateModeBtnUI(d.mode);
        }).catch(() => {});

        modeToggleBtn.onclick = async () => {
            const currentIsDev = modeToggleBtn.textContent.includes('工程師');
            const targetMode = currentIsDev ? 'editor' : 'dev';
            try {
                const res = await fetch('/api/set_app_mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: targetMode })
                });
                const d = await res.json();
                if (d.status === 'success') {
                    updateModeBtnUI(d.mode);
                    // 觸發全域事件並重整頁面狀態
                    window.dispatchEvent(new CustomEvent('appModeChanged', { detail: { mode: d.mode } }));
                    // 重新導向或小提示
                    const msg = d.mode === 'dev' ? '已切換為【🛠️ 工程師除錯模式】！解鎖 Log、ZIP 下載與內部目錄。' : '已切換為【🏢 出版社編輯模式】！僅保留 Word 另存檔案功能。';
                    alert(msg);
                    window.location.reload();
                }
            } catch (e) {
                alert('模式切換失敗：' + e.message);
            }
        };
    }
});
