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
        <div style="padding: 1.5rem; margin-top: auto; display: flex; flex-direction: column; gap: 8px;">
            <div id="versionDisplay" style="font-size: 0.8rem; color: #64748b; text-align: center;">版本: 讀取中...</div>
            <button id="modeToggleBtn" style="width: 100%; background: #1e293b; color: #94a3b8; border: 1px dashed #475569; padding: 6px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; display: flex; align-items: center; justify-content: center; gap: 6px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> 編輯專用 (點擊切換)
            </button>
            <button id="checkUpdateBtn" style="width: 100%; background: #0284c7; color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> 檢查更新
            </button>
            <button id="globalReportBtn" style="width: 100%; background: #334155; color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg> 前往 GitHub 回報 ↗
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

    // Direct GitHub Issue Reporting Button logic
    const globalReportBtn = document.getElementById('globalReportBtn');
    if (globalReportBtn) {
        globalReportBtn.onclick = () => {
            const repo = 'RandyXie04/doc-image-extractor';
            const title = encodeURIComponent('[問題回報] 請簡述您遇到的問題');
            const versionText = document.getElementById('versionDisplay')?.textContent || 'App 版本未知';
            const bodyContent = 
`### 📌 問題描述
<!-- 請在此詳細描述您遇到的異常現象、錯誤訊息或改進建議 -->

### ⚙️ 系統資訊
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
                modeToggleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg> 工程師除錯 (切換)';
                modeToggleBtn.style.color = '#38bdf8';
                modeToggleBtn.style.borderColor = '#0284c7';
                modeToggleBtn.style.background = '#0f172a';
            } else {
                modeToggleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> 編輯專用 (切換)';
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

    // --- Theme Toggle Logic ---
    const savedTheme = localStorage.getItem('app-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const themeToggleBtn = document.createElement('button');
    themeToggleBtn.id = 'themeToggleBtn';
    themeToggleBtn.style.cssText = 'position: fixed; top: 1.5rem; right: 2rem; background: rgba(120, 120, 120, 0.2); border: 1px solid rgba(120,120,120,0.3); border-radius: 50%; width: 42px; height: 42px; font-size: 1.2rem; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 1000; backdrop-filter: blur(8px); transition: all 0.3s;';
    themeToggleBtn.innerHTML = savedTheme === 'light' ? '☀️' : '🌙';
    themeToggleBtn.title = '切換主題 (Light/Dark)';
    
    themeToggleBtn.onmouseover = () => { themeToggleBtn.style.transform = 'scale(1.1)'; };
    themeToggleBtn.onmouseout = () => { themeToggleBtn.style.transform = 'scale(1)'; };

    themeToggleBtn.onclick = () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('app-theme', newTheme);
        themeToggleBtn.innerHTML = newTheme === 'light' ? '☀️' : '🌙';
    };
    
    document.getElementById('main-content').appendChild(themeToggleBtn);
});
