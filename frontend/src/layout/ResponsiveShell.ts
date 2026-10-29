/**
 * Responsive Shell & Gutter Spacing Token Calculator
 * ==================================================
 * Implements fluid container max-widths and side padding tokens across device form factors.
 */

import type { DeviceCategory, ResponsiveGutterTokens } from './viewportTypes';

/**
 * Returns dynamic gutter and container max-width tokens for the given device category.
 */
export function getResponsiveGutterTokens(device: DeviceCategory): ResponsiveGutterTokens {
  switch (device) {
    case 'mobile':
      return {
        gutterX: '0.75rem',
        gutterY: '0.75rem',
        containerMaxWidth: '100%',
      };
    case 'tablet':
      return {
        gutterX: '1.25rem',
        gutterY: '1.25rem',
        containerMaxWidth: '100%',
      };
    case 'ultrawide':
      return {
        gutterX: '3.5rem',
        gutterY: '2.5rem',
        containerMaxWidth: '1480px',
      };
    case 'desktop':
    default:
      return {
        gutterX: '2.5rem',
        gutterY: '2rem',
        containerMaxWidth: '1200px',
      };
  }
}

