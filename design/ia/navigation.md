# Information Architecture: 3-Zone Sidebar Navigation

Canonical navigation structure implemented by `src/web/static/sidebar.js` and hydrated from `GET /api/system/bootstrap`.

## Zone Hierarchy

1. **Brand Header** (`#sidebar > a.brand`): Links to `/` (`轉檔工具箱`).
2. **Zone 1 — Primary Navigation** (`<nav id="sidebarPrimaryNav" aria-label="主導覽">`):
   - **核心工作流程** (`#mainNavList`): Renders enabled `core_typesetting` plugins (`全自動整稿`, `POD 整稿`) at top level with zero accordion gating.
   - **專項輔助工具** (`#auxNavGroup`): Collapsible navigation group rendering enabled `auxiliary_task` plugins (`方正修復`, `圖片提取`, `公式提取`).
3. **Zone 2 — Workspace Tools & Documentation** (`<div id="sidebarWorkspaceTools" role="region" aria-label="工作區工具與文件">`):
   - `外觀主題` toggle (`#themeToggleBtn`) synced via `src/web/static/js/sidebar/theme_manager.js`.
   - `操作指南與文件` trigger (`#openDocCenterBtn`) opening `#docViewerModal`.
4. **Zone 3 — System Status Footer & Maintenance Popover** (`<footer id="sidebarSystemFooter" aria-label="系統狀態與維護">`):
   - Developer-only `#devTelemetryHUD` slot (rendered only in `dev` mode via `src/web/static/js/sidebar/dev_telemetry.js`).
   - Compact status capsule button (`#systemStatusToggle`) summarizing accelerator status, app version, and current mode pill (`編輯` / `除錯`).
   - On-demand `#systemStatusPopover` (`[hidden]` by default) housing hardware/AI details, read-only quota summary, `#modeToggleBtn`, `#checkUpdateBtn`, and dev-only `#globalReportBtn`.

## Landmarks & Visibility Rules

- Every page wraps primary content in a single `<main id="main-content">` landmark.
- Non-navigation tools and system controls remain outside `<nav>`.
- Panel visibility uses the native `[hidden]` attribute exclusively (no `style.display` toggling).
- Collapsed drawers (`< 1024px`) set `sidebar.inert = true` via `src/web/static/js/viewport_manager.js`.
