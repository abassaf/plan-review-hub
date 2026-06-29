# Dark mode — proposal

## Summary

Add a complete dark colour scheme that activates automatically via `prefers-color-scheme: dark`
and can be overridden manually via a sun/moon toggle in the navigation bar.

## Approach

1. **Token audit** — identify every hard-coded colour in the codebase; map each to a semantic
   design token (e.g. `--color-surface`, `--color-text-primary`).
2. **Token split** — define light-mode values in `:root` and dark-mode overrides in
   `@media (prefers-color-scheme: dark)` plus a `[data-theme="dark"]` attribute selector.
3. **Toggle UI** — add a theme toggle button to the top navigation; on click it:
   - Sets `data-theme` on `<html>`.
   - Writes `"dark"` or `"light"` to `localStorage['theme']`.
4. **FOUC prevention** — inject an inline script in `<head>` that reads `localStorage['theme']`
   before first paint and sets `data-theme` immediately.

## Colour palette (dark)

| Token | Light | Dark |
|-------|-------|------|
| `--color-bg` | `#f5f6f8` | `#0f1117` |
| `--color-surface` | `#ffffff` | `#1a1d27` |
| `--color-text-primary` | `#111827` | `#f0f2f5` |
| `--color-text-secondary` | `#374151` | `#9ca3af` |
| `--color-border` | `#e4e7ec` | `#2d3142` |
| `--color-accent` | `#4f46e5` | `#818cf8` |

## Accessibility

- All dark-mode colour pairs must pass WCAG AA (4.5:1 for normal text, 3:1 for large).
- Toggle button must have a visible focus ring.
