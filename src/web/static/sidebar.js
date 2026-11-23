// @ts-nocheck
// Shared client config, notifications, and modular 3-zone sidebar shell.
window.APP_CONFIG = {
    maxUploadSizeMB: 200,
    maxTemplateSizeMB: 20,
    fileRetentionHours: 24
};

let pendingDocOpenId = null;

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
    },
    openDocViewer(docId) {
        pendingDocOpenId = docId || 'workflow';
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
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'
};

function svg(name, size = 16) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name] || ''}</svg>`;
}

const MODE_LABEL = { editor: '出版社編輯模式', dev: '工程師除錯模式' };
const MODE_PILL = { editor: '編輯', dev: '除錯' };

document.addEventListener('DOMContentLoaded', () => {
    const pending = sessionStorage.getItem('tb-toast');
    if (pending) {
        sessionStorage.removeItem('tb-toast');
        window.toolbox.notify(pending, 'success');
    }

    if (document.getElementById('sidebar')) return;

    const savedAuxState = localStorage.getItem('sidebar_aux_expanded');
    const initialAuxExpanded = savedAuxState !== 'false';

    const sidebarHtml = `
    <aside id="sidebar" aria-label="側邊欄導覽與系統控制">
        <a href="/" class="brand">${svg('book', 20)}<span>轉檔工具箱</span></a>

        <!-- Zone 1: Primary Navigation (Core Workflows + Auxiliary Tools) -->
        <nav class="sidebar-nav-zone" id="sidebarPrimaryNav" aria-label="主導覽">
            <div class="sidebar-section-label" id="navWorkflowLabel">核心工作流程</div>
            <div class="sidebar-nav-list" id="mainNavList" role="list" aria-labelledby="navWorkflowLabel"></div>

            <div class="nav-group ${initialAuxExpanded ? 'is-expanded' : 'is-collapsed'}" id="auxNavGroup">
                <button type="button"
                        class="nav-group-header"
                        id="auxNavToggle"
                        aria-expanded="${initialAuxExpanded ? 'true' : 'false'}"
                        aria-controls="auxNavChildren"
                        title="切換展開/收折專項輔助工具">
                    <span class="nav-group-header-left">
                        <span class="nav-arrow-indicator">${svg('chevronRight', 13)}</span>
                        <span class="nav-group-title">專項輔助工具</span>
                    </span>
                    <span class="nav-group-count" id="auxNavCount">0</span>
                </button>
                <div class="nav-group-children" id="auxNavChildren" role="list"${initialAuxExpanded ? '' : ' hidden'}></div>
            </div>
        </nav>

        <!-- Zone 2: Workspace Tools & Documentation Entry -->
        <div class="sidebar-tools-zone" id="sidebarWorkspaceTools" role="region" aria-label="工作區工具與文件">
            <div class="sidebar-section-label" id="workspaceToolsLabel">工作區與文件</div>
            <button id="themeToggleBtn" class="sidebar-tool-btn" type="button">
                <span class="sidebar-tool-btn-left">
                    <span class="sidebar-tool-icon" id="themeToggleIcon">${svg('moon', 15)}</span>
                    <span id="themeToggleLabel">外觀主題：淺色模式</span>
                </span>
                <span class="sidebar-tool-badge" id="themeToggleBadge">Light</span>
            </button>
            <button id="openDocCenterBtn" class="sidebar-tool-btn" type="button" title="開啟操作指南與技術文件中心">
                <span class="sidebar-tool-btn-left">
                    <span class="sidebar-tool-icon">${svg('book', 15)}</span>
                    <span>操作指南與文件</span>
                </span>
                <span class="sidebar-tool-arrow">${svg('chevronRight', 14)}</span>
            </button>
        </div>

        <!-- Zone 3: Compact System Status Footer & Maintenance Popover -->
        <footer class="sidebar-system-footer" id="sidebarSystemFooter" aria-label="系統狀態與維護">
            <div id="devTelemetrySlot"></div>

            <div class="system-status-popover" id="systemStatusPopover" role="region" aria-labelledby="systemStatusToggle" hidden>
                <div class="system-popover-info">
                    <div id="hardwareDisplay" class="sidebar-info-box">硬體加速：偵測中</div>
                    <div id="aiModelDisplay" class="sidebar-info-box">AI 推論：偵測中</div>
                    <div id="versionDisplay" class="sidebar-version-text">版本：讀取中</div>
                    <div class="sidebar-quota-summary">
                        配額：上傳 <strong id="cfgMaxUploadVal">${window.APP_CONFIG.maxUploadSizeMB} MB</strong> ·
                        樣板 <strong id="cfgMaxTemplateVal">${window.APP_CONFIG.maxTemplateSizeMB} MB</strong> ·
                        暫存 <strong id="cfgRetentionVal">${window.APP_CONFIG.fileRetentionHours} 小時</strong>
                    </div>
                </div>
                <div class="system-popover-actions">
                    <button id="modeToggleBtn" class="sidebar-btn" type="button" aria-pressed="false" title="切換出版社編輯模式與工程師除錯模式">模式：讀取中</button>
                    <button id="checkUpdateBtn" class="sidebar-btn" type="button" title="檢查是否有新版程式可供更新">
                        <span class="ia-btn-inline-icon">${svg('refresh', 13)}</span>
                        <span>檢查版本更新</span>
                    </button>
                    <button id="globalReportBtn" class="sidebar-btn" type="button" hidden title="僅供工程師除錯使用">
                        <span class="ia-btn-inline-icon">${svg('github', 14)}</span>
                        <span>在 GitHub 回報問題</span>
                    </button>
                </div>
            </div>

            <button type="button"
                    class="system-status-toggle"
                    id="systemStatusToggle"
                    aria-expanded="false"
                    aria-controls="systemStatusPopover">
                <span class="system-status-left">
                    <span class="system-status-dot" id="systemStatusDot" aria-hidden="true"></span>
                    <span class="system-status-meta">
                        <span class="system-status-title" id="statusSummaryText">系統偵測中</span>
                        <span class="system-status-version" id="statusVersionBadge">版本讀取中</span>
                    </span>
                </span>
                <span class="system-status-right">
                    <span class="system-mode-pill" id="statusModeBadge">編輯</span>
                    <span class="system-status-chevron">${svg('chevronRight', 14)}</span>
                </span>
            </button>
        </footer>
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
                <aside class="doc-modal-sidebar" id="docModalSidebar" aria-label="文件目錄">
                    <div class="ia-loading-hint">載入清單中...</div>
                </aside>
                <article class="doc-modal-article" id="docViewerArticle" tabindex="0">
                    <div class="doc-loading">請由左側選擇欲閱讀之手冊或文件</div>
                </article>
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
    const mainContent = document.createElement('main');
    mainContent.id = 'main-content';
    bodyContents.forEach((node) => mainContent.appendChild(node));

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

    ['sidebar.css', 'toolbox.css'].forEach((name) => {
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

    function closeDrawerIfMobile() {
        const vp = /** @type {any} */ (window).viewportManager;
        if (vp && typeof vp.isMobile === 'function' && (vp.isMobile() || vp.isTablet())) {
            vp.closeSidebar();
        }
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

    const sidebarEl = document.getElementById('sidebar');
    if (sidebarEl) {
        sidebarEl.addEventListener('click', (e) => {
            const target = e.target;
            if (target instanceof Element && target.closest('a.nav-link, a.nav-sub-link')) {
                closeDrawerIfMobile();
            }
        });
    }

    const auxNavToggle = document.getElementById('auxNavToggle');
    const auxNavGroup = document.getElementById('auxNavGroup');
    const auxNavChildren = document.getElementById('auxNavChildren');
    function setAuxExpanded(expanded, persist = true) {
        if (!auxNavToggle || !auxNavGroup || !auxNavChildren) return;
        auxNavGroup.classList.toggle('is-expanded', expanded);
        auxNavGroup.classList.toggle('is-collapsed', !expanded);
        auxNavToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        auxNavChildren.hidden = !expanded;
        if (persist) {
            localStorage.setItem('sidebar_aux_expanded', expanded ? 'true' : 'false');
        }
    }
    if (auxNavToggle) {
        auxNavToggle.addEventListener('click', () => {
            const currentlyExpanded = auxNavToggle.getAttribute('aria-expanded') === 'true';
            setAuxExpanded(!currentlyExpanded, true);
        });
    }

    const systemFooter = document.getElementById('sidebarSystemFooter');
    const systemStatusToggle = document.getElementById('systemStatusToggle');
    const systemStatusPopover = document.getElementById('systemStatusPopover');
    function setStatusPopoverOpen(open) {
        if (!systemFooter || !systemStatusToggle || !systemStatusPopover) return;
        systemFooter.classList.toggle('is-popover-open', open);
        systemStatusToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        systemStatusPopover.hidden = !open;
    }
    if (systemStatusToggle && systemStatusPopover) {
        systemStatusToggle.addEventListener('click', () => {
            const isOpen = systemStatusToggle.getAttribute('aria-expanded') === 'true';
            setStatusPopoverOpen(!isOpen);
        });
        systemStatusPopover.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                setStatusPopoverOpen(false);
                systemStatusToggle.focus();
            }
        });
    }

    function renderNavigation(plugins) {
        const curPath = window.location.pathname;
        const isPluginActive = (item) => Boolean(
            curPath.includes(item.id) || (item.entry_url && curPath.endsWith(item.entry_url.split('/').pop()))
        );

        const corePlugins = (plugins || []).filter((p) => p.category === 'core_typesetting' && p.is_enabled);
        const auxPlugins = (plugins || []).filter((p) => p.category === 'auxiliary_task' && p.is_enabled);

        const mainNavList = document.getElementById('mainNavList');
        if (mainNavList) {
            mainNavList.innerHTML = corePlugins.map((item) => {
                const active = isPluginActive(item);
                return `
                <a href="${item.entry_url}" class="nav-link ${active ? 'active' : ''}" role="listitem"${active ? ' aria-current="page"' : ''}>
                    <span class="nav-icon">${svg(item.icon, 15)}</span>
                    <span class="nav-label">${window.toolbox.escape(item.name)}</span>
                </a>`;
            }).join('');
        }

        const auxCountEl = document.getElementById('auxNavCount');
        const hasAuxActive = auxPlugins.some(isPluginActive);
        if (auxNavChildren) {
            auxNavChildren.innerHTML = auxPlugins.map((item) => {
                const active = isPluginActive(item);
                return `
                <a href="${item.entry_url}" class="nav-sub-link ${active ? 'active' : ''}" role="listitem"${active ? ' aria-current="page"' : ''}>
                    <span class="nav-sub-icon">${svg(item.icon, 14)}</span>
                    <span class="nav-sub-label">${window.toolbox.escape(item.name)}</span>
                </a>`;
            }).join('');
        }
        if (auxCountEl) auxCountEl.textContent = String(auxPlugins.length);
        if (auxNavToggle) auxNavToggle.classList.toggle('has-active-child', hasAuxActive);
        if (hasAuxActive) setAuxExpanded(true, false);
    }

    function renderSystemMetadata(state) {
        const upEl = document.getElementById('cfgMaxUploadVal');
        const tplEl = document.getElementById('cfgMaxTemplateVal');
        const retEl = document.getElementById('cfgRetentionVal');
        if (upEl) upEl.textContent = `${state.config.max_upload_size_mb} MB`;
        if (tplEl) tplEl.textContent = `${state.config.max_template_size_mb} MB`;
        if (retEl) retEl.textContent = `${state.config.file_retention_hours} 小時`;

        const versionDisplay = document.getElementById('versionDisplay');
        const statusVersionBadge = document.getElementById('statusVersionBadge');
        if (state.version) {
            if (versionDisplay) {
                versionDisplay.textContent = `App v${state.version.app_version} · Model v${state.version.model_version}`;
            }
            if (statusVersionBadge) {
                statusVersionBadge.textContent = `v${state.version.app_version}`;
            }
        } else if (state.loaded) {
            if (versionDisplay) versionDisplay.textContent = '無法讀取版本資訊';
            if (statusVersionBadge) statusVersionBadge.textContent = '離線';
        }

        const hardwareDisplay = document.getElementById('hardwareDisplay');
        const statusSummaryText = document.getElementById('statusSummaryText');
        const statusDot = document.getElementById('systemStatusDot');
        if (state.hardware) {
            const isAccel = Boolean(state.hardware.is_accelerated);
            const shortGpu = (state.hardware.gpu_name || '').replace('NVIDIA GeForce ', '').replace('NVIDIA ', '');
            if (hardwareDisplay) {
                hardwareDisplay.classList.toggle('is-accelerated', isAccel);
                hardwareDisplay.innerHTML = isAccel
                    ? `${svg('chip', 12)} GPU 加速：${window.toolbox.escape(shortGpu)}`
                    : `${svg('chip', 12)} CPU 相容模式`;
            }
            if (statusSummaryText) {
                statusSummaryText.textContent = isAccel ? (shortGpu || 'GPU 就緒') : 'CPU 模式';
            }
            if (statusDot) {
                statusDot.classList.toggle('is-accelerated', isAccel);
            }
        } else if (state.loaded) {
            if (hardwareDisplay) hardwareDisplay.textContent = '硬體探測離線';
            if (statusSummaryText) statusSummaryText.textContent = '離線狀態';
        }

        const aiModelDisplay = document.getElementById('aiModelDisplay');
        if (aiModelDisplay) {
            const isOllama = Boolean(state.config.ollama_available);
            const modelName = state.config.ollama_model || state.config.default_ai_model || 'qwen3.5:4b';
            const statusLabel = isOllama ? 'Ollama 就緒' : '離線就緒';
            aiModelDisplay.classList.toggle('is-accelerated', isOllama);
            aiModelDisplay.innerHTML = `${svg('chip', 12)} AI：${window.toolbox.escape(modelName)} (${statusLabel})`;
        }

        const modeToggleBtn = document.getElementById('modeToggleBtn');
        const statusModeBadge = document.getElementById('statusModeBadge');
        const globalReportBtn = document.getElementById('globalReportBtn');
        const isDev = state.mode === 'dev';

        if (modeToggleBtn) {
            modeToggleBtn.dataset.mode = state.mode;
            modeToggleBtn.textContent = `模式：${MODE_LABEL[state.mode] || state.mode}`;
            modeToggleBtn.classList.toggle('is-dev', isDev);
            modeToggleBtn.setAttribute('aria-pressed', isDev ? 'true' : 'false');
        }
        if (statusModeBadge) {
            statusModeBadge.textContent = MODE_PILL[state.mode] || state.mode;
            statusModeBadge.classList.toggle('is-dev', isDev);
        }
        if (globalReportBtn) {
            globalReportBtn.hidden = !isDev;
        }
    }

    Promise.all([
        import('/static/js/sidebar/system_store.js'),
        import('/static/js/sidebar/theme_manager.js'),
        import('/static/js/sidebar/doc_modal.js'),
        import('/static/js/sidebar/dev_telemetry.js')
    ]).then(([storeMod, themeMod, docMod, telemetryMod]) => {
        themeMod.initThemeToggle({
            btn: document.getElementById('themeToggleBtn'),
            iconEl: document.getElementById('themeToggleIcon'),
            labelEl: document.getElementById('themeToggleLabel'),
            badgeEl: document.getElementById('themeToggleBadge')
        }, svg);

        const docCtrl = docMod.initDocModal({
            modalEl: document.getElementById('docViewerModal'),
            closeBtnEl: document.getElementById('closeDocViewerBtn'),
            titleEl: document.getElementById('docViewerTitle'),
            subtitleEl: document.getElementById('docViewerSubtitle'),
            sidebarEl: document.getElementById('docModalSidebar'),
            articleEl: document.getElementById('docViewerArticle')
        }, svg, window.toolbox.escape);

        window.toolbox.openDocViewer = (docId) => docCtrl.openDocViewer(docId);
        if (pendingDocOpenId) {
            const queuedId = pendingDocOpenId;
            pendingDocOpenId = null;
            docCtrl.openDocViewer(queuedId);
        }

        const openDocCenterBtn = document.getElementById('openDocCenterBtn');
        if (openDocCenterBtn) {
            openDocCenterBtn.addEventListener('click', () => {
                docCtrl.openDocViewer(docCtrl.getDefaultDocId(), openDocCenterBtn);
                closeDrawerIfMobile();
            });
        }

        const telemetryCtrl = telemetryMod.initDevTelemetry(
            document.getElementById('devTelemetrySlot'),
            window.toolbox.escape
        );

        const applyState = (state) => {
            renderNavigation(state.plugins);
            renderSystemMetadata(state);
            docCtrl.setDocs(state.docs);
            telemetryCtrl.syncMode(state.mode);
        };

        applyState(storeMod.getState());
        storeMod.subscribe(applyState);
        void storeMod.loadBootstrap();

        const modeToggleBtn = document.getElementById('modeToggleBtn');
        if (modeToggleBtn) {
            modeToggleBtn.addEventListener('click', async () => {
                const targetMode = modeToggleBtn.dataset.mode === 'dev' ? 'editor' : 'dev';
                const result = await storeMod.setMode(targetMode);
                window.toolbox.notify(result.message, result.kind);
            });
        }

        const updateModalEl = document.getElementById('updateModal');
        const closeUpdateBtn = document.getElementById('closeUpdateBtn');
        const applyUpdateBtn = document.getElementById('applyUpdateBtn');
        const updateVersionText = document.getElementById('updateVersionText');
        const updateReleaseNotes = document.getElementById('updateReleaseNotes');
        const updateMsg = document.getElementById('updateMsg');
        const checkUpdateBtn = document.getElementById('checkUpdateBtn');
        let currentDownloadUrl = null;

        const updateModalCtrl = docMod.bindModalA11y(
            updateModalEl,
            closeUpdateBtn,
            () => !closeUpdateBtn || !closeUpdateBtn.disabled
        );

        if (checkUpdateBtn) {
            checkUpdateBtn.addEventListener('click', async () => {
                checkUpdateBtn.disabled = true;
                const originalHtml = checkUpdateBtn.innerHTML;
                checkUpdateBtn.textContent = '檢查中…';
                try {
                    const res = await fetch('/api/check_update', { method: 'POST' });
                    const data = await res.json();
                    if (data.has_update) {
                        if (updateVersionText) updateVersionText.textContent = `最新版本：v${data.latest_version}`;
                        if (updateReleaseNotes) updateReleaseNotes.textContent = data.release_notes || '此版本未提供發布說明。';
                        currentDownloadUrl = data.download_url;
                        if (updateMsg) {
                            updateMsg.textContent = currentDownloadUrl ? '' : '此版本尚未附帶可執行檔，請改至 GitHub Releases 手動下載。';
                        }
                        if (applyUpdateBtn) applyUpdateBtn.disabled = !currentDownloadUrl;
                        updateModalCtrl.open(checkUpdateBtn);
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
            });
        }

        if (applyUpdateBtn) {
            applyUpdateBtn.addEventListener('click', async () => {
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
            });
        }

        const globalReportBtn = document.getElementById('globalReportBtn');
        if (globalReportBtn) {
            globalReportBtn.addEventListener('click', () => {
                const repo = 'RandyXie04/doc-image-extractor';
                const title = encodeURIComponent('[問題回報] 請簡述您遇到的問題');
                const verState = storeMod.getState().version;
                const versionText = verState
                    ? `App v${verState.app_version} · Model v${verState.model_version}`
                    : '未知版本';
                const body = `### 問題描述
<!-- 請描述異常現象、錯誤訊息或改進建議 -->

### 系統資訊
- **應用版本**: ${versionText}
- **瀏覽器**: ${navigator.userAgent}
- **回報時間**: ${new Date().toLocaleString()}`;
                window.open(`https://github.com/${repo}/issues/new?title=${title}&body=${encodeURIComponent(body)}`, '_blank');
            });
        }
    }).catch((err) => {
        console.error('[Sidebar] Failed to load modular components:', err);
    });
});
