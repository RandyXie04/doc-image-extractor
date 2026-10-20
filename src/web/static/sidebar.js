// 全域安全配置與上傳限制檢查器
window.APP_CONFIG = {
    maxUploadSizeMB: 200,
    maxTemplateSizeMB: 20,
    fileRetentionHours: 24
};

// 異步取得伺服器最新安全與生命週期配置
fetch('/api/system_config').then(r => r.json()).then(cfg => {
    if (cfg && cfg.max_upload_size_mb) {
        window.APP_CONFIG.maxUploadSizeMB = cfg.max_upload_size_mb;
        window.APP_CONFIG.maxTemplateSizeMB = cfg.max_template_size_mb;
        window.APP_CONFIG.fileRetentionHours = cfg.file_retention_hours;
    }
}).catch(() => {});

// 全域檔案大小預檢輔助函式 (客戶端第一道防線)
window.checkUploadFileSize = function(file, customMaxMB) {
    if (!file) return true;
    const maxMB = customMaxMB || window.APP_CONFIG.maxUploadSizeMB;
    const maxBytes = maxMB * 1024 * 1024;
    if (file.size > maxBytes) {
        const fileMB = (file.size / (1024 * 1024)).toFixed(1);
        alert(`檔案大小 (${fileMB} MB) 超過單次上傳限制 (上限 ${maxMB} MB)！\n請壓縮檔案或分卷後再試。`);
        return false;
    }
    return true;
};

// 全域錯誤監聽器，防止隱含 SyntaxError 或 Runtime Error 讓按鈕靜默失效
window.addEventListener('error', function(e) {
    let errorBanner = document.getElementById('global-error-banner');
    if (!errorBanner) {
        errorBanner = document.createElement('div');
        errorBanner.id = 'global-error-banner';
        errorBanner.style.cssText = 'position:fixed; top:0; left:0; width:100%; background:#dc2626; color:white; padding:10px; z-index:9999; text-align:center; font-family:sans-serif; cursor:pointer; font-weight:bold; box-shadow:0 4px 6px rgba(0,0,0,0.1);';
        errorBanner.title = '點擊關閉此錯誤提示';
        errorBanner.onclick = () => errorBanner.remove();
        if (document.body) document.body.prepend(errorBanner);
    }
    errorBanner.textContent = '系統發生異常：' + e.message + ' (請檢查主控台)';
});

