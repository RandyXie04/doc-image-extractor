// @ts-check
/**
 * Sidebar Theme Manager (`src/web/static/js/sidebar/theme_manager.js`)
 * =====================================================================
 * Resolves URL ?theme= & localStorage('app-theme'), syncs data-theme,
 * and keeps button accessible name compliant with WCAG 2.5.3 Label-in-Name.
 */

const THEME_STORAGE_KEY = 'app-theme';

/**
 * Resolve initial theme from URL query parameter or localStorage.
 * @returns {'light' | 'dark'}
 */
export function resolveInitialTheme() {
    const urlTheme = new URLSearchParams(window.location.search).get('theme');
    if (urlTheme === 'dark' || urlTheme === 'light') {
        localStorage.setItem(THEME_STORAGE_KEY, urlTheme);
        return urlTheme;
    }
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'dark' ? 'dark' : 'light';
}

/**
 * Update toggle button visuals and accessible attributes without overriding visible text.
 * @param {{
 *   btn: HTMLElement | null,
 *   iconEl: HTMLElement | null,
 *   labelEl: HTMLElement | null,
 *   badgeEl: HTMLElement | null
 * }} els
 * @param {'light' | 'dark'} theme
 * @param {(name: string, size?: number) => string} svgFn
 */
export function updateThemeToggleUI(els, theme, svgFn) {
    const { btn, iconEl, labelEl, badgeEl } = els;
    if (!btn) return;
    const isDark = theme === 'dark';
    if (iconEl) iconEl.innerHTML = svgFn(isDark ? 'sun' : 'moon', 15);
    if (labelEl) labelEl.textContent = isDark ? '外觀主題：深色模式' : '外觀主題：淺色模式';
    if (badgeEl) badgeEl.textContent = isDark ? 'Dark' : 'Light';
    btn.title = isDark ? '切換為淺色模式' : '切換為深色模式';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    btn.removeAttribute('aria-label');
}

/**
 * Initialize theme attribute and toggle button handler.
 * @param {{
 *   btn: HTMLElement | null,
 *   iconEl: HTMLElement | null,
 *   labelEl: HTMLElement | null,
 *   badgeEl: HTMLElement | null
 * }} els
 * @param {(name: string, size?: number) => string} svgFn
 * @returns {'light' | 'dark'}
 */
export function initThemeToggle(els, svgFn) {
    const initial = resolveInitialTheme();
    document.documentElement.setAttribute('data-theme', initial);
    updateThemeToggleUI(els, initial, svgFn);

    if (els.btn) {
        els.btn.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem(THEME_STORAGE_KEY, next);
            updateThemeToggleUI(els, next, svgFn);
        });
    }

    return initial;
}
