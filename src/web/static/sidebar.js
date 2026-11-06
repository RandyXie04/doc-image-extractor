// @ts-nocheck
// Shared client config, notifications and the sidebar shell for every toolbox page.
window.APP_CONFIG = {
    maxUploadSizeMB: 200,
    maxTemplateSizeMB: 20,
    fileRetentionHours: 24
};

function syncQuotaDisplayUI() {
    const upEl = document.getElementById('cfgMaxUploadVal');
    const tplEl = document.getElementById('cfgMaxTemplateVal');
    const retEl = document.getElementById('cfgRetentionVal');
    const privRetEl = document.getElementById('privacyRetentionHours');
    if (upEl) upEl.textContent = `${window.APP_CONFIG.maxUploadSizeMB} MB`;
    if (tplEl) tplEl.textContent = `${window.APP_CONFIG.maxTemplateSizeMB} MB`;
    if (retEl) retEl.textContent = `${window.APP_CONFIG.fileRetentionHours} 小時`;
    if (privRetEl) privRetEl.textContent = `${window.APP_CONFIG.fileRetentionHours}`;
}

fetch('/api/system_config').then(r => r.json()).then(cfg => {
    if (cfg && cfg.max_upload_size_mb) {
        window.APP_CONFIG.maxUploadSizeMB = cfg.max_upload_size_mb;
        window.APP_CONFIG.maxTemplateSizeMB = cfg.max_template_size_mb;
        window.APP_CONFIG.fileRetentionHours = cfg.file_retention_hours;
        syncQuotaDisplayUI();
    }
}).catch((err) => {
    console.debug('[SystemConfig] Using default quota:', err);
});

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

window.checkUploadFileSize = function (file, customMaxMB) {
    if (!file) return true;
    const maxMB = customMaxMB || window.APP_CONFIG.maxUploadSizeMB;
    if (file.size > maxMB * 1024 * 1024) {
        const fileMB = (file.size / (1024 * 1024)).toFixed(1);
        window.toolbox.notify(`檔案 ${fileMB} MB 超過單次上傳上限 ${maxMB} MB。\n請壓縮檔案或分卷後再試。`, 'error', 8000);
        return false;
    }
    return true;
};

