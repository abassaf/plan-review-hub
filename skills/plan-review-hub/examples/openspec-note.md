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

## Tip — enriching with `plan.json`

You can mix both: put a `plan.json` alongside OpenSpec markdown files to add structured
decision questions to a change that was authored with `ospx propose`.

**Must list `docs` when generic mode can win.** The openspec loader auto-fills `docs` from
`proposal.md` / `design.md` / `tasks.md`. The generic loader only renders files listed in
`plan.json`'s `docs` array — missing `docs` → progress + form, **zero documents**, no error.
That hits if you pass `--plans …/openspec/changes` (forces generic) or if `auto` already
found generic plans. Always include `docs` when adding `plan.json`:

```json
{
  "id": "my-change",
  "title": "My change",
  "docs": ["proposal.md", "design.md", "tasks.md", "specs/foo/spec.md"],
  "decisions": []
}
```

Paths are relative to the change directory; subdirectories are allowed. Prefer default
`--plans` + `auto`/`openspec` rather than pointing `--plans` at `openspec/changes`.
