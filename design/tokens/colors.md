# Design Tokens: Colors

Single source of truth for light (Fluent 2) and dark (Dracula) color tokens defined in `src/web/static/sidebar.css`.

## Canonical Semantic Tokens

| Role | Token | Light Value | Dark Value (`[data-theme="dark"]`) | Usage & WCAG Notes |
|---|---|---|---|---|
| App Canvas | `--bg` | `#F5F7FA` | `#282a36` | Root page and `#main-content` background |
| Elevated Card | `--surface` | `#ffffff` | `#343746` | Cards, modals, primary containers |
| Nested Surface | `--surface-2` | `#F8FAFC` | `#44475a` | Nested panels, popovers, secondary controls |
| Sidebar Shell | `--sidebar-bg` | `#ffffff` | `#21222c` | `#sidebar` rail and system footer |
| Border | `--border` | `#D1D1D1` | `rgba(98, 114, 164, 0.45)` | Structural dividers and interactive boundaries |
| Primary Text | `--text` | `#242424` | `#f8f8f2` | Headings, body copy, button labels |
| Secondary Text | `--text-secondary` | `#616161` | `#a4b1cd` | Readable secondary text on `--bg` and `--surface` |
| Hint / Nested Muted Text | `--text-hint` | `#616161` | `#b8c0d9` | Required for readable text on `--surface-2` (>= 5.05:1 AA) and `--sidebar-bg` |
| Decorative Muted | `--text-muted` | `#616161` | `#6272a4` | **Non-text borders/icons only**; never apply as text `color` on dark surfaces |
| Primary Accent | `--accent` | `#0F6CBD` | `#bd93f9` | Reserved exclusively for active route highlight and primary focus/CTA |
| Warning / Dev Accent | `--warning-orange` | `#F7630C` | `#ffb86c` | Borders/indicators for developer debug mode (pair with `--text` for text) |
| Success | `--success` | `#107C10` | `#50fa7b` | Hardware acceleration dot, idle queue status |
| Danger | `--danger` | `#D13438` | `#ff5555` | Error alerts and destructive feedback |

## Governance Rules

1. New sidebar and component styles must consume canonical `--bg`, `--surface`, `--surface-2`, `--text`, `--text-hint`, and `--accent` tokens rather than duplicating `--f2-color-*` or legacy aliases.
2. Only active navigation links (`a.nav-link.active`, `.nav-sub-link.active`) may receive primary `--accent-soft` / `--accent-ring` fills inside the sidebar.
