// Shared client config, notifications and the sidebar shell for every toolbox page.
window.APP_CONFIG = {
    maxUploadSizeMB: 200,
    maxTemplateSizeMB: 20,
    fileRetentionHours: 24
};

fetch('/api/system_config').then(r => r.json()).then(cfg => {
    if (cfg && cfg.max_upload_size_mb) {
        window.APP_CONFIG.maxUploadSizeMB = cfg.max_upload_size_mb;
        window.APP_CONFIG.maxTemplateSizeMB = cfg.max_template_size_mb;
        window.APP_CONFIG.fileRetentionHours = cfg.file_retention_hours;
    }
}).catch(() => {});

// Non-blocking replacement for window.alert; kind is "info" | "success" | "warning" | "error".
window.toolbox = {
    notify(message, kind = 'info', ms = 5000) {
        let region = document.getElementById('toast-region');
        if (!region) {
            region = document.createElement('div');
            region.id = 'toast-region';
            region.setAttribute('role', 'status');
            region.setAttribute('aria-live', 'polite');
            document.body.appendChild(region);
        }
        const toast = document.createElement('div');
        toast.className = 'toast' + (kind === 'info' ? '' : ' toast-' + kind);
        toast.textContent = message;
        region.appendChild(toast);
        setTimeout(() => toast.remove(), ms);
    },
    escape(text) {
        return String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
};

window.checkUploadFileSize = function(file, customMaxMB) {
    if (!file) return true;
    const maxMB = customMaxMB || window.APP_CONFIG.maxUploadSizeMB;
    if (file.size > maxMB * 1024 * 1024) {
        const fileMB = (file.size / (1024 * 1024)).toFixed(1);
        window.toolbox.notify(`檔案 ${fileMB} MB 超過單次上傳上限 ${maxMB} MB。\n請壓縮檔案或分卷後再試。`, 'error', 8000);
        return false;
    }
    return true;
};

window.addEventListener('error', function(e) {
    window.toolbox.notify('頁面發生未預期的錯誤：' + e.message, 'error', 8000);
});

const ICON = {
    book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
    formula: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    pod: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><polyline points="10 2 10 10 13 7 16 10 16 2"/>',
    refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    github: '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>',
    chip: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>'
};

function svg(name, size = 16) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name]}</svg>`;
}

const NAV_ITEMS = [
    { href: '/static/ocr_pipeline.html', key: 'ocr_pipeline', icon: 'doc', label: '全自動整稿' },
    { href: '/static/pod_studio.html', key: 'pod_studio', icon: 'pod', label: 'POD 整稿' },
    { href: '/static/formula.html', key: 'formula', icon: 'formula', label: '公式提取' },
    { href: '/static/extract_images.html', key: 'extract_images', icon: 'image', label: '圖片提取' },
    { href: '/static/founder_repair.html', key: 'founder_repair', icon: 'wrench', label: '方正修復' }
];

document.addEventListener('DOMContentLoaded', () => {
    const pending = sessionStorage.getItem('tb-toast');
    if (pending) {
        sessionStorage.removeItem('tb-toast');
        window.toolbox.notify(pending, 'success');
    }

    if (document.getElementById('sidebar')) return;

    const currentPath = window.location.pathname;
    const navHtml = NAV_ITEMS.map(item => `
            <a href="${item.href}" class="nav-link ${currentPath.includes(item.key) ? 'active' : ''}"${currentPath.includes(item.key) ? ' aria-current="page"' : ''}>
                <span class="nav-icon">${svg(item.icon)}</span>${item.label}
            </a>`).join('');

    const sidebarHtml = `
    <div id="sidebar">
        <a href="/" class="brand">${svg('book', 20)}轉檔工具箱</a>
        <nav aria-label="工具選單">${navHtml}
        </nav>
        <div class="sidebar-footer">
            <div id="hardwareDisplay" class="sidebar-info-box">硬體加速：偵測中</div>
            <div id="versionDisplay" class="sidebar-version-text">版本：讀取中</div>
            <div class="sidebar-privacy"><strong>零日誌隱私架構</strong>檔案保留 24 小時後自動銷毀</div>
            <button id="modeToggleBtn" class="sidebar-btn" type="button" title="切換出版社編輯模式與工程師除錯模式">模式：讀取中</button>
            <button id="checkUpdateBtn" class="sidebar-btn" type="button">${svg('refresh', 14)}檢查更新</button>
            <button id="globalReportBtn" class="sidebar-btn" type="button">${svg('github', 14)}在 GitHub 回報問題</button>
        </div>
    </div>

    <div id="updateModal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="updateModalTitle">
        <div class="modal modal-sm">
            <h2 id="updateModalTitle">發現新版本</h2>
            <p id="updateVersionText" style="font-weight:600; margin:0 0 0.75rem;"></p>
            <div id="updateReleaseNotes" class="path-box" style="white-space:pre-wrap; max-height:150px; overflow-y:auto; font-family:var(--font-sans);"></div>
            <div id="updateMsg" class="hint" style="margin:0.75rem 0 0;" role="status"></div>
            <div class="modal-foot" style="margin-top:1rem;">
                <button id="closeUpdateBtn" class="btn btn-secondary btn-sm" type="button">稍後再說</button>
                <button id="applyUpdateBtn" class="btn btn-primary btn-sm" type="button">下載並重新啟動</button>
            </div>
        </div>
    </div>`;

    const bodyContents = Array.from(document.body.childNodes);
    const mainContent = document.createElement('div');
    mainContent.id = 'main-content';
    bodyContents.forEach(node => mainContent.appendChild(node));

    const backdrop = document.createElement('div');
    backdrop.id = 'sidebarBackdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.appendChild(backdrop);

    const mobileNavbar = document.createElement('div');
    mobileNavbar.id = 'mobileNavbar';
    mobileNavbar.innerHTML = `
        <button id="sidebarToggleBtn" class="mobile-nav-toggle" type="button" aria-label="切換選單" aria-expanded="false" aria-controls="sidebar">
            ${svg('menu', 20)}
        </button>
        <a href="/" class="mobile-brand">
            ${svg('book', 18)}
            <span>轉檔工具箱</span>
        </a>
        <div id="mobileNavRight"></div>
    `;
    mainContent.insertAdjacentElement('afterbegin', mobileNavbar);

    document.body.appendChild(mainContent);
    document.body.insertAdjacentHTML('afterbegin', sidebarHtml);

    ['sidebar.css', 'toolbox.css'].forEach(name => {
        if (!document.querySelector(`link[href*="${name}"]`)) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = '/static/' + name;
            document.head.appendChild(link);
        }
    });

    if (!document.querySelector('script[src*="viewport_manager.js"]')) {
        const vp = document.createElement('script');
        vp.src = '/static/js/viewport_manager.js';
        document.head.appendChild(vp);
    }

    const toggleBtn = document.getElementById('sidebarToggleBtn');
    if (toggleBtn) {
        toggleBtn.onclick = () => {
            const vp = /** @type {any} */ (window).viewportManager;
            if (vp && typeof vp.toggleSidebar === 'function') {
                vp.toggleSidebar();
            } else {
                const isExpanded = document.documentElement.getAttribute('data-sidebar-state') === 'expanded';
                document.documentElement.setAttribute('data-sidebar-state', isExpanded ? 'collapsed' : 'expanded');
                toggleBtn.setAttribute('aria-expanded', isExpanded ? 'false' : 'true');
            }
        };
    }

    backdrop.onclick = () => {
        const vp = /** @type {any} */ (window).viewportManager;
        if (vp && typeof vp.closeSidebar === 'function') {
            vp.closeSidebar();
        } else {
            document.documentElement.setAttribute('data-sidebar-state', 'collapsed');
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
        }
    };

    document.querySelectorAll('#sidebar a.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            const vp = /** @type {any} */ (window).viewportManager;
            if (vp && typeof vp.isMobile === 'function' && (vp.isMobile() || vp.isTablet())) {
                vp.closeSidebar();
            }
        });
    });

    const versionDisplay = document.getElementById('versionDisplay');
    const checkUpdateBtn = document.getElementById('checkUpdateBtn');
    const updateModal = document.getElementById('updateModal');
    const closeUpdateBtn = document.getElementById('closeUpdateBtn');
    const applyUpdateBtn = document.getElementById('applyUpdateBtn');
    const updateVersionText = document.getElementById('updateVersionText');
    const updateReleaseNotes = document.getElementById('updateReleaseNotes');
    const updateMsg = document.getElementById('updateMsg');
    let currentDownloadUrl = null;

    document.getElementById('globalReportBtn').onclick = () => {
        const repo = 'RandyXie04/doc-image-extractor';
        const title = encodeURIComponent('[問題回報] 請簡述您遇到的問題');
        const versionText = versionDisplay.textContent || 'App 版本未知';
        const body = `### 問題描述