window.addEventListener('error', function (e) {
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
    menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
    chevronRight: '<polyline points="9 18 15 12 9 6"/>',
    chevronDown: '<polyline points="6 9 12 15 18 9"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'
};

function svg(name, size = 16) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name] || ''}</svg>`;
}

// 主工作流項目（收攏至 Settings > 一般與工作流設定）
const MAIN_NAV_ITEMS = [
    { href: '/static/ocr_pipeline.html', key: 'ocr_pipeline', icon: 'doc', label: '全自動整稿' },
    { href: '/static/pod_studio.html', key: 'pod_studio', icon: 'pod', label: 'POD 整稿' }
];

// 輔助識別工具清單（收攏至 Settings > OCR 與識別工具設定）
const AUXILIARY_NAV_ITEMS = [
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
    const isMainActive = (key) => currentPath.includes(key);
    const hasAnyMainActive = MAIN_NAV_ITEMS.some(item => isMainActive(item.key));
    const isAuxActive = AUXILIARY_NAV_ITEMS.some(item => currentPath.includes(item.key));
    const hasActiveRouteInSettings = hasAnyMainActive || isAuxActive;

    // 1. Settings 主分類展開狀態（預設展開，或當前路由為工具頁時自動展開）
    const savedSettingsCatState = localStorage.getItem('sidebar_cat_settings_expanded');
    const isSettingsCatExpanded = hasActiveRouteInSettings || savedSettingsCatState !== 'false';

    // 2. Documentation 主分類展開狀態（遵循漸進式揭露，預設收折，記憶使用者偏好）
    const savedDocsCatState = localStorage.getItem('sidebar_cat_docs_expanded');
    const isDocsCatExpanded = savedDocsCatState === 'true';

    // 3. OCR 與輔助識別工具子群組收折狀態
    const savedAuxState = localStorage.getItem('sidebar_aux_expanded');
    const isAuxExpanded = isAuxActive || savedAuxState !== 'false';

    const mainNavHtml = MAIN_NAV_ITEMS.map(item => `
        <a href="${item.href}" class="nav-link ${isMainActive(item.key) ? 'active' : ''}"${isMainActive(item.key) ? ' aria-current="page"' : ''}>
            <span class="nav-icon">${svg(item.icon, 15)}</span>
            <span class="nav-label">${item.label}</span>
        </a>`).join('');

    const auxChildrenHtml = AUXILIARY_NAV_ITEMS.map(item => `
        <a href="${item.href}" class="nav-sub-link ${currentPath.includes(item.key) ? 'active' : ''}"${currentPath.includes(item.key) ? ' aria-current="page"' : ''}>
            <span class="nav-sub-icon">${svg(item.icon, 14)}</span>
            <span class="nav-sub-label">${item.label}</span>
        </a>`).join('');

    const auxGroupHtml = `
        <div class="nav-group ${isAuxExpanded ? 'is-expanded' : 'is-collapsed'}" id="auxNavGroup">
            <button type="button" class="nav-group-header ${isAuxActive ? 'has-active-child' : ''}" id="auxNavToggle" aria-expanded="${isAuxExpanded ? 'true' : 'false'}" aria-controls="auxNavChildren" title="切換展開/收折輔助工具">
                <span class="nav-group-header-left">
                    <span class="nav-arrow-indicator">${svg('chevronRight', 13)}</span>
                    <span class="nav-group-title">輔助工具</span>
                </span>
                <span class="nav-group-count">${AUXILIARY_NAV_ITEMS.length}</span>
            </button>
            <div class="nav-group-children" id="auxNavChildren" style="${isAuxExpanded ? '' : 'display:none;'}">
                ${auxChildrenHtml}
            </div>
        </div>`;

    // 嚴格僅包含兩大頂層主分類：1. Settings（設定）與 2. Documentation（文件）
    const sidebarHtml = `
    <aside id="sidebar" aria-label="側邊欄導覽與系統控制">
        <a href="/" class="brand">${svg('book', 20)}<span>轉檔工具箱</span></a>

        <nav class="sidebar-ia-container" aria-label="主分類選單">
            <!-- ==================== PRIMARY CATEGORY 1: SETTINGS (設定) ==================== -->
            <section class="ia-category ${isSettingsCatExpanded ? 'is-expanded' : 'is-collapsed'}" id="iaCategorySettings">
                <button type="button"
                        class="ia-category-header ${hasActiveRouteInSettings ? 'has-active-child' : ''}"
                        id="catSettingsToggle"
                        aria-expanded="${isSettingsCatExpanded ? 'true' : 'false'}"
                        aria-controls="catSettingsPanel">
                    <span class="ia-category-header-left">
                        <span class="ia-category-icon">${svg('settings', 16)}</span>
                        <span class="ia-category-title-wrap">
                            <span class="ia-category-title">Settings</span>
                            <span class="ia-category-subtitle">設定</span>
                        </span>
                    </span>
                    <span class="ia-category-chevron">${svg('chevronRight', 14)}</span>
                </button>

                <div class="ia-category-panel" id="catSettingsPanel" role="region" aria-labelledby="catSettingsToggle" ${isSettingsCatExpanded ? '' : 'hidden'}>
                    <div class="ia-category-panel-inner">
                        <!-- 1.1 General Settings -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgGeneralTitle">
                            <div class="ia-subgroup-title" id="sgGeneralTitle">一般與工作流設定 (General)</div>
                            <div class="ia-nav-list">
                                ${mainNavHtml}
                            </div>
                            <button id="themeToggleBtn" class="ia-action-btn" type="button">
                                <span class="ia-action-btn-left">
                                    <span class="ia-action-icon" id="themeToggleIcon">${svg('moon', 15)}</span>
                                    <span id="themeToggleLabel">外觀主題：淺色模式</span>
                                </span>
                                <span class="ia-badge" id="themeToggleBadge">Light</span>
                            </button>
                        </div>

                        <!-- 1.2 OCR & Recognition Settings -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgOcrTitle">
                            <div class="ia-subgroup-title" id="sgOcrTitle">OCR 與識別設定 (Recognition)</div>
                            ${auxGroupHtml}
                        </div>

                        <!-- 1.3 Document Conversion Settings & 1.4 Output & Export Settings -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgOutputTitle">
                            <div class="ia-subgroup-title" id="sgOutputTitle">轉檔與輸出配額 (Conversion & Output)</div>
                            <div class="ia-kv-list" aria-label="轉檔與輸出配額參數">
                                <div class="ia-kv-row">
                                    <span class="ia-kv-label">單次上傳上限</span>
                                    <span class="ia-kv-val" id="cfgMaxUploadVal">${window.APP_CONFIG.maxUploadSizeMB} MB</span>
                                </div>
                                <div class="ia-kv-row">
                                    <span class="ia-kv-label">樣板檔案上限</span>
                                    <span class="ia-kv-val" id="cfgMaxTemplateVal">${window.APP_CONFIG.maxTemplateSizeMB} MB</span>
                                </div>
                                <div class="ia-kv-row">
                                    <span class="ia-kv-label">暫存自動清理</span>
                                    <span class="ia-kv-val" id="cfgRetentionVal">${window.APP_CONFIG.fileRetentionHours} 小時</span>
                                </div>
                            </div>
                        </div>

                        <!-- 1.5 Advanced Settings -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgAdvancedTitle">
                            <div class="ia-subgroup-title" id="sgAdvancedTitle">進階與系統維護 (Advanced)</div>
                            <button id="modeToggleBtn" class="sidebar-btn ia-control-btn" type="button" title="切換出版社編輯模式與工程師除錯模式">模式：讀取中</button>
                            <button id="checkUpdateBtn" class="sidebar-btn ia-control-btn" type="button" title="檢查是否有新版程式可供更新">
                                <span class="ia-btn-inline-icon">${svg('refresh', 13)}</span>
                                <span>檢查版本更新</span>
                            </button>
                        </div>
                    </div>
                </div>
            </section>

            <!-- ==================== PRIMARY CATEGORY 2: DOCUMENTATION (文件) ==================== -->
            <section class="ia-category ${isDocsCatExpanded ? 'is-expanded' : 'is-collapsed'}" id="iaCategoryDocs">
                <button type="button"
                        class="ia-category-header"
                        id="catDocsToggle"
                        aria-expanded="${isDocsCatExpanded ? 'true' : 'false'}"
                        aria-controls="catDocsPanel">
                    <span class="ia-category-header-left">
                        <span class="ia-category-icon">${svg('book', 16)}</span>
                        <span class="ia-category-title-wrap">
                            <span class="ia-category-title">Documentation</span>
                            <span class="ia-category-subtitle">文件</span>
                        </span>
                    </span>
                    <span class="ia-category-chevron">${svg('chevronRight', 14)}</span>
                </button>

                <div class="ia-category-panel" id="catDocsPanel" role="region" aria-labelledby="catDocsToggle" ${isDocsCatExpanded ? '' : 'hidden'}>
                    <div class="ia-category-panel-inner">
                        <!-- 2.1 ~ 2.4 Manuals, Formatting Specs & Guides -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgDocManualsTitle">
                            <div class="ia-subgroup-title" id="sgDocManualsTitle">操作指南與技術規格 (Guides & Specs)</div>
                            <div class="settings-doc-list" id="sidebarDocList">
                                <div class="ia-loading-hint">載入文件中...</div>
                            </div>
                        </div>

                        <!-- 2.5 Troubleshooting & Support -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgDocSupportTitle">
                            <div class="ia-subgroup-title" id="sgDocSupportTitle">疑難排解與支援 (Troubleshooting & FAQ)</div>
                            <button type="button" class="sidebar-doc-link" id="openDocCenterQuickBtn" title="開啟完整文件檢視中心">
                                <span class="doc-icon">${svg('list', 14)}</span>
                                <span class="doc-name">開啟完整文件檢視中心</span>
                            </button>
                            <button id="globalReportBtn" class="sidebar-btn ia-control-btn" type="button" style="display:none;" title="僅供工程師除錯使用">
                                <span class="ia-btn-inline-icon">${svg('github', 14)}</span>
                                <span>在 GitHub 回報問題</span>
                            </button>
                        </div>

                        <!-- 2.6 System Environment, Version & Privacy Specs -->
                        <div class="ia-subgroup" role="group" aria-labelledby="sgDocEnvTitle">
                            <div class="ia-subgroup-title" id="sgDocEnvTitle">系統環境與隱私規範 (System & Privacy)</div>
                            <div class="ia-env-card">
                                <div id="hardwareDisplay" class="sidebar-info-box">硬體加速：偵測中</div>
                                <div id="aiModelDisplay" class="sidebar-info-box">AI 推論：偵測中</div>
                                <div id="versionDisplay" class="sidebar-version-text">版本：讀取中</div>
                                <div class="sidebar-privacy">
                                    <strong>零日誌隱私架構</strong>
                                    <span>檔案保留 <span id="privacyRetentionHours">${window.APP_CONFIG.fileRetentionHours}</span> 小時後自動銷毀</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>
        </nav>
    </aside>

    <div id="docViewerModal" class="modal-overlay doc-viewer-modal" role="dialog" aria-modal="true" aria-labelledby="docViewerTitle">
        <div class="modal doc-modal-content">
            <div class="doc-modal-head">
                <div class="doc-modal-head-title">
                    <span class="doc-modal-head-icon">${svg('book', 20)}</span>
                    <div>
                        <h2 id="docViewerTitle" style="margin:0; font-size:1.15rem; font-weight:700;">技術與操作文件中心</h2>
                        <span id="docViewerSubtitle" class="doc-badge">載入中...</span>
                    </div>
                </div>
                <button id="closeDocViewerBtn" class="modal-close-btn" type="button" aria-label="關閉文件中心">
                    ${svg('close', 18)}
                </button>
            </div>
            <div class="doc-modal-body">
                <aside class="doc-modal-sidebar" id="docModalSidebar">
                    <div style="padding:1rem; color:var(--text-muted); font-size:0.85rem;">載入清單中...</div>
                </aside>
                <main class="doc-modal-article" id="docViewerArticle">
                    <div class="doc-loading">請由左側選擇欲閱讀之手冊或文件</div>
                </main>
            </div>
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

    // 行動端側邊欄展開/收折控制
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

    document.querySelectorAll('#sidebar a.nav-link, #sidebar a.nav-sub-link').forEach(link => {
        link.addEventListener('click', () => {
            const vp = /** @type {any} */ (window).viewportManager;
            if (vp && typeof vp.isMobile === 'function' && (vp.isMobile() || vp.isTablet())) {
                vp.closeSidebar();
            }
        });
    });

    // 通用兩大主分類 (Settings / Documentation) 展開與收折控制
    function setupPrimaryCategoryToggle(toggleId, panelId, containerId, storageKey) {
        const btn = document.getElementById(toggleId);
        const panel = document.getElementById(panelId);
        const container = document.getElementById(containerId);
        if (!btn || !panel || !container) return;

        btn.addEventListener('click', () => {
            const isExpanded = btn.getAttribute('aria-expanded') === 'true';
            const nextState = !isExpanded;
            btn.setAttribute('aria-expanded', nextState ? 'true' : 'false');
            container.classList.toggle('is-expanded', nextState);
            container.classList.toggle('is-collapsed', !nextState);
            if (nextState) {
                panel.removeAttribute('hidden');
            } else {
                panel.setAttribute('hidden', '');
            }
            localStorage.setItem(storageKey, nextState ? 'true' : 'false');
        });
    }

    setupPrimaryCategoryToggle('catSettingsToggle', 'catSettingsPanel', 'iaCategorySettings', 'sidebar_cat_settings_expanded');
    setupPrimaryCategoryToggle('catDocsToggle', 'catDocsPanel', 'iaCategoryDocs', 'sidebar_cat_docs_expanded');

    // 支援兩大主分類標題按鈕之間的上下方向鍵無障礙導覽
    const categoryHeaders = Array.from(document.querySelectorAll('.ia-category-header'));
    categoryHeaders.forEach((headerBtn, idx) => {
        headerBtn.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                const next = categoryHeaders[(idx + 1) % categoryHeaders.length];
                if (next) next.focus();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prev = categoryHeaders[(idx - 1 + categoryHeaders.length) % categoryHeaders.length];
                if (prev) prev.focus();
            } else if (e.key === 'Home') {
                e.preventDefault();
                if (categoryHeaders[0]) categoryHeaders[0].focus();
            } else if (e.key === 'End') {
                e.preventDefault();
                if (categoryHeaders[categoryHeaders.length - 1]) categoryHeaders[categoryHeaders.length - 1].focus();
            }
        });
    });

    // Settings > 1.2 OCR 與識別工具子群組折疊切換
    const auxNavToggle = document.getElementById('auxNavToggle');
    const auxNavGroup = document.getElementById('auxNavGroup');
    const auxNavChildren = document.getElementById('auxNavChildren');
    if (auxNavToggle && auxNavGroup && auxNavChildren) {
        auxNavToggle.onclick = () => {
            const isCurrentlyExpanded = auxNavGroup.classList.contains('is-expanded');
            const nextState = !isCurrentlyExpanded;
            auxNavGroup.classList.toggle('is-expanded', nextState);
            auxNavGroup.classList.toggle('is-collapsed', !nextState);
            auxNavToggle.setAttribute('aria-expanded', nextState ? 'true' : 'false');
            auxNavChildren.style.display = nextState ? '' : 'none';
            localStorage.setItem('sidebar_aux_expanded', nextState ? 'true' : 'false');
        };
    }

    // 技術與操作文件檢視中心 (Doc Viewer Modal)
    const docModal = document.getElementById('docViewerModal');
    const closeDocViewerBtn = document.getElementById('closeDocViewerBtn');
    const docViewerTitle = document.getElementById('docViewerTitle');
    const docViewerSubtitle = document.getElementById('docViewerSubtitle');
    const docViewerArticle = document.getElementById('docViewerArticle');
    const docCache = {};
    let availableDocs = [];

    async function loadAndShowDoc(docId) {
        if (!docId) return;

        document.querySelectorAll('.doc-tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.docId === docId);
        });

        docViewerArticle.innerHTML = '<div class="doc-loading">正在載入文件內容...</div>';
        docModal.classList.add('open');

        if (docCache[docId]) {
            renderDoc(docCache[docId]);
            return;
        }

        try {
            const res = await fetch(`/api/docs/${encodeURIComponent(docId)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            docCache[docId] = data;
            renderDoc(data);
        } catch (err) {
            docViewerArticle.innerHTML = `
                <div style="padding:2rem; text-align:center;">
                    <p style="color:var(--danger); font-weight:600; font-size:1.05rem;">文件載入失敗</p>
                    <p class="hint" style="margin-top:0.5rem;">${window.toolbox.escape(err.message)}</p>
                </div>`;
        }
    }

    function renderDoc(data) {
        docViewerTitle.textContent = data.title || '技術與操作文件中心';
        docViewerSubtitle.textContent = data.category || '說明文件';
        const descBanner = data.description ? `<div class="doc-modal-desc-banner" style="margin-bottom:1.25rem; padding:0.75rem 1rem; background:var(--f2-color-surface-secondary, #f8fafc); border-left:3px solid var(--f2-color-primary, #0F6CBD); border-radius:4px; font-size:0.88rem; color:var(--f2-color-text-secondary, #616161);">${window.toolbox.escape(data.description)}</div>` : '';
        docViewerArticle.innerHTML = descBanner + (data.html || `<pre style="white-space:pre-wrap;">${window.toolbox.escape(data.markdown || '')}</pre>`);
        docViewerArticle.scrollTop = 0;
    }

    window.toolbox.openDocViewer = loadAndShowDoc;

    const openDocCenterQuickBtn = document.getElementById('openDocCenterQuickBtn');
    if (openDocCenterQuickBtn) {
        openDocCenterQuickBtn.onclick = () => {
            const defaultDocId = (availableDocs[0] && availableDocs[0].id) || 'workflow';
            loadAndShowDoc(defaultDocId);
            const vp = /** @type {any} */ (window).viewportManager;
            if (vp && typeof vp.isMobile === 'function' && (vp.isMobile() || vp.isTablet())) {
                vp.closeSidebar();
            }
        };
    }

    async function loadAndRenderDocCatalogue(currentMode) {
        try {
            const url = currentMode ? `/api/docs?mode=${encodeURIComponent(currentMode)}` : '/api/docs';
            const res = await fetch(url);
            let docs = [];
            if (res.ok) {
                docs = await res.json();
            } else {
                docs = [
                    { id: 'workflow', title: '全流程操作指南', category: '操作手冊', icon: 'book', description: '全自動整稿 & POD' },
                    { id: 'about', title: '系統授權與內網部署', category: '操作手冊', icon: 'shield', description: '開源授權與私有化規範' }
                ];
                if (currentMode === 'dev') {
                    docs.push(
                        { id: 'modules', title: '核心模組技術說明', category: '技術規格', icon: 'cpu', description: '雙引擎、YOLOv8、方正' },
                        { id: 'glossary', title: '名詞定義與術語表', category: '技術規格', icon: 'list', description: '系統排版術語彙編' },
                        { id: 'decisions', title: '架構設計決策記錄', category: '技術規格', icon: 'fileText', description: 'ADR 關鍵設計決策' }
                    );
                }
            }
            availableDocs = docs;

            // 1. Render inside Documentation category (#sidebarDocList)
            const docListEl = document.getElementById('sidebarDocList');
            if (docListEl) {
                const dropdownHtml = docs.map(d => `
                    <button type="button" class="sidebar-doc-link" data-doc-id="${window.toolbox.escape(d.id)}" title="${window.toolbox.escape(d.title)}">
                        <span class="doc-icon">${svg(d.icon || 'fileText', 14)}</span>
                        <span class="doc-name">${window.toolbox.escape(d.title)}</span>
                    </button>
                `).join('');

                docListEl.innerHTML = dropdownHtml;

                docListEl.querySelectorAll('.sidebar-doc-link[data-doc-id]').forEach(btn => {
                    btn.onclick = () => {
                        const docId = btn.dataset.docId;
                        if (docId) {
                            loadAndShowDoc(docId);
                            const vp = /** @type {any} */ (window).viewportManager;
                            if (vp && typeof vp.isMobile === 'function' && (vp.isMobile() || vp.isTablet())) {
                                vp.closeSidebar();
                            }
                        }
                    };
                });
            }

            // 2. Render inside Doc Viewer Modal sidebar
            const modalSidebarEl = document.getElementById('docModalSidebar');
            if (modalSidebarEl) {
                const categories = {};
                docs.forEach(d => {
                    const cat = d.category || '手冊與文件';
                    if (!categories[cat]) categories[cat] = [];
                    categories[cat].push(d);
                });

                let modalNavHtml = '';
                for (const [catName, catDocs] of Object.entries(categories)) {
                    modalNavHtml += `<div class="doc-nav-heading">${window.toolbox.escape(catName)}</div>`;
                    catDocs.forEach(d => {
                        modalNavHtml += `
                            <button type="button" class="doc-tab-btn" data-doc-id="${window.toolbox.escape(d.id)}">
                                <span class="doc-tab-icon">${svg(d.icon || 'fileText', 14)}</span>
                                <span>${window.toolbox.escape(d.title)}</span>
                            </button>
                        `;
                    });
                }

                modalSidebarEl.innerHTML = modalNavHtml;

                modalSidebarEl.querySelectorAll('.doc-tab-btn').forEach(btn => {
                    btn.onclick = () => {
                        const docId = btn.dataset.docId;
                        if (docId) loadAndShowDoc(docId);
                    };
                });
            }
        } catch (err) {
            console.error('Failed to load doc catalogue:', err);
        }
    }

    if (closeDocViewerBtn) {
        closeDocViewerBtn.onclick = () => docModal.classList.remove('open');
    }
    if (docModal) {
        docModal.addEventListener('click', (e) => {
            if (e.target === docModal) docModal.classList.remove('open');
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && docModal && docModal.classList.contains('open')) {
            docModal.classList.remove('open');
        }
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

    const globalReportBtn = document.getElementById('globalReportBtn');
    if (globalReportBtn) {
        globalReportBtn.onclick = () => {
            const repo = 'RandyXie04/doc-image-extractor';
            const title = encodeURIComponent('[問題回報] 請簡述您遇到的問題');
            const versionText = versionDisplay ? (versionDisplay.textContent || 'App 版本未知') : '未知版本';
            const body = `### 問題描述
<!-- 請描述異常現象、錯誤訊息或改進建議 -->

### 系統資訊
- **應用版本**: ${versionText}
- **瀏覽器**: ${navigator.userAgent}
- **回報時間**: ${new Date().toLocaleString()}`;
            window.open(`https://github.com/${repo}/issues/new?title=${title}&body=${encodeURIComponent(body)}`, '_blank');
        };
    }

    if (versionDisplay) {
        fetch('/api/version').then(res => res.json()).then(data => {
            versionDisplay.textContent = `App v${data.app_version} · Model v${data.model_version}`;
        }).catch((err) => {
            console.debug('[Version] Fetch error:', err);
            versionDisplay.textContent = '無法讀取版本資訊';
        });
    }

    const hardwareDisplay = document.getElementById('hardwareDisplay');
    if (hardwareDisplay) {
        fetch('/api/hardware_status').then(res => res.json()).then(data => {
            if (data.is_accelerated) {
                const gpuName = (data.gpu_name || '').replace('NVIDIA GeForce ', '').replace('NVIDIA ', '');
                hardwareDisplay.classList.add('is-accelerated');
                hardwareDisplay.innerHTML = `${svg('chip', 12)} GPU 加速：${window.toolbox.escape(gpuName)}`;
            } else {
                hardwareDisplay.innerHTML = `${svg('chip', 12)} CPU 相容模式`;
            }
        }).catch((err) => {
            console.debug('[Hardware] Fetch error:', err);
            hardwareDisplay.textContent = '硬體探測離線';
        });
    }

    const aiModelDisplay = document.getElementById('aiModelDisplay');
    if (aiModelDisplay) {
        fetch('/api/system_config').then(res => res.json()).then(cfg => {
            const isOllama = cfg.ollama_available;
            const modelName = cfg.ollama_model || cfg.default_ai_model || 'qwen3.5:4b';
            const statusLabel = isOllama ? 'Ollama 就緒' : '離線就緒';
            aiModelDisplay.innerHTML = `${svg('chip', 12)} AI：${window.toolbox.escape(modelName)} (${statusLabel})`;
            if (isOllama) aiModelDisplay.classList.add('is-accelerated');
        }).catch((err) => {
            console.debug('[AIModel] Fetch error:', err);
            aiModelDisplay.textContent = 'AI：本地離線隔離';
        });
    }

    if (closeUpdateBtn) {
        closeUpdateBtn.onclick = () => updateModal && updateModal.classList.remove('open');
    }
    if (updateModal) {
        updateModal.addEventListener('click', (e) => {
            if (e.target === updateModal && (!closeUpdateBtn || !closeUpdateBtn.disabled)) updateModal.classList.remove('open');
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && updateModal && (!closeUpdateBtn || !closeUpdateBtn.disabled)) updateModal.classList.remove('open');
    });

    if (checkUpdateBtn) {
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
                    if (applyUpdateBtn) applyUpdateBtn.disabled = !currentDownloadUrl;
                    updateModal.classList.add('open');
                } else {
                    window.toolbox.notify(data.msg || '目前已是最新版本。', data.status === 'error' ? 'warning' : 'success');
                }
            } catch (err) {
                console.debug('[CheckUpdate] Failed:', err);
                window.toolbox.notify('檢查更新失敗，請確認網路連線後再試。', 'error');
            } finally {
                checkUpdateBtn.disabled = false;
                checkUpdateBtn.innerHTML = originalHtml;
            }
        };
    }

    if (applyUpdateBtn) {
        applyUpdateBtn.onclick = async () => {
            if (!currentDownloadUrl) return;
            applyUpdateBtn.disabled = true;
            if (closeUpdateBtn) closeUpdateBtn.disabled = true;
            if (updateMsg) updateMsg.textContent = '正在背景下載新版程式，請勿關閉此視窗。';
            try {
                const res = await fetch('/api/apply_update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ download_url: currentDownloadUrl })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (updateMsg) updateMsg.textContent = '下載完成，系統即將重新啟動。';
                } else {
                    if (updateMsg) updateMsg.textContent = '更新失敗：' + (data.msg || data.detail || '未知錯誤');
                    applyUpdateBtn.disabled = false;
                    if (closeUpdateBtn) closeUpdateBtn.disabled = false;
                }
            } catch (err) {
                console.debug('[ApplyUpdate] Failed:', err);
                if (updateMsg) updateMsg.textContent = '網路錯誤，請稍後再試。';
                applyUpdateBtn.disabled = false;
                if (closeUpdateBtn) closeUpdateBtn.disabled = false;
            }
        };
    }

    // Settings > 1.5 Advanced Settings: 模式切換與工程師 Telemetry HUD
    const modeToggleBtn = document.getElementById('modeToggleBtn');
    const MODE_LABEL = { editor: '出版社編輯模式', dev: '工程師除錯模式' };
    let telemetryTimer = null;

    function renderDevTelemetry(data) {
        let hud = document.getElementById('devTelemetryHUD');
        if (!hud) {
            hud = document.createElement('div');
            hud.id = 'devTelemetryHUD';
            hud.className = 'sidebar-telemetry-hud';
            if (modeToggleBtn && modeToggleBtn.parentElement) {
                modeToggleBtn.parentElement.insertBefore(hud, modeToggleBtn.nextSibling);
            }
        }
        const vramText = data.total_vram_gb > 0
            ? `${data.reserved_vram_mb} MB / ${(data.total_vram_gb * 1024).toFixed(0)} MB (${data.vram_usage_percent}%)`
            : 'CPU 模式';
        const lockStatus = data.gpu_locked
            ? '<span class="telemetry-status-busy">運算中</span>'
            : '<span class="telemetry-status-idle">閒置</span>';

        hud.innerHTML = `
            <div class="telemetry-hud-head">
                <span>${window.toolbox.escape(data.gpu_name)}</span>
                <span>${window.toolbox.escape(data.target_accelerator)}</span>
            </div>
            <div>VRAM: ${window.toolbox.escape(vramText)}</div>
            <div>佇列狀態: ${lockStatus}</div>
        `;
    }

    async function pollTelemetry() {
        try {
            const res = await fetch('/api/dev/telemetry');
            if (res.ok) {
                const data = await res.json();
                renderDevTelemetry(data);
            }
        } catch (err) {
            console.debug('[Telemetry] Poll skipped:', err);
        }
    }

    function updateModeBtnUI(mode) {
        if (!modeToggleBtn) return;
        modeToggleBtn.dataset.mode = mode;
        modeToggleBtn.textContent = `模式：${MODE_LABEL[mode] || mode}`;
        modeToggleBtn.classList.toggle('is-active', mode === 'dev');
        if (globalReportBtn) {
            globalReportBtn.style.display = (mode === 'dev') ? 'flex' : 'none';
        }
        const hud = document.getElementById('devTelemetryHUD');
        if (mode === 'dev') {
            pollTelemetry();
            if (!telemetryTimer) telemetryTimer = setInterval(pollTelemetry, 4000);
        } else {
            if (telemetryTimer) {
                clearInterval(telemetryTimer);
                telemetryTimer = null;
            }
            if (hud) hud.remove();
        }
        loadAndRenderDocCatalogue(mode);
    }

    const isDevPreset = localStorage.getItem('developer_engineer_mode') === 'true';
    fetch('/api/app_mode').then(r => r.json()).then(d => {
        const mode = d && d.mode ? d.mode : (isDevPreset ? 'dev' : 'editor');
        if (isDevPreset && d && d.mode !== 'dev') {
            fetch('/api/set_app_mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'dev' })
            }).then(() => updateModeBtnUI('dev')).catch(() => updateModeBtnUI(mode));
        } else {
            updateModeBtnUI(mode);
        }
    }).catch((err) => {
        console.debug('[AppMode] Fetch skipped:', err);
        if (modeToggleBtn) modeToggleBtn.textContent = isDevPreset ? '模式：工程師除錯模式' : '模式：未知';
        loadAndRenderDocCatalogue(isDevPreset ? 'dev' : 'editor');
    });

    if (modeToggleBtn) {
        modeToggleBtn.onclick = async () => {
            const targetMode = modeToggleBtn.dataset.mode === 'dev' ? 'editor' : 'dev';
            localStorage.setItem('developer_engineer_mode', targetMode === 'dev' ? 'true' : 'false');
            try {
                const res = await fetch('/api/set_app_mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: targetMode })
                });
                const d = await res.json();
                if (d.status === 'success') {
                    window.dispatchEvent(new CustomEvent('appModeChanged', { detail: { mode: d.mode } }));
                    document.dispatchEvent(new CustomEvent('appModeChanged', { detail: { mode: d.mode } }));
                    updateModeBtnUI(d.mode);
                    const msg = d.mode === 'dev'
                        ? '已切換為工程師除錯模式：顯示處理日誌與內部目錄。'
                        : '已切換為出版社編輯模式：隱藏處理日誌與內部目錄。';
                    if (window.toolbox && window.toolbox.notify) {
                        window.toolbox.notify(msg, 'success');
                    }
                }
            } catch (err) {
                window.toolbox.notify('模式切換失敗：' + err.message, 'error');
            }
        };
    }

    // Settings > 1.1 General Settings: 深淺色主題切換（整合於側邊欄 Settings 內）
    const savedTheme = localStorage.getItem('app-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);

    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const themeToggleIcon = document.getElementById('themeToggleIcon');
    const themeToggleLabel = document.getElementById('themeToggleLabel');
    const themeToggleBadge = document.getElementById('themeToggleBadge');

    function updateThemeToggleUI(theme) {
        if (!themeToggleBtn) return;
        const isDark = theme === 'dark';
        if (themeToggleIcon) themeToggleIcon.innerHTML = svg(isDark ? 'sun' : 'moon', 15);
        if (themeToggleLabel) themeToggleLabel.textContent = isDark ? '外觀主題：深色模式' : '外觀主題：淺色模式';
        if (themeToggleBadge) themeToggleBadge.textContent = isDark ? 'Dark' : 'Light';
        const actionTitle = isDark ? '切換為淺色模式' : '切換為深色模式';
        themeToggleBtn.title = actionTitle;
        themeToggleBtn.setAttribute('aria-label', actionTitle);
        themeToggleBtn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    }
    updateThemeToggleUI(savedTheme);

    if (themeToggleBtn) {
        themeToggleBtn.onclick = () => {
            const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('app-theme', newTheme);
            updateThemeToggleUI(newTheme);
        };
    }
});
