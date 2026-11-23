// @ts-check
/**
 * Sidebar Developer Telemetry Module (`src/web/static/js/sidebar/dev_telemetry.js`)
 * =================================================================================
 * Owns 4-second polling of /api/dev/telemetry and renders a single-column 2-row
 * GPU/VRAM HUD inside the sidebar system footer without wrapping GPU names.
 */

/**
 * @typedef {Object} TelemetryPayload
 * @property {string} gpu_name
 * @property {string} target_accelerator
 * @property {number} total_vram_gb
 * @property {number} reserved_vram_mb
 * @property {number} vram_usage_percent
 * @property {boolean} gpu_locked
 */

/**
 * Initialize developer hardware telemetry polling and HUD rendering.
 * @param {HTMLElement | null} slotEl
 * @param {(text: unknown) => string} escapeFn
 */
export function initDevTelemetry(slotEl, escapeFn) {
    /** @type {ReturnType<typeof setInterval> | null} */
    let timer = null;

    /** @param {TelemetryPayload} data */
    function render(data) {
        if (!slotEl) return;
        let hud = document.getElementById('devTelemetryHUD');
        if (!hud) {
            hud = document.createElement('div');
            hud.id = 'devTelemetryHUD';
            hud.className = 'sidebar-telemetry-hud';
            slotEl.appendChild(hud);
        }

        const vramText = data.total_vram_gb > 0
            ? `${data.reserved_vram_mb} / ${(data.total_vram_gb * 1024).toFixed(0)} MB (${data.vram_usage_percent}%)`
            : 'CPU 模式';
        const lockBadge = data.gpu_locked
            ? '<span class="telemetry-status-busy">運算中</span>'
            : '<span class="telemetry-status-idle">閒置</span>';

        hud.innerHTML = `
            <div class="telemetry-hud-row-gpu" title="${escapeFn(data.gpu_name)}">
                <span class="telemetry-gpu-name">${escapeFn(data.gpu_name)}</span>
                <span class="telemetry-accel-pill">${escapeFn(data.target_accelerator)}</span>
            </div>
            <div class="telemetry-hud-row-meta">
                <span>VRAM ${escapeFn(vramText)}</span>
                <span>${lockBadge}</span>
            </div>
        `;
    }

    async function poll() {
        try {
            const res = await fetch('/api/dev/telemetry');
            if (res.ok) {
                const data = await res.json();
                render(data);
            }
        } catch (err) {
            console.debug('[DevTelemetry] Poll skipped:', err);
        }
    }

    function stop() {
        if (timer !== null) {
            clearInterval(timer);
            timer = null;
        }
        const hud = document.getElementById('devTelemetryHUD');
        if (hud) hud.remove();
    }

    function start() {
        void poll();
        if (timer === null) {
            timer = setInterval(() => void poll(), 4000);
        }
    }

    /** @param {'editor' | 'dev'} mode */
    function syncMode(mode) {
        if (mode === 'dev') {
            start();
        } else {
            stop();
        }
    }

    window.addEventListener('pagehide', stop);

    return {
        syncMode,
        stop,
    };
}
