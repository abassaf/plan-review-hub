# plan-review-hub

A provider-agnostic coding-agent skill that turns multi-step work plans into a served
LAN hub for review, approval, feedback collection, and isolated worktree dispatch.

## What it is

You describe work to a coding agent. The agent breaks it into discrete plans. A local web
server renders each plan as a styled page with decision questions and a feedback form. You
review, answer the decisions, set a verdict (approve / approve with changes / hold /
reject), and submit. The agent reads the feedback and dispatches each approved plan to its
own git worktree and implementation agent. Nothing merges to `main` until you say so.

**Zero external dependencies.** The server runs with `python3` (stdlib only) or
`node` (built-ins only). No npm install. No pip install.

## Install

```bash
npx skills add abassaf/plan-review-hub --copy
```

This installs the skill for your active agent (Codex, Claude Code, or any compatible
provider). The `--copy` flag copies the files so you can edit them locally.

### Manual install (fallback)

If `npx skills` is not available, install directly into the provider's skills directory:

**Codex:**
```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/abassaf/plan-review-hub.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/plan-review-hub"
```

**Claude Code:**
```bash
mkdir -p .claude/skills
git clone https://github.com/abassaf/plan-review-hub.git \
  .claude/skills/plan-review-hub
```

Codex reads `SKILL.md` for trigger metadata and `agents/openai.yaml` for optional UI
metadata.

## Quickstart

1. **Ask your coding agent to generate plans** from a brief:
   > "Use $plan-review-hub to create reviewable plans for [your work]"

   Claude Code users can also say:
   > "Read SKILL.md and create plans for [your work]"

2. **Start the hub:**
   ```bash
   python3 skills/plan-review-hub/scripts/serve.py --plans plans
   # or
   node skills/plan-review-hub/scripts/serve.mjs --plans plans
   ```
   Open the printed URL in your browser.

3. **Review each plan**, answer the decision questions, set a verdict, submit.

4. **Tell the agent to read the feedback** and dispatch approved plans:
   > "Read the feedback and dispatch the approved plans."

5. **Track progress** - the hub shows live implementation status as the agent works.

## Try the examples

The `skills/plan-review-hub/examples/plans/` directory contains 3 realistic plans (API versioning, dark mode,
rate limiting) that render out-of-the-box:

```bash
python3 skills/plan-review-hub/scripts/serve.py --plans skills/plan-review-hub/examples/plans --port 8770
# open http://localhost:8770/
```

The `skills/plan-review-hub/examples/audits/` directory contains a sample findings audit that renders at
`/audit/<id>`:

```bash
python3 skills/plan-review-hub/scripts/serve.py --audits skills/plan-review-hub/examples/audits --port 8770
# open http://localhost:8770/audit/operator-precedence-sweep
```

## Findings audits

Alongside plans, the hub renders **findings audits**: cross-file code findings (the same
bug or anti-pattern repeated across many files) shown as before/after diffs with a status
badge per finding (`Bug` / `Fixed` / `Fine`), headline stat cards, and a "why this is a
bug" box. A plan answers *what should we build?*; an audit answers *where does this problem
already exist and which instances are fixed?*

Each audit is a single JSON file under `<auditsDir>/<id>.json` (default
`.planning-hub/audits/`). Set `planId` to attach it to a plan, or omit it for a standalone
audit. The stat cards are derived from the findings, so they never drift. As fixes land,
flip a finding's `status` from `bug` to `fixed` and add its `commit` — the card moves to the
Fixed section and the counts recompute. See `docs/plan-format.md` for the schema.

## Plan format

Each plan is a folder under `plans/<id>/` (or a custom `--plans` path):

```
plans/
└── api-versioning/
    ├── plan.json      # metadata + decision questions
    ├── proposal.md    # what the plan does and why
    └── tasks.md       # checklist of implementation steps
```

See `docs/plan-format.md` for the full schema.

## OpenSpec adapter

If your project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) and has an
`openspec/changes/` directory, the hub auto-detects it when no `plans/` directory exists.
Set `--source openspec` to force it. See `examples/openspec-note.md` for details.

## Configuration

**Config file** (`plan-review-hub.config.json` in the repo root):

