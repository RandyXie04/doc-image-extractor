// @ts-check
/**
 * Sidebar System Store (`src/web/static/js/sidebar/system_store.js`)
 * ==================================================================
 * Single bootstrap seam for system config, hardware summary, app mode,
 * dynamic plugins, and audience-filtered documentation catalogue.
 */

/**
 * @typedef {'editor' | 'dev'} AppMode
 *
 * @typedef {Object} PluginSpec
 * @property {string} id
 * @property {string} name
 * @property {string} category
 * @property {string} description
 * @property {string} icon
 * @property {string} entry_url
 * @property {boolean} is_enabled
 * @property {number} [order]
 *
 * @typedef {Object} DocItem
 * @property {string} id
 * @property {string} title
 * @property {string} category
 * @property {string} audience
 * @property {string} icon
 * @property {string} description
 *
 * @typedef {Object} SystemState
 * @property {boolean} loaded
 * @property {AppMode} mode
 * @property {boolean} isLocalDev
 * @property {{ app_version: string, model_version: string } | null} version
 * @property {{
 *   max_upload_size_mb: number,
 *   max_template_size_mb: number,
 *   file_retention_hours: number,
 *   default_ai_model?: string,
 *   ollama_model?: string,
 *   ollama_available?: boolean
 * }} config
 * @property {{ gpu_name: string, is_accelerated: boolean, target_accelerator?: string } | null} hardware
 * @property {PluginSpec[]} plugins
 * @property {DocItem[]} docs
 */

const DEV_MODE_STORAGE_KEY = 'developer_engineer_mode';

/** @type {DocItem[]} */
const FALLBACK_DOCS = [
    { id: 'workflow', title: '全流程操作指南', category: '操作手冊', audience: 'all', icon: 'book', description: '全自動整稿 & POD' },
    { id: 'about', title: '系統授權與內網部署', category: '操作手冊', audience: 'all', icon: 'shield', description: '開源授權與私有化規範' },
];

/** @type {PluginSpec[]} */
const FALLBACK_PLUGINS = [
    { id: 'ocr_pipeline', name: '全自動整稿', category: 'core_typesetting', description: '', icon: 'doc', entry_url: '/static/ocr_pipeline.html', is_enabled: true, order: 10 },
    { id: 'pod_studio', name: 'POD 整稿', category: 'core_typesetting', description: '', icon: 'pod', entry_url: '/static/pod_studio.html', is_enabled: true, order: 20 },
    { id: 'founder_repair', name: '方正修復', category: 'auxiliary_task', description: '', icon: 'wrench', entry_url: '/static/founder_repair.html', is_enabled: true, order: 10 },
    { id: 'extract_images', name: '圖片提取', category: 'auxiliary_task', description: '', icon: 'image', entry_url: '/static/extract_images.html', is_enabled: true, order: 20 },
    { id: 'formula_extraction', name: '公式提取', category: 'auxiliary_task', description: '', icon: 'formula', entry_url: '/static/formula.html', is_enabled: true, order: 30 },
];

/** @type {SystemState} */
let state = {
    loaded: false,
    mode: 'editor',
    isLocalDev: true,
    version: null,
    config: {
        max_upload_size_mb: 200,
        max_template_size_mb: 20,
        file_retention_hours: 24,
    },
    hardware: null,
    plugins: [...FALLBACK_PLUGINS],
    docs: [...FALLBACK_DOCS],
};

/** @type {Set<(nextState: SystemState) => void>} */
const listeners = new Set();

function notifyListeners() {
    const snapshot = getState();
    listeners.forEach((fn) => {
        try {
            fn(snapshot);
        } catch (err) {
            console.error('[SystemStore] Listener error:', err);
        }
    });
}

/**
 * Sync quota values onto global window.APP_CONFIG for upload validators.
 * @param {SystemState['config']} cfg
 */
function syncGlobalAppConfig(cfg) {
    const win = /** @type {any} */ (window);
    win.APP_CONFIG = win.APP_CONFIG || {
        maxUploadSizeMB: 200,
        maxTemplateSizeMB: 20,
        fileRetentionHours: 24,
    };
    if (cfg && cfg.max_upload_size_mb) {
        win.APP_CONFIG.maxUploadSizeMB = cfg.max_upload_size_mb;
        win.APP_CONFIG.maxTemplateSizeMB = cfg.max_template_size_mb;
        win.APP_CONFIG.fileRetentionHours = cfg.file_retention_hours;
    }
}

/**
 * Dispatch a single canonical appModeChanged event on window.
 * @param {AppMode} mode
 */
function emitAppModeChanged(mode) {
    window.dispatchEvent(new CustomEvent('appModeChanged', { detail: { mode } }));
}

/**
 * Fetch audience-filtered docs when mode switches after initial bootstrap.
 * @param {AppMode} mode
 * @returns {Promise<DocItem[]>}
 */
