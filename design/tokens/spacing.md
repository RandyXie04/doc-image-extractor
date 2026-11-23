# Design Tokens: Spacing & Responsive Shell

Single source of truth for viewport breakpoints, container widths, and touch targets in `src/web/static/sidebar.css` and `src/web/static/js/viewport_manager.js`.

## Breakpoints & Container Widths

| Device Category | Viewport Width | `--container-max-w` | `--gutter-x` | Sidebar Behavior |
|---|---|---|---|---|
| Mobile | `< 640px` | `100%` | `0.75rem` | Off-canvas drawer (`280px`, `max-width: 85vw`), `inert` when collapsed |
| Tablet | `640px – 1023px` | `100%` | `1.25rem` | Off-canvas drawer (`280px`, `max-width: 85vw`), `inert` when collapsed |
| Desktop | `1024px – 1439px` | `1120px` | `clamp(1rem, 2.5vw, 2.5rem)` | Fixed `250px` left rail (`--sidebar-width`) |
| Wide Desktop | `1440px – 1919px` | `1360px` | `clamp(2rem, 3.5vw, 3.5rem)` | Fixed `250px` left rail |
| Ultrawide | `>= 1920px` | `1480px` | `3.5rem` | Fixed `250px` left rail |

## Radius & Elevation

- `--radius-sm`: `4px`
- `--radius-md`: `6px`
- `--radius-lg`: `8px`
- `--shadow-resting`, `--shadow-raised`, `--shadow-modal`: defined per theme in `src/web/static/sidebar.css`.

## Touch Targets

- On coarse pointers (`@media (pointer: coarse)`) and `< 1024px` viewports, interactive sidebar and modal controls enforce `min-height: 44px`.
