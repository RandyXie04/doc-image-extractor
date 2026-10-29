/**
 * Viewport & Responsive Layout Types
 * ==================================
 * Strongly typed viewport specifications following modern component scaffolding.
 */

export type DeviceCategory = 'mobile' | 'tablet' | 'desktop' | 'ultrawide';
export type ScreenOrientation = 'portrait' | 'landscape';

export interface ViewportDimensions {
  width: number;
  height: number;
}

export interface ViewportState extends ViewportDimensions {
  device: DeviceCategory;
  orientation: ScreenOrientation;
  isTouch: boolean;
  isSidebarOpen: boolean;
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  isUltrawide: boolean;
}

export interface ResponsiveGutterTokens {
  gutterX: string;
  gutterY: string;
  containerMaxWidth: string;
}

export interface ViewportManagerContract {
  getState(): ViewportState;
  isMobile(): boolean;
  isTablet(): boolean;
  isDesktop(): boolean;
  isUltrawide(): boolean;
  isTouch(): boolean;
  toggleSidebar(force?: boolean): void;
  openSidebar(): void;
  closeSidebar(): void;
}

