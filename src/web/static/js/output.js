// @ts-check
// Output helpers shared by every tool: native "save as" flow, folder reveal and error panels.

/**
 * @typedef {Object} NativeSaveOptions
 * @property {string} sourcePath
 * @property {string} filename
 * @property {HTMLButtonElement | null} [button]
 * @property {string | null} [fallbackUrl]
 * @property {HTMLElement | null} [mountEl]
 * @property {string} [label]
 */

/**
 * @typedef {Object} ToolboxGlobal
 * @property {(message: string, kind?: string, ms?: number) => void} notify
 * @property {(text: unknown) => string} escape
 * @property {(title: string, message: string, retryHandler?: string) => string} [errorPanel]
 * @property {(filePath: string) => Promise<void>} [openFolder]
 * @property {(options: NativeSaveOptions) => Promise<void>} [nativeSave]
 * @property {string} [DOWNLOAD_ICON]
 */

(function () {
    const win = /** @type {Window & typeof globalThis & { toolbox?: ToolboxGlobal }} */ (window);
    const tb = win.toolbox || (win.toolbox = {
        notify() {},
        escape(text) {
            return String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }
    });

    /**
     * @param {string} title
     * @param {string} message
     * @param {string} [retryHandler]
     * @returns {string}
     */
    function errorPanel(title, message, retryHandler) {
        const retry = retryHandler ? `<button type="button" class="btn btn-secondary btn-sm" onclick="${tb.escape(retryHandler)}">重新嘗試</button>` : '';
        return `<div class="alert alert-danger" role="alert"><div class="alert-title">${tb.escape(title)}</div>${tb.escape(message)}${retry ? '<br>' + retry : ''}</div>`;
    }

    /**
     * @param {string} filePath
     * @returns {Promise<void>}
     */
    async function openFolder(filePath) {
        try {
            const res = await fetch('/api/open_file_folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: filePath })
            });
            const data = await res.json().catch(() => ({}));
            if (data.status === 'fallback') tb.notify(data.message || '遠端連線無法開啟伺服器資料夾，請改用瀏覽器下載。', 'warning');
            else if (!res.ok || data.status === 'error') tb.notify(data.detail || data.message || '無法開啟檔案總管。', 'error');
        } catch (err) {
            const errMsg = err instanceof Error ? err.message : String(err);
            tb.notify('無法開啟檔案總管：' + errMsg, 'error');
        }
    }

    // Saves a server-side file through the native dialog; falls back to a browser download.
    // mountEl receives the "saved to" confirmation so it stays inside the result card.
    /**
     * @param {NativeSaveOptions} options
     * @returns {Promise<void>}
     */
    async function nativeSave({ sourcePath, filename, button, fallbackUrl, mountEl, label }) {
        const original = button ? button.innerHTML : '';
        if (button) {
            button.disabled = true;
            button.textContent = '請在開啟的視窗中選擇儲存位置…';
        }
        const restore = () => {
            if (button) {
                button.innerHTML = original;
                button.disabled = false;
            }
        };
        try {
            const res = await fetch('/api/native_save_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source_path: sourcePath, suggested_filename: filename })
            });
            if (res.status === 404) {
                tb.notify('另存失敗：輸出檔案尚未生成，或已超過保存期限被清除。', 'error');
                restore();
                return;
            }
            if (!res.ok) throw new Error(`伺服器回應異常 (${res.status})`);
            const result = await res.json();

            if (result.status === 'success') {
                restore();
                if (mountEl) {
                    const id = 'saved-' + String(filename || 'file').replace(/[^\w.-]/g, '_');
                    let info = document.getElementById(id);
                    if (!info) {
                        info = document.createElement('div');
                        info.id = id;
                        info.className = 'saved-info';
                        mountEl.appendChild(info);
                    }
                    info.innerHTML = `<strong>${tb.escape(label || filename)} 已儲存到</strong><div class="path-box">${tb.escape(result.saved_path)}</div>`;
                    const open = document.createElement('button');
                    open.type = 'button';
                    open.className = 'btn btn-secondary btn-sm';
                    open.style.marginTop = '8px';
                    open.textContent = '在檔案總管中顯示';
                    open.onclick = () => openFolder(result.saved_path);
                    info.appendChild(open);
                } else {
                    tb.notify('已儲存：' + result.saved_path, 'success');
                }
            } else if (result.status === 'cancelled') {
                restore();
            } else {
                if (fallbackUrl) window.location.href = fallbackUrl;
                else tb.notify(result.message || result.detail || '另存失敗', result.status === 'fallback' ? 'warning' : 'error');
                restore();
            }
        } catch (e) {
            const errMsg = e instanceof Error ? e.message : String(e);
            if (fallbackUrl) window.location.href = fallbackUrl;
            else tb.notify('另存失敗：' + errMsg, 'error');
            restore();
        }
    }

    const DOWNLOAD_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

    Object.assign(tb, { errorPanel, openFolder, nativeSave, DOWNLOAD_ICON });
})();