document.addEventListener("DOMContentLoaded", () => {
    // Check if sidebar already exists
    if (document.getElementById('sidebar')) return;

    const currentPath = window.location.pathname;
    
    const sidebarHtml = `
    <div id="sidebar">
        <style>
            #sidebar { background: var(--sidebar-bg, #ffffff) !important; color: var(--text-main, #0f172a) !important; }
            #sidebar .brand { color: var(--text-main, #0f172a) !important; }
            :root[data-theme="dark"] #sidebar .brand { color: #f8fafc !important; }
            #sidebar a.nav-link { color: #334155 !important; font-weight: 500 !important; }
            #sidebar a.nav-link:hover { background: #f1f5f9 !important; color: #0f172a !important; }
            #sidebar a.nav-link.active { background: rgba(234, 88, 12, 0.1) !important; color: #c2410c !important; border: 1px solid rgba(234, 88, 12, 0.25) !important; font-weight: 600 !important; }
            :root[data-theme="dark"] #sidebar a.nav-link { color: #94a3b8 !important; }
            :root[data-theme="dark"] #sidebar a.nav-link:hover { background: rgba(255, 255, 255, 0.06) !important; color: #f8fafc !important; }
            #main-content { background-color: var(--bg-color, #f8fafc) !important; }
            :root[data-theme="dark"] html, :root[data-theme="dark"] body { background-color: #0f172a !important; color: #f8fafc !important; }
            .container { background-color: var(--card-bg, #ffffff) !important; border: 1px solid var(--border, #e2e8f0) !important; border-radius: 20px !important; padding: clamp(1.5rem, 3vw, 3rem) !important; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06) !important; box-sizing: border-box !important; }
            :root[data-theme="dark"] .container { background-color: #1e293b !important; border-color: rgba(255, 255, 255, 0.12) !important; color: #f8fafc !important; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4) !important; border-radius: 20px !important; padding: clamp(1.5rem, 3vw, 3rem) !important; }
        </style>
        <a href="/" class="brand">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg> 轉檔工具箱
        </a>
        <nav>
            <a href="/static/formula.html" class="nav-link ${currentPath.includes('formula') ? 'active' : ''}">
                <span class="nav-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></span> 公式提取
            </a>
            <a href="/static/extract_images.html" class="nav-link ${currentPath.includes('extract_images') ? 'active' : ''}">
                <span class="nav-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></span> 圖片提取
            </a>
            <a href="/static/founder_repair.html" class="nav-link ${currentPath.includes('founder_repair') ? 'active' : ''}">
                <span class="nav-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></span> 方正修復
            </a>
            <a href="/static/ocr_pipeline.html" class="nav-link ${currentPath.includes('ocr_pipeline') ? 'active' : ''}">
                <span class="nav-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></span> 自動 OCR
            </a>
        </nav>
        <div class="sidebar-footer">
            <div id="hardwareDisplay" class="sidebar-info-box">
                <span style="display:inline-flex; align-items:center; justify-content:center; gap:4px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 硬體加速: 偵測中...
                </span>
            </div>
            <div id="versionDisplay" class="sidebar-version-text">版本: 讀取中...</div>
            <div class="sidebar-privacy-box" style="margin-top: 6px; font-size: 0.72rem; color: var(--text-muted, #64748b); text-align: center; padding: 5px; background: rgba(0,0,0,0.03); border-radius: 6px; border: 1px solid var(--border, #e2e8f0); line-height: 1.3;">
                <span style="display: inline-flex; align-items: center; gap: 4px; font-weight: 600; color: #059669;">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> 零日誌隱私架構
                </span><br>
                檔案僅保留 24h 後自動銷毀
            </div>
            <button id="modeToggleBtn" class="sidebar-mode-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> 編輯專用 (點擊切換)
            </button>
            <button id="checkUpdateBtn" class="sidebar-btn btn-primary">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> 檢查更新
            </button>
            <button id="globalReportBtn" class="sidebar-btn btn-secondary">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg> 前往 GitHub 回報 ↗
            </button>
        </div>
    </div>
    
    <div id="updateModal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1001;">
        <div style="background: var(--card-bg, #ffffff); padding: 2rem; border-radius: 12px; width: 450px; max-width: 90%; border: 1px solid var(--border, #e2e8f0); box-shadow: 0 10px 25px rgba(0,0,0,0.1);">
            <h3 style="margin-top: 0; color: var(--text-main, #0f172a); display: flex; align-items: center; gap: 8px;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                發現新版本
            </h3>
            <p id="updateVersionText" style="font-size: 1rem; font-weight: bold; color: var(--text-main, #0f172a);"></p>
            <div id="updateReleaseNotes" style="font-size: 0.9rem; color: var(--text-muted, #475569); background: rgba(0,0,0,0.03); padding: 10px; border-radius: 8px; max-height: 150px; overflow-y: auto; margin-bottom: 1rem; white-space: pre-wrap; border: 1px solid var(--border, #e2e8f0);"></div>
            <div id="updateMsg" style="margin-bottom: 1rem; font-size: 0.9rem; font-weight: 600; color: #0284c7;"></div>
            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="closeUpdateBtn" style="padding: 8px 16px; border: 1px solid var(--border, #e2e8f0); background: rgba(0,0,0,0.04); color: var(--text-main, #0f172a); border-radius: 6px; cursor: pointer;">稍後再說</button>
                <button id="applyUpdateBtn" style="padding: 8px 16px; border: none; background: #059669; color: white; border-radius: 6px; cursor: pointer; font-weight: 500;">立即下載並重啟</button>
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

    // Inject sidebar CSS with cache-busting
    let existingLink = document.querySelector('link[href*="sidebar.css"]');
    if (!existingLink) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/sidebar.css?v=' + Date.now();
        document.head.appendChild(link);
    } else if (!existingLink.href.includes('?v=')) {
        existingLink.href = '/static/sidebar.css?v=' + Date.now();
    }

    // Direct GitHub Issue Reporting Button logic
    const globalReportBtn = document.getElementById('globalReportBtn');
    if (globalReportBtn) {
        globalReportBtn.onclick = () => {
            const repo = 'RandyXie04/doc-image-extractor';
            const title = encodeURIComponent('[問題回報] 請簡述您遇到的問題');
            const versionText = document.getElementById('versionDisplay')?.textContent || 'App 版本未知';
            const bodyContent = 
`### 問題描述
<!-- 請在此詳細描述您遇到的異常現象、錯誤訊息或改進建議 -->

### 系統資訊
- **應用版本**: ${versionText}
- **瀏覽器**: ${navigator.userAgent}
- **回報時間**: ${new Date().toLocaleString()}

---
*由網頁端「一鍵前往 GitHub 回報」按鈕自動產生*`;
            const issueUrl = `https://github.com/${repo}/issues/new?title=${title}&body=${encodeURIComponent(bodyContent)}`;
            window.open(issueUrl, '_blank');
        };
    }

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

    // Fetch hardware acceleration status
    const hardwareDisplay = document.getElementById('hardwareDisplay');
    fetch('/api/hardware_status').then(res => res.json()).then(data => {
        if (!hardwareDisplay) return;
        const gpuName = data.gpu_name || 'N/A';
        const shortGpu = gpuName.replace('NVIDIA GeForce ', '').replace('NVIDIA ', '');
        const accel = data.target_accelerator || (data.is_accelerated ? 'GPU' : 'CPU');
        if (data.is_accelerated) {
            hardwareDisplay.style.color = '#059669';
            hardwareDisplay.style.background = 'rgba(16, 185, 129, 0.08)';
            hardwareDisplay.style.borderColor = 'rgba(16, 185, 129, 0.25)';
            hardwareDisplay.innerHTML = `<span style="display:inline-flex; align-items:center; justify-content:center; gap:4px; font-weight:600;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 加速: ${shortGpu}</span><br><span style="font-size:0.68rem; opacity:0.85;">(${accel})</span>`;
        } else {
            hardwareDisplay.style.color = 'var(--text-muted, #475569)';
            hardwareDisplay.style.background = 'rgba(0, 0, 0, 0.03)';
            hardwareDisplay.style.borderColor = 'var(--border, #e2e8f0)';
            hardwareDisplay.innerHTML = `<span style="display:inline-flex; align-items:center; justify-content:center; gap:4px; font-weight:600;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> 運算: CPU 相容模式</span>`;
        }
    }).catch(e => {
        if (hardwareDisplay) hardwareDisplay.textContent = '硬體探測離線';
    });

    closeUpdateBtn.onclick = () => updateModal.style.display = 'none';

    checkUpdateBtn.onclick = async () => {
        checkUpdateBtn.disabled = true;
        const originalText = checkUpdateBtn.innerHTML;
        checkUpdateBtn.innerHTML = '<span style="display:inline-flex; align-items:center; gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg> 檢查中...</span>';

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
                    updateMsg.textContent = '此 Release 尚未包含執行檔。';
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
        updateMsg.textContent = '正在背景下載新版程式，請勿關閉視窗...';

        try {
            const res = await fetch('/api/apply_update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ download_url: currentDownloadUrl })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                updateMsg.style.color = '#15803d';
                updateMsg.textContent = '下載完成！系統即將重新啟動...';
            } else {
                updateMsg.style.color = '#dc2626';
                updateMsg.textContent = '更新失敗: ' + (data.msg || '未知錯誤');
                applyUpdateBtn.disabled = false;
                closeUpdateBtn.disabled = false;
            }
        } catch (e) {
            updateMsg.style.color = '#dc2626';
            updateMsg.textContent = '網路錯誤，請稍後再試。';
            applyUpdateBtn.disabled = false;
            closeUpdateBtn.disabled = false;
        }
    };

    // --- Mode Toggle Logic (Editor vs Dev) ---
    const modeToggleBtn = document.getElementById('modeToggleBtn');
    if (modeToggleBtn) {
        function updateModeBtnUI(mode) {
            if (mode === 'dev') {
                modeToggleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg> 工程師除錯 (切換)';
                modeToggleBtn.style.color = '#0284c7';
                modeToggleBtn.style.borderColor = '#0284c7';
                modeToggleBtn.style.background = 'rgba(2, 132, 199, 0.08)';
            } else {
                modeToggleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> 編輯專用 (切換)';
                modeToggleBtn.style.color = '';
                modeToggleBtn.style.borderColor = '';
                modeToggleBtn.style.background = '';
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
                    // 提示
                    const msg = d.mode === 'dev' ? '已切換為【工程師除錯模式】！解鎖 Log、ZIP 下載與內部目錄。' : '已切換為【出版社編輯模式】！僅保留 Word 另存檔案功能。';
                    alert(msg);
                    window.location.reload();
                }
            } catch (e) {
                alert('模式切換失敗：' + e.message);
            }
        };
    }

    // --- Theme Toggle Logic (Light Mode by Default) ---
    const savedTheme = localStorage.getItem('app-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const themeToggleBtn = document.createElement('button');
    themeToggleBtn.id = 'themeToggleBtn';

    function updateThemeToggleUI(theme) {
        if (theme === 'dark') {
            // In dark mode, clicking switches to light, show sun icon
            themeToggleBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>`;
            themeToggleBtn.title = '切換為淺色模式 (Light)';
            themeToggleBtn.setAttribute('aria-label', '切換為淺色模式');
        } else {
            // In light mode, clicking switches to dark, show moon icon
            themeToggleBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;
            themeToggleBtn.title = '切換為深色模式 (Dark)';
            themeToggleBtn.setAttribute('aria-label', '切換為深色模式');
        }
    }

    updateThemeToggleUI(savedTheme);

    themeToggleBtn.onclick = () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('app-theme', newTheme);
        updateThemeToggleUI(newTheme);
    };
    
    document.getElementById('main-content').appendChild(themeToggleBtn);
});