<!-- 請描述異常現象、錯誤訊息或改進建議 -->

### 系統資訊
- **應用版本**: ${versionText}
- **瀏覽器**: ${navigator.userAgent}
- **回報時間**: ${new Date().toLocaleString()}`;
        window.open(`https://github.com/${repo}/issues/new?title=${title}&body=${encodeURIComponent(body)}`, '_blank');
    };

    fetch('/api/version').then(res => res.json()).then(data => {
        versionDisplay.textContent = `App v${data.app_version} · Model v${data.model_version}`;
    }).catch(() => {
        versionDisplay.textContent = '無法讀取版本資訊';
    });

    const hardwareDisplay = document.getElementById('hardwareDisplay');
    fetch('/api/hardware_status').then(res => res.json()).then(data => {
        if (data.is_accelerated) {
            const gpuName = (data.gpu_name || '').replace('NVIDIA GeForce ', '').replace('NVIDIA ', '');
            hardwareDisplay.classList.add('is-accelerated');
            hardwareDisplay.innerHTML = `${svg('chip', 12)} GPU 加速：${window.toolbox.escape(gpuName)}`;
        } else {
            hardwareDisplay.innerHTML = `${svg('chip', 12)} CPU 相容模式`;
        }
    }).catch(() => {
        hardwareDisplay.textContent = '硬體探測離線';
    });

    closeUpdateBtn.onclick = () => updateModal.classList.remove('open');
    updateModal.addEventListener('click', (e) => {
        if (e.target === updateModal && !closeUpdateBtn.disabled) updateModal.classList.remove('open');
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !closeUpdateBtn.disabled) updateModal.classList.remove('open');
    });

    checkUpdateBtn.onclick = async () => {
        checkUpdateBtn.disabled = true;
        const originalHtml = checkUpdateBtn.innerHTML;
        checkUpdateBtn.textContent = '檢查中…';
        try {
            const res = await fetch('/api/check_update', { method: 'POST' });
            const data = await res.json();
            if (data.has_update) {
                updateVersionText.textContent = `最新版本：v${data.latest_version}`;
                updateReleaseNotes.textContent = data.release_notes || '此版本未提供發布說明。';
                currentDownloadUrl = data.download_url;
                updateMsg.textContent = currentDownloadUrl ? '' : '此版本尚未附帶可執行檔，請改至 GitHub Releases 手動下載。';
                applyUpdateBtn.disabled = !currentDownloadUrl;
                updateModal.classList.add('open');
            } else {
                window.toolbox.notify(data.msg || '目前已是最新版本。', data.status === 'error' ? 'warning' : 'success');
            }
        } catch (e) {
            window.toolbox.notify('檢查更新失敗，請確認網路連線後再試。', 'error');
        } finally {
            checkUpdateBtn.disabled = false;
            checkUpdateBtn.innerHTML = originalHtml;
        }
    };

    applyUpdateBtn.onclick = async () => {
        if (!currentDownloadUrl) return;
        applyUpdateBtn.disabled = true;
        closeUpdateBtn.disabled = true;
        updateMsg.textContent = '正在背景下載新版程式，請勿關閉此視窗。';
        try {
            const res = await fetch('/api/apply_update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ download_url: currentDownloadUrl })
            });
            const data = await res.json();
            if (data.status === 'success') {
                updateMsg.textContent = '下載完成，系統即將重新啟動。';
            } else {
                updateMsg.textContent = '更新失敗：' + (data.msg || data.detail || '未知錯誤');
                applyUpdateBtn.disabled = false;
                closeUpdateBtn.disabled = false;
            }
        } catch (e) {
            updateMsg.textContent = '網路錯誤，請稍後再試。';
            applyUpdateBtn.disabled = false;
            closeUpdateBtn.disabled = false;
        }
    };

    const modeToggleBtn = document.getElementById('modeToggleBtn');
    const MODE_LABEL = { editor: '出版社編輯模式', dev: '工程師除錯模式' };
    function updateModeBtnUI(mode) {
        modeToggleBtn.dataset.mode = mode;
        modeToggleBtn.textContent = `模式：${MODE_LABEL[mode] || mode}`;
        modeToggleBtn.classList.toggle('is-active', mode === 'dev');
    }
    fetch('/api/app_mode').then(r => r.json()).then(d => {
        if (d && d.mode) updateModeBtnUI(d.mode);
    }).catch(() => { modeToggleBtn.textContent = '模式：未知'; });

    modeToggleBtn.onclick = async () => {
        const targetMode = modeToggleBtn.dataset.mode === 'dev' ? 'editor' : 'dev';
        try {
            const res = await fetch('/api/set_app_mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: targetMode })
            });
            const d = await res.json();
            if (d.status === 'success') {
                window.dispatchEvent(new CustomEvent('appModeChanged', { detail: { mode: d.mode } }));
                const msg = d.mode === 'dev'
                    ? '已切換為工程師除錯模式：顯示處理日誌與內部目錄。'
                    : '已切換為出版社編輯模式：隱藏處理日誌與內部目錄。';
                sessionStorage.setItem('tb-toast', msg);
                window.location.reload();
            }
        } catch (e) {
            window.toolbox.notify('模式切換失敗：' + e.message, 'error');
        }
    };

    const savedTheme = localStorage.getItem('app-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const themeToggleBtn = document.createElement('button');
    themeToggleBtn.id = 'themeToggleBtn';
    themeToggleBtn.type = 'button';

    function updateThemeToggleUI(theme) {
        const toDark = theme !== 'dark';
        themeToggleBtn.innerHTML = svg(toDark ? 'moon' : 'sun', 18);
        themeToggleBtn.title = toDark ? '切換為深色模式' : '切換為淺色模式';
        themeToggleBtn.setAttribute('aria-label', themeToggleBtn.title);
    }
    updateThemeToggleUI(savedTheme);

    themeToggleBtn.onclick = () => {
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('app-theme', newTheme);
        updateThemeToggleUI(newTheme);
    };

    document.getElementById('main-content').appendChild(themeToggleBtn);
});
