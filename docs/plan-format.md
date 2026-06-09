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

## progress.json (input — updated as implementation agents land changes)

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

## audit/<id>.json (input — one per findings audit)

Location: `<auditsDir>/<id>.json` (default `<stateDir>/audits/<id>.json`)

A **findings audit** is a sibling artifact to a plan. Where a plan answers "what should
we build?", an audit answers "where does this problem already exist, what does the fix look
like, and which instances are done?". The hub renders it at `/audit/<id>` as a before/after
report with a status badge per finding and headline counts.

```jsonc
{
  // Required
  "id":    "operator-precedence-sweep",   // url-safe slug; used in the /audit/<id> URL
  "title": "Operator-precedence guard sweep",

  // Optional — link this audit to a plan (shown on that plan's page, and vice versa)
  "planId": "some-plan",                  // or null / omitted for a standalone audit

  // Optional — the pattern, shown as inline code in the header
  "pattern": {
    "buggy":   "loading || (ready && view())",
    "correct": "(loading || ready) && view()"
  },

  // Optional — the "why this is a bug" info box. May contain inline HTML (e.g. <code>).
  "why": "When loading is truthy, || short-circuits and the guarded block never renders…",

  // Optional — footer summary line (falls back to derived counts)
  "summary": "4 instances: 2 fixed, 1 open, 1 confirmed fine.",

  // The findings themselves
  "findings": [
    {
      "file":   "path/to/file",           // repo-relative path (shown in monospace)
      "line":   84,                        // optional line reference

      // Status drives the badge, the section it lands in, and the verdict pill:
      //   "bug"   → ⚠️ Needs fixing
      //   "fixed" → ✅ Fixed
      //   "fine"  → 👀 Reviewed — confirmed fine (false positive)
      "status": "fixed",

      // Code for the two diff panes. Each entry is either a plain string or an object
      // {"text": "...", "kind": "removed"|"added"|"neutral"}. Plain strings default to
      // "removed" in the Before pane and "added" in the After pane.
      "before": ["loading || (ready && (", "  panel(items)", "))"],
      "after":  ["(loading || ready) && (", "  panel(items)", ")"],

      "explanation": "Plain-English reason THIS instance is wrong, in its own terms.",

      // Optional. For fixed findings, commit fills the verdict pill ("Fixed in <sha>").
      // An explicit verdict string overrides the derived text.
      "commit":  "a1b2c3d",
      "verdict": null,
      "ref":     "https://…"               // optional link rendered in the card header
    }
  ]
}
```

The three stat cards (Fixed / Needs fixing / Total scanned) are **derived** from the
`findings` array on every request — they are never stored, so they cannot drift. To update
an audit as fixes land, edit the relevant finding's `status` (`bug` → `fixed`) and add its
`commit`; the card moves sections and the counts recompute automatically.

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
│   ├── audits/                     # findings audits (--audits); default <state>/audits
│   │   └── operator-precedence-sweep.json
│   └── progress.json
│
└── assets/themes/
    └── default.css
```
