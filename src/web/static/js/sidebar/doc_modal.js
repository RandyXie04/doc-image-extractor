// @ts-check
/**
 * Sidebar Doc Viewer & Accessible Modal Controller (`src/web/static/js/sidebar/doc_modal.js`)
 * ==========================================================================================
 * Manages documentation catalogue cache, modal open/close lifecycle, keyboard focus trap,
 * and focus restoration for sidebar modals.
 */

/**
 * @typedef {import('./system_store.js').DocItem} DocItem
 */

const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Bind accessible open/close, focus trapping, and focus restoration to a modal overlay.
 * @param {HTMLElement | null} modalEl
 * @param {HTMLElement | null} closeBtnEl
 * @param {() => boolean} [canClose]
 * @returns {{ open: (triggerEl?: HTMLElement | null) => void, close: () => void }}
 */
export function bindModalA11y(modalEl, closeBtnEl, canClose = () => true) {
    /** @type {HTMLElement | null} */
    let lastFocusedEl = null;

    function getFocusableElements() {
        if (!modalEl) return [];
        return /** @type {HTMLElement[]} */ (
            Array.from(modalEl.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
                (el) => el instanceof HTMLElement && el.offsetParent !== null
            )
        );
    }

    /** @param {HTMLElement | null} [triggerEl] */
    function open(triggerEl = null) {
        if (!modalEl) return;
        if (!modalEl.classList.contains('open')) {
            const active = document.activeElement;
            lastFocusedEl = triggerEl || (active instanceof HTMLElement ? active : null);
        }
        modalEl.classList.add('open');
        const focusTarget = closeBtnEl || getFocusableElements()[0];
        if (focusTarget) {
            requestAnimationFrame(() => focusTarget.focus());
        }
    }

    function close() {
        if (!modalEl || !modalEl.classList.contains('open')) return;
        if (!canClose()) return;
        modalEl.classList.remove('open');
        if (lastFocusedEl && typeof lastFocusedEl.focus === 'function') {
            lastFocusedEl.focus();
        }
        lastFocusedEl = null;
    }

    if (closeBtnEl) {
        closeBtnEl.addEventListener('click', close);
    }

    if (modalEl) {
        modalEl.addEventListener('click', (e) => {
            if (e.target === modalEl) close();
        });

        modalEl.addEventListener('keydown', (e) => {
            if (!modalEl.classList.contains('open')) return;
            if (e.key === 'Escape') {
                e.preventDefault();
                close();
                return;
            }
            if (e.key !== 'Tab') return;

            const focusables = getFocusableElements();
            if (focusables.length === 0) return;
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            if (!first || !last) return;

            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        });
    }

    return { open, close };
}

/**
 * Initialize the documentation viewer modal controller.
 * @param {{
 *   modalEl: HTMLElement | null,
 *   closeBtnEl: HTMLElement | null,
 *   titleEl: HTMLElement | null,
 *   subtitleEl: HTMLElement | null,
 *   sidebarEl: HTMLElement | null,
 *   articleEl: HTMLElement | null
 * }} els
 * @param {(name: string, size?: number) => string} svgFn
 * @param {(text: unknown) => string} escapeFn
 */
export function initDocModal(els, svgFn, escapeFn) {
    /** @type {Record<string, { title?: string, category?: string, description?: string, html?: string, markdown?: string }>} */
    const docCache = {};
    /** @type {DocItem[]} */
    let availableDocs = [];

    const controller = bindModalA11y(els.modalEl, els.closeBtnEl);

    /** @param {{ title?: string, category?: string, description?: string, html?: string, markdown?: string }} data */
    function renderDoc(data) {
        if (els.titleEl) els.titleEl.textContent = data.title || '技術與操作文件中心';
        if (els.subtitleEl) els.subtitleEl.textContent = data.category || '說明文件';
        if (!els.articleEl) return;
        const descBanner = data.description
            ? `<div class="doc-modal-desc-banner">${escapeFn(data.description)}</div>`
            : '';
        els.articleEl.innerHTML =
            descBanner + (data.html || `<pre style="white-space:pre-wrap;">${escapeFn(data.markdown || '')}</pre>`);
        els.articleEl.scrollTop = 0;
    }

    /**
     * Load and open a specific document inside the modal.
     * @param {string} docId
     * @param {HTMLElement | null} [triggerEl]
     */
    async function openDocViewer(docId, triggerEl = null) {
        const targetId = docId || (availableDocs[0] && availableDocs[0].id) || 'workflow';
        if (!targetId) return;

        if (els.sidebarEl) {
            els.sidebarEl.querySelectorAll('.doc-tab-btn').forEach((btn) => {
                if (btn instanceof HTMLElement) {
                    btn.classList.toggle('active', btn.dataset.docId === targetId);
                }
            });
        }

        if (els.articleEl) {
            els.articleEl.innerHTML = '<div class="doc-loading">正在載入文件內容...</div>';
        }
        controller.open(triggerEl);

        const cached = docCache[targetId];
        if (cached) {
            renderDoc(cached);
            return;
        }

        try {
            const res = await fetch(`/api/docs/${encodeURIComponent(targetId)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            docCache[targetId] = data;
            renderDoc(data);
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            if (els.articleEl) {
                els.articleEl.innerHTML = `
                    <div class="doc-error-box">
                        <p class="doc-error-title">文件載入失敗</p>
                        <p class="hint">${escapeFn(msg)}</p>
                    </div>`;
            }
        }
    }

    /** @param {DocItem[]} docs */
    function setDocs(docs) {
        availableDocs = Array.isArray(docs) ? docs : [];
        if (!els.sidebarEl) return;

        /** @type {Record<string, DocItem[]>} */
        const categories = {};
        availableDocs.forEach((doc) => {
            const cat = doc.category || '手冊與文件';
            if (!categories[cat]) categories[cat] = [];
            categories[cat].push(doc);
        });

        let modalNavHtml = '';
        for (const [catName, catDocs] of Object.entries(categories)) {
            modalNavHtml += `<div class="doc-nav-heading">${escapeFn(catName)}</div>`;
            catDocs.forEach((d) => {
                modalNavHtml += `
                    <button type="button" class="doc-tab-btn" data-doc-id="${escapeFn(d.id)}">
                        <span class="doc-tab-icon">${svgFn(d.icon || 'fileText', 14)}</span>
                        <span>${escapeFn(d.title)}</span>
                    </button>
                `;
            });
        }

        els.sidebarEl.innerHTML = modalNavHtml || '<div class="ia-loading-hint">無可用文件</div>';
        els.sidebarEl.querySelectorAll('.doc-tab-btn').forEach((btn) => {
            if (!(btn instanceof HTMLElement)) return;
            btn.addEventListener('click', () => {
                const docId = btn.dataset.docId;
                if (docId) void openDocViewer(docId, btn);
            });
        });
    }

    return {
        setDocs,
        openDocViewer,
        closeDocViewer: controller.close,
        getDefaultDocId: () => (availableDocs[0] && availableDocs[0].id) || 'workflow',
    };
}
