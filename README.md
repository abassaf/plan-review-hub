# plan-review-hub

A Claude Code skill that turns multi-step work plans into a served LAN hub for review,
approval, feedback collection, and isolated worktree dispatch.

## What it is

You describe work to Claude. Claude breaks it into discrete plans. A local web server
renders each plan as a styled page with decision questions and a feedback form. You review,
answer the decisions, set a verdict (approve / approve with changes / hold / reject), and
submit. Claude reads the feedback and dispatches each approved plan to its own git worktree
and subagent — nothing merges to `main` until you say so.

**Zero external dependencies.** The server runs with `python3` (stdlib only) or
`node` (built-ins only). No npm install. No pip install.

## Install

```bash
npx skills add abassaf/plan-review-hub --copy
```

Or clone directly:

```bash
git clone https://github.com/abassaf/plan-review-hub.git
```

## Quickstart

1. **Ask Claude to generate plans** from a brief:
   > "Read SKILL.md and create plans for [your work]"

2. **Start the hub:**
   ```bash
   python3 scripts/serve.py --plans plans
   # or
   node scripts/serve.mjs --plans plans
   ```
   Open the printed URL in your browser.

3. **Review each plan**, answer the decision questions, set a verdict, submit.

4. **Tell Claude to read the feedback** and dispatch approved plans:
   > "Read the feedback and dispatch the approved plans."

5. **Track progress** — the hub shows live implementation status as Claude works.

## Try the examples

The `examples/plans/` directory contains 3 realistic plans (API versioning, dark mode,
rate limiting) that render out-of-the-box:

```bash
python3 scripts/serve.py --plans examples/plans --port 8770
# open http://localhost:8770/
```

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

If your project uses [OpenSpec](https://github.com/abassaf/openspec) and has an
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
| `PLAN_HUB_TOKEN` | Optional shared-secret access token |

**CLI flags** (both servers support the same flags):

```
--port    TCP port
--host    Bind address
--plans   Plans directory
--source  auto | generic | openspec
--theme   CSS theme file path
--state   State directory path
--token   Shared-secret token
```

## Theming

All colours and typography are CSS custom properties in `assets/themes/default.css`.
To re-skin the hub, copy the file, change the token values, and pass `--theme`:

```bash
python3 scripts/serve.py --theme path/to/my-theme.css
```

See `assets/themes/README.md` for a description of every token.

## State

Feedback and progress are written to `.planning-hub/` (gitignored by default):

```
.planning-hub/
├── feedback/
│   ├── api-versioning.json
│   └── dark-mode.json
└── progress.json
```

Update `progress.json` manually or have Claude update it as subagents land changes.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Hub index — all plans with status and progress chips |
| `/plan/<id>` | Single plan — docs, progress card, feedback form |
| `/feedback` | JSON dump of all collected feedback |
| `/assets/...` | Theme CSS and static assets |
| `/healthz` | Health check — returns `{"status":"ok"}` |

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
