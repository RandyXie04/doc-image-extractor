# Design Tokens: Typography

Single source of truth for font families and sidebar/workbench type hierarchy in `src/web/static/sidebar.css`.

## Font Families

- Sans (`--font-sans`): `-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif`
- Monospace (`--font-mono`): `"Segoe UI Mono", "Cascadia Mono", Consolas, "Noto Sans TC", monospace`

## Sidebar Hierarchy Scale

| Level | Selector | Size | Weight | Purpose |
|---|---|---|---|---|
| Brand Header | `#sidebar .brand` | `1.05rem` (16.8px) | `600` | Application title link (`轉檔工具箱`) |
| Primary Route | `#sidebar a.nav-link`, `.nav-group-header` | `0.875rem` (14px) | `500` / `600` | Core workflow routes and collapsible tool header |
| Tool / Action Row | `.sidebar-tool-btn`, `.sidebar-btn` | `0.84rem` (13.44px) | `500` | Workspace theme toggle, documentation entry, popover actions |
| Sub-Navigation | `.nav-sub-link` | `0.8125rem` (13px) | `500` / `600` | Auxiliary tool routes inside `專項輔助工具` |
| Section Label | `.sidebar-section-label` | `0.75rem` (12px) | `700` | Uppercase/tracked zone labels (`核心工作流程`, `工作區與文件`) |
| Telemetry & Meta | `.sidebar-telemetry-hud`, `.system-status-version`, `.sidebar-quota-summary` | `0.72rem–0.75rem` (11.5–12px) | `400` / `600` | Monospace hardware stats, version badge, quota summary |
