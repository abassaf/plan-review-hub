# Theme tokens

Every visual property of the hub is driven by CSS custom properties defined in the theme file.
To re-skin the hub, copy `default.css`, change the values, and launch with:

```
python3 scripts/serve.py --theme path/to/my-theme.css
# or
node scripts/serve.mjs --theme path/to/my-theme.css
# or env var:
PLAN_HUB_THEME=path/to/my-theme.css python3 scripts/serve.py
```

## Token reference

| Token | Default | Purpose |
|-------|---------|---------|
| `--bg` | `#f5f6f8` | Page canvas background |
| `--surface` | `#ffffff` | Card / panel background |
| `--surface-warm` | `#fafaf9` | Slightly warm inset used for the headline block |
| `--line` | `#e4e7ec` | Default border colour |
| `--line-2` | `#d0d5dd` | Slightly stronger border for emphasis |
| `--ink-900` | `#111827` | Primary body text |
| `--ink-700` | `#374151` | Secondary / muted text |
| `--ink-500` | `#6b7280` | Placeholder / helper text |
| `--accent` | `#4f46e5` | Primary interactive colour (links, buttons, active chips) |
| `--accent-soft` | `#eef2ff` | Subtle accent tint for selected states |
| `--accent-dark` | `#3730a3` | Hover / active state for accent elements |
| `--green` | `#059669` | Success / done text |
| `--green-bg` | `#d1fae5` | Success chip background |
| `--yellow` | `#d97706` | Warning / in-progress text |
| `--yellow-bg` | `#fef3c7` | Warning chip background |
| `--red` | `#dc2626` | Danger / reject text |
| `--red-bg` | `#fee2e2` | Danger chip background |
| `--blue` | `#2563eb` | Info text |
| `--blue-bg` | `#dbeafe` | Info chip background |
| `--font-body` | system-ui stack | Body typeface |
| `--font-display` | same as body | Heading typeface — override with a web font |
| `--font-mono` | ui-monospace stack | Code / monospace typeface |
| `--radius-sm` | `8px` | Small element corner radius |
| `--radius` | `12px` | Default corner radius |
| `--radius-lg` | `16px` | Large card corner radius |
| `--radius-pill` | `999px` | Pill / badge corner radius |
| `--shadow-sm` | subtle | Card drop shadow |

## Example: swapping the accent to teal

```css
:root {
  --accent:      #0d9488;
  --accent-soft: #ccfbf1;
  --accent-dark: #0f766e;
}
```

Only the tokens that differ need to be set — the rest inherit from `default.css` (or from the
server's built-in fallback values).
