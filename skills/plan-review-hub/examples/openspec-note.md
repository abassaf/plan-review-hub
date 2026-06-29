# OpenSpec adapter — auto-detection note

When `source` is set to `openspec` (or `auto` and no `plans/` directory exists), the hub
looks for an `openspec/changes/` directory in the working directory and builds plans from it.

## Expected structure

```
openspec/
└── changes/
    └── <change-id>/
        ├── proposal.md      # rendered in the "Proposal" section
        ├── design.md        # rendered in the "Design & decisions" collapsible
        ├── tasks.md         # rendered in the "Task breakdown" collapsible
        └── plan.json        # optional — adds decisions/metadata (same schema as generic plan.json)
```

If `plan.json` is absent, the hub infers:
- `id` from the directory name
- `title` from the first `# Heading` in `proposal.md`
- `tagline` from the first paragraph after the heading
- No decisions (feedback form shows only verdict, notes, priority, assignee)

## How the auto-detect priority works

| Condition | Source used |
|-----------|-------------|
| `source: generic` | Always reads `plansDir` |
| `source: openspec` | Always reads `openspec/changes/` |
| `source: auto` (default) | `plansDir` present and non-empty → generic; else `openspec/changes/` present → openspec; else empty state |

## Tip

You can mix both: put a `plan.json` alongside OpenSpec markdown files to add structured
decision questions to a change that was authored with `ospx propose`.
