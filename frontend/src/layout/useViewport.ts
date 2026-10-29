/**
 * Viewport State Observer & Responsive Hook
 * ==========================================
 * Subscribes to window resize, device category transitions and orientation changes.
 */

import type { ViewportState, DeviceCategory, ScreenOrientation } from './viewportTypes';

/**
 * Calculates a synchronous viewport state snapshot.
 */
export function getInitialViewportState(): ViewportState {
  const width = typeof window !== 'undefined' ? window.innerWidth : 1200;
  const height = typeof window !== 'undefined' ? window.innerHeight : 800;
  const device: DeviceCategory =
    width < 640 ? 'mobile' : width < 1024 ? 'tablet' : width < 1440 ? 'desktop' : 'ultrawide';
  const orientation: ScreenOrientation = width >= height ? 'landscape' : 'portrait';
  const isTouch =
    typeof window !== 'undefined'
      ? 'ontouchstart' in window || (navigator && navigator.maxTouchPoints > 0)
      : false;

  return {
    width,
    height,
    device,
    orientation,
    isTouch,
    isSidebarOpen: false,
    isMobile: device === 'mobile',
    isTablet: device === 'tablet',
    isDesktop: device === 'desktop',
    isUltrawide: device === 'ultrawide',
  };
}

/**
 * Subscribes a listener callback to global viewport change events.
 * Returns an unsubscription cleanup function.
 */
export function subscribeViewport(callback: (state: ViewportState) => void): () => void {
  if (typeof window === 'undefined') return () => {};

  const handler = (event: Event) => {
    const custom = event as CustomEvent<ViewportState>;
    if (custom.detail) {
      callback(custom.detail);
    } else {
      callback(getInitialViewportState());
    }
  };

  window.addEventListener('viewportChange', handler);
  window.addEventListener('resize', handler, { passive: true });

  return () => {
    window.removeEventListener('viewportChange', handler);
    window.removeEventListener('resize', handler);
  };
}