```json
{
  "port":      8770,
  "host":      "0.0.0.0",
  "plansDir":  "plans",
  "source":    "auto",
  "themePath": "assets/themes/default.css",
  "stateDir":  ".planning-hub",
  "auditsDir": null,
  "token":     null
}
```

**Environment variables** override the config file:

| Env var | Description |
|---------|-------------|
| `PLAN_HUB_PORT` | TCP port (default: `8770`) |
| `PLAN_HUB_HOST` | Bind address (default: `0.0.0.0`) |
| `PLAN_HUB_PLANS_DIR` | Plans directory path |
| `PLAN_HUB_SOURCE` | `auto` / `generic` / `openspec` |
| `PLAN_HUB_THEME` | Path to CSS theme file |
| `PLAN_HUB_STATE_DIR` | Feedback + progress state dir (default: `.planning-hub`) |
| `PLAN_HUB_AUDITS_DIR` | Findings-audit JSON dir (default: `<state>/audits`) |
| `PLAN_HUB_TOKEN` | Optional shared-secret access token |

**CLI flags** (both servers support the same flags):

```
--port    TCP port
--host    Bind address
--plans   Plans directory
--source  auto | generic | openspec
--theme   CSS theme file path
--state   State directory path
--audits  Findings-audit JSON directory
--token   Shared-secret token
```

## Theming

All colours and typography are CSS custom properties in `assets/themes/default.css`.
To re-skin the hub, copy the file, change the token values, and pass `--theme`:

```bash
python3 skills/plan-review-hub/scripts/serve.py --theme path/to/my-theme.css
```

See `skills/plan-review-hub/assets/themes/README.md` for a description of every token.

## State

Feedback and progress are written to `.planning-hub/` (gitignored by default):

```
.planning-hub/
├── feedback/
│   ├── api-versioning.json
│   └── dark-mode.json
└── progress.json
```

Update `progress.json` manually or have the implementing agent update it as plans land.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Hub index — all plans with status and progress chips (plus any findings audits) |
| `/plan/<id>` | Single plan — docs, progress card, feedback form |
| `/audit/<id>` | Findings audit — before/after report with a status badge per finding |
| `/feedback` | JSON dump of all collected feedback |
| `/audits` | JSON dump of all findings audits |
| `/assets/...` | Theme CSS and static assets |
| `/healthz` | Health check — returns `{"status":"ok"}` |

## Validation

Run the repository-local validation script before publishing skill changes:

```bash
python3 skills/plan-review-hub/scripts/validate_skill.py --smoke
```

The validator checks skill metadata, Codex UI metadata, JSON plan files, server syntax, and
an optional Python server smoke test. Node syntax is checked when `node` is installed.

## Provider notes

The workflow is intentionally provider-neutral. Provider-specific install and dispatch
details live in `references/provider-notes.md` so `SKILL.md` can stay focused on the core
plan-review-dispatch cycle.

## Feedback fields

Each submitted plan captures:

- **Verdict** — approve / approve with changes / hold / reject
- **Decisions** — answers to per-plan decision questions
- **Notes** — free-text guidance for the implementation
- **Priority** — e.g. `high`, `1`, `urgent`
- **Assignee** — optional routing hint

## Security

> **The hub binds to `0.0.0.0` by default — it is reachable by everyone on your LAN.**
> It is designed for a **trusted LAN** (home or office network) only.
> **Never expose it to the public internet** without a reverse proxy, TLS, and proper
> authentication.

Use `--token mysecret` for light access control within a shared LAN. The first request
must include `?token=mysecret`; subsequent requests use a session cookie.

## License

MIT — Copyright (c) 2026 Anthony Assaf

## Acknowledgements & disclaimers

plan-review-hub is a provider-agnostic, independent open-source project. It is designed
to work with a range of third-party coding agents and tools, but it is **not affiliated
with, sponsored by, or endorsed by** any of them. Product names are used only to
describe compatibility.

- **Claude** and **Claude Code** are products of Anthropic. This project is not
  affiliated with or endorsed by Anthropic.
- **Codex** is a product of OpenAI. This project is not affiliated with or endorsed by
  OpenAI.
- **OpenSpec** is an independent, MIT-licensed open-source project
  ([Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)); plan-review-hub
  interoperates with its convention but is not affiliated with or endorsed by it.

All other product names, logos, and trademarks are the property of their respective
owners. Their mention here denotes compatibility only and implies no affiliation or
endorsement.
