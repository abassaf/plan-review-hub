# Dark mode — task breakdown

## Phase 1: token audit and CSS foundation

- [ ] Run `grep -rn '#[0-9a-fA-F]\{3,6\}' src/` to enumerate hard-coded colours
- [ ] Map each unique colour to a semantic token name
- [ ] Define all tokens in `src/styles/tokens.css` (`:root` block)
- [ ] Replace hard-coded colours in component CSS with token references
- [ ] Add `@media (prefers-color-scheme: dark)` block with dark overrides
- [ ] Add `[data-theme="dark"]` block (mirrors the media query; needed for the toggle)

## Phase 2: FOUC prevention script

- [ ] Write `src/scripts/theme-init.js` (tiny inline script, <200 bytes minified)
- [ ] Inject it as the **first** `<script>` tag in `<head>` (before any CSS paint)
- [ ] Add unit test: script sets `data-theme="dark"` when localStorage has `"dark"`
- [ ] Add unit test: script defaults to `"light"` when no preference stored

## Phase 3: toggle component

- [ ] Build `ThemeToggle` component (sun/moon SVG icons, accessible label)
- [ ] Integrate into `NavBar` component
- [ ] Component test: clicking toggle switches `data-theme` and writes localStorage
- [ ] Component test: toggle shows correct icon for current theme

## Phase 4: visual QA

- [ ] Review every page in dark mode at 1280px and 375px widths
- [ ] Verify all contrast ratios with a browser accessibility inspector
- [ ] Fix any components that look broken or fail contrast

## Phase 5: feature flag and ship

- [ ] Wrap toggle in `FEATURE_DARK_MODE` flag (default: `false` until QA complete)
- [ ] Once all pages pass QA, flip flag default to `true`
- [ ] Update CHANGELOG and design system docs