async function fetchDocsForMode(mode) {
    try {
        const res = await fetch(`/api/docs?mode=${encodeURIComponent(mode)}`);
        if (res.ok) {
            const items = await res.json();
            if (Array.isArray(items)) return items;
        }
    } catch (err) {
        console.debug('[SystemStore] Docs refresh fallback:', err);
    }
    const docs = [...FALLBACK_DOCS];
    if (mode === 'dev') {
        docs.push({ id: 'modules', title: '核心模組技術說明', category: '技術規格', audience: 'dev', icon: 'cpu', description: '雙引擎、YOLOv8、方正' });
    }
    return docs;
}

/**
 * Return shallow copy of current system state.
 * @returns {SystemState}
 */
export function getState() {
    return {
        ...state,
        config: { ...state.config },
        plugins: [...state.plugins],
        docs: [...state.docs],
    };
}

/**
 * Subscribe to store state updates.
 * @param {(nextState: SystemState) => void} listener
 * @returns {() => void}
 */
export function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

/**
 * Load unified bootstrap payload from GET /api/system/bootstrap.
 * @returns {Promise<SystemState>}
 */
export async function loadBootstrap() {
    const isDevPreset = localStorage.getItem(DEV_MODE_STORAGE_KEY) === 'true';

    try {
        const res = await fetch('/api/system/bootstrap');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const isLocalDev = Boolean(data.app_mode && data.app_mode.is_local_dev !== false);
        /** @type {AppMode} */
        let activeMode = data.app_mode && data.app_mode.mode === 'dev' ? 'dev' : 'editor';
        let docs = Array.isArray(data.docs) && data.docs.length > 0 ? data.docs : [...FALLBACK_DOCS];

        if (!isLocalDev) {
            localStorage.setItem(DEV_MODE_STORAGE_KEY, 'false');
            activeMode = 'editor';
        } else if (isDevPreset && activeMode !== 'dev') {
            try {
                const modeRes = await fetch('/api/set_app_mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: 'dev' }),
                });
                if (modeRes.ok) {
                    const modeData = await modeRes.json();
                    activeMode = modeData.mode === 'dev' ? 'dev' : 'editor';
                    docs = await fetchDocsForMode(activeMode);
                } else {
                    localStorage.setItem(DEV_MODE_STORAGE_KEY, 'false');
                    activeMode = 'editor';
                }
            } catch {
                localStorage.setItem(DEV_MODE_STORAGE_KEY, 'false');
                activeMode = 'editor';
            }
        }

        state = {
            loaded: true,
            mode: activeMode,
            isLocalDev,
            version: data.version || null,
            config: data.config || state.config,
            hardware: data.hardware || null,
            plugins: Array.isArray(data.plugins) && data.plugins.length > 0 ? data.plugins : [...FALLBACK_PLUGINS],
            docs,
        };

        syncGlobalAppConfig(state.config);
        notifyListeners();
        emitAppModeChanged(state.mode);
        return getState();
    } catch (err) {
        console.debug('[SystemStore] Bootstrap failed, using fallback:', err);
        const fallbackMode = isDevPreset ? 'dev' : 'editor';
        state = {
            ...state,
            loaded: true,
            mode: fallbackMode,
            docs: await fetchDocsForMode(fallbackMode),
        };
        syncGlobalAppConfig(state.config);
        notifyListeners();
        emitAppModeChanged(state.mode);
        return getState();
    }
}

/**
 * Switch operational mode ('editor' | 'dev') and persist preference.
 * @param {AppMode} targetMode
 * @returns {Promise<{ ok: boolean, mode: AppMode, message: string, kind: 'success' | 'warning' | 'error' }>}
 */
export async function setMode(targetMode) {
    try {
        const res = await fetch('/api/set_app_mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: targetMode }),
        });
        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
            localStorage.setItem(DEV_MODE_STORAGE_KEY, 'false');
            const docs = await fetchDocsForMode('editor');
            state = { ...state, mode: 'editor', docs };
            notifyListeners();
            emitAppModeChanged('editor');
            return {
                ok: false,
                mode: 'editor',
                message: data.detail || data.msg || '工程師除錯模式僅允許於開發本機 IP 位址啟動。',
                kind: 'warning',
            };
        }

        /** @type {AppMode} */
        const nextMode = data.mode === 'dev' ? 'dev' : 'editor';
        localStorage.setItem(DEV_MODE_STORAGE_KEY, nextMode === 'dev' ? 'true' : 'false');
        const docs = await fetchDocsForMode(nextMode);
        state = { ...state, mode: nextMode, docs };
        notifyListeners();
        emitAppModeChanged(nextMode);

        const message = nextMode === 'dev'
            ? `已偵測為開發本機 IP (${data.client_ip || '127.0.0.1'})，啟動工程師除錯模式。`
            : '已切換為出版社編輯模式：隱藏處理日誌與內部目錄。';
        return { ok: true, mode: nextMode, message, kind: 'success' };
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
            ok: false,
            mode: state.mode,
            message: '模式切換失敗：' + msg,
            kind: 'error',
        };
    }
}
