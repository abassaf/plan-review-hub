# Plan format reference

This document defines the schemas for all JSON files read and written by plan-review-hub.

---

## plan.json (input — one per plan)

Location: `<plansDir>/<id>/plan.json`

```jsonc
{
  // Required
  "id":      "api-versioning",         // unique slug; used in URLs and filenames
  "num":     "01",                     // display number (string; "01", "02", …)
  "title":   "API versioning strategy",
  "tagline": "One-line summary shown on the hub index.",

  // Optional metadata
  "branch":  "feat/api-versioning",    // git branch this plan will be built on
  "effort":  "M — 3 files, ~200 LOC", // free-form effort estimate
  "risk":    "Low (additive only)",    // free-form risk level
  "headline": "HTML string shown in the 'What the investigation found' box on the plan page.",

  // Markdown files to render (relative paths inside the plan folder)
  // Rendered in order; each appears in a named collapsible section.
  "docs": ["proposal.md", "tasks.md"],

  // Structured decision questions shown in the feedback form
  "decisions": [
    {
      "id":      "compat_strategy",          // unique within this plan
      "q":       "Backward-compatibility approach",
      "help":    "Hint text shown under the question.",
      "options": [
        {
          "v":           "redirect",          // the value stored in feedback JSON
          "label":       "301-redirect for 6 months, then drop",
          "recommended": true                 // optional: shows a "recommended" hint
        },
        { "v": "parallel", "label": "Keep both routes indefinitely" },
        { "v": "gone",     "label": "Return 410 immediately (breaking)" }
      ],
      "default": "redirect"                  // pre-selected value on first load
    }
  ]
}
```

**Minimal plan.json** (only `id`, `title`, and one markdown file required):

```jsonc
{
  "id":    "quick-fix",
  "title": "Quick fix",
  "docs":  ["proposal.md"]
}
```

---

## feedback/<id>.json (output — written by POST /submit)

Location: `<stateDir>/feedback/<id>.json`

```jsonc
{
  "planId":      "api-versioning",
  "title":       "API versioning strategy",

  // Verdict — one of:
  //   "approve" | "approve_with_changes" | "hold" | "reject"
  "verdict":     "approve_with_changes",

  // Decision answers — keys are decision IDs from plan.json
  "decisions": {
    "compat_strategy": "redirect",
    "version_header":  "header"
  },

  "notes":       "Proceed with redirect; set Sunset to 2026-12-31.",
  "priority":    "high",       // free text or a number; whatever the reviewer enters
  "assignee":    "alice",      // free text

  "submittedAt": "2026-06-06T10:30:00.000Z",
  "ua":          "Mozilla/5.0 …"   // user-agent string (diagnostic only)
}
```

---

## progress.json (input — updated by Claude as subagents land)

Location: `<stateDir>/progress.json`

```jsonc
{
  "api-versioning": {
    // State — one of: "not_started" | "in_progress" | "done"
    "state":  "in_progress",
    "label":  "In progress",            // display label shown on the hub
    "branch": "feat/api-versioning",    // the worktree branch

    // Completed items (rendered as ☑ in the progress card)
    "done": [
      "Version middleware wired up and unit-tested",
      "301 redirect handler added"
    ],

    // Remaining items (rendered as ☐ in the progress card)
    "remaining": [
      "OpenAPI spec update",
      "Integration tests",
      "Review and merge"
    ]
  },

  "dark-mode": {
    "state":     "not_started",
    "label":     "Not started",
    "branch":    "feat/dark-mode",
    "done":      [],
    "remaining": []
  }
}
```

If `progress.json` does not exist, every plan is treated as "not started".

---

## Directory layout summary

```
<workdir>/
├── plans/                          # or custom --plans path
│   ├── api-versioning/
│   │   ├── plan.json
│   │   ├── proposal.md
│   │   └── tasks.md
│   └── dark-mode/
│       ├── plan.json
│       ├── proposal.md
│       └── tasks.md
│
├── .planning-hub/                  # gitignored state dir (--state)
│   ├── feedback/
│   │   ├── api-versioning.json
│   │   └── dark-mode.json
│   └── progress.json
│
└── assets/themes/
    └── default.css
```
