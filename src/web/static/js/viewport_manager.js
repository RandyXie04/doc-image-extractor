// @ts-check
/**
 * Viewport & Device Adaptation Module (src/web/static/js/viewport_manager.js)
 * =========================================================================
 * Provides dynamic screen size, breakpoint, orientation and device detection,
 * handles responsive side margins and sidebar drawer states across all devices.
 */

/**
 * @typedef {'mobile' | 'tablet' | 'desktop' | 'ultrawide'} DeviceType
 * @typedef {'portrait' | 'landscape'} OrientationType
 *
 * @typedef {Object} ViewportState
 * @property {number} width - Current viewport width in pixels
 * @property {number} height - Current viewport height in pixels
 * @property {DeviceType} device - Active breakpoint category
 * @property {OrientationType} orientation - Screen orientation
 * @property {boolean} isTouch - Whether coarse touch pointer is active
 * @property {boolean} isSidebarOpen - Whether sidebar drawer is open on mobile/tablet
 *
 * @typedef {Object} ViewportManagerAPI
 * @property {() => ViewportState} getState
 * @property {() => boolean} isMobile
 * @property {() => boolean} isTablet
 * @property {() => boolean} isDesktop
 * @property {() => boolean} isUltrawide
 * @property {() => boolean} isTouch
 * @property {(force?: boolean) => void} toggleSidebar
 * @property {() => void} closeSidebar
 * @property {() => void} openSidebar
 */

(function () {
    /** @type {DeviceType} */
    let currentDevice = 'desktop';
    /** @type {OrientationType} */
    let currentOrientation = 'landscape';
    let isTouchDevice = false;
    let sidebarOpen = false;

    /**
     * Determine device breakpoint based on viewport width.
     * @param {number} width
     * @returns {DeviceType}
     */
    function computeDevice(width) {
        if (width < 640) return 'mobile';
        if (width < 1024) return 'tablet';
        if (width < 1440) return 'desktop';
        return 'ultrawide';
    }

    /**
     * Compute current viewport orientation.
     * @param {number} width
     * @param {number} height
     * @returns {OrientationType}
     */
    function computeOrientation(width, height) {
        return width >= height ? 'landscape' : 'portrait';
    }

    /**
     * Detect touch capability safely.
     * @returns {boolean}
     */
    function checkTouch() {
        return (
            'ontouchstart' in window ||
            navigator.maxTouchPoints > 0 ||
            Boolean(window.matchMedia && window.matchMedia('(pointer: coarse)').matches)
        );
    }

    /**
     * Sync state to DOM data-* attributes on documentElement.
     */
    function syncDOMAttributes() {
        const root = document.documentElement;
        root.setAttribute('data-device', currentDevice);
        root.setAttribute('data-orientation', currentOrientation);
        root.setAttribute('data-touch', isTouchDevice ? 'true' : 'false');
        root.setAttribute('data-sidebar-state', sidebarOpen ? 'expanded' : 'collapsed');

        // Update aria-expanded on toggle button if present
        const toggleBtn = document.getElementById('sidebarToggleBtn');
        if (toggleBtn) {
            toggleBtn.setAttribute('aria-expanded', sidebarOpen ? 'true' : 'false');
        }
    }

    /**
     * Get current snapshot of viewport state.
     * @returns {ViewportState}
     */
    function getState() {
        const width = window.innerWidth || document.documentElement.clientWidth || 1024;
        const height = window.innerHeight || document.documentElement.clientHeight || 768;
        return {
            width,
            height,
            device: currentDevice,
            orientation: currentOrientation,
            isTouch: isTouchDevice,
            isSidebarOpen: sidebarOpen
        };
    }

    /**
     * Update viewport metrics and dispatch event if changed.
     * @param {boolean} [forceDispatch]
     */
    function updateMetrics(forceDispatch = false) {
        const width = window.innerWidth || document.documentElement.clientWidth || 1024;
        const height = window.innerHeight || document.documentElement.clientHeight || 768;
        const nextDevice = computeDevice(width);
        const nextOrientation = computeOrientation(width, height);
        const nextTouch = checkTouch();

        const deviceChanged = nextDevice !== currentDevice;
        const orientationChanged = nextOrientation !== currentOrientation;

        currentDevice = nextDevice;
        currentOrientation = nextOrientation;
        isTouchDevice = nextTouch;

        // Auto-close mobile drawer when scaling up to desktop
        if (currentDevice === 'desktop' || currentDevice === 'ultrawide') {
            if (sidebarOpen) {
                sidebarOpen = false;
            }
        }

        syncDOMAttributes();

        if (deviceChanged || orientationChanged || forceDispatch) {
            const detail = getState();
            window.dispatchEvent(new CustomEvent('viewportChange', { detail }));
        }
    }

    /**
     * Open the mobile sidebar drawer.
     */
    function openSidebar() {
        sidebarOpen = true;
        syncDOMAttributes();
        window.dispatchEvent(new CustomEvent('sidebarStateChange', { detail: { open: true } }));
    }

    /**
     * Close the mobile sidebar drawer.
     */
    function closeSidebar() {
        sidebarOpen = false;
        syncDOMAttributes();
        window.dispatchEvent(new CustomEvent('sidebarStateChange', { detail: { open: false } }));
    }

    /**
     * Toggle sidebar drawer state.
     * @param {boolean} [force]
     */
    function toggleSidebar(force) {
        if (typeof force === 'boolean') {
            sidebarOpen = force;
        } else {
            sidebarOpen = !sidebarOpen;
        }
        syncDOMAttributes();
        window.dispatchEvent(new CustomEvent('sidebarStateChange', { detail: { open: sidebarOpen } }));
    }

    // Debounced resize handler via requestAnimationFrame
    /** @type {number | null} */
    let rafId = null;
    function onWindowResize() {
        if (rafId !== null) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(() => {
            rafId = null;
            updateMetrics();
        });
    }

    // Initial setup
    updateMetrics(true);

    window.addEventListener('resize', onWindowResize, { passive: true });
    window.addEventListener('orientationchange', () => {
        setTimeout(updateMetrics, 100);
    });

    // Close on Escape if sidebar is open
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebarOpen) {
            closeSidebar();
        }
    });

    /** @type {ViewportManagerAPI} */
    const api = {
        getState,
        isMobile: () => currentDevice === 'mobile',
        isTablet: () => currentDevice === 'tablet',
        isDesktop: () => currentDevice === 'desktop',
        isUltrawide: () => currentDevice === 'ultrawide',
        isTouch: () => isTouchDevice,
        toggleSidebar,
        closeSidebar,
        openSidebar
    };

    const win = /** @type {Window & typeof globalThis & { viewportManager?: ViewportManagerAPI }} */ (window);
    win.viewportManager = api;

    // Attach to window.toolbox if available
    const tbWin = /** @type {Window & typeof globalThis & { toolbox?: { viewport?: ViewportManagerAPI } }} */ (window);
    if (tbWin.toolbox) {
        tbWin.toolbox.viewport = api;
    }
})();

