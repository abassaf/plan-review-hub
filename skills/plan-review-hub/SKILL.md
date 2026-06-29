---
name: plan-review-hub
description: >
  Serve a set of work plans as a styled LAN hub so a human reviewer can approve,
  decide, and give structured feedback on each one, then dispatch each approved
  plan to its own isolated git-worktree implementation agent and track progress
  live. Use this skill in Codex, Claude Code, or another local coding-agent
  workflow when the user wants to plan multi-step work, review proposals via a
  browser, approve individual plans, and have each plan implemented in isolation
  before merging.
---

# plan-review-hub - workflow instructions

This skill packages a complete plan → review → approve → dispatch → track cycle.
Follow the numbered steps in order. All paths are relative to the project root unless stated.

---

## 1. Generate plans from a brief

When the user gives you a brief (a problem to solve, a set of features to build, or an
existing set of changes):

**From a brief:**
1. Break the work into discrete, independently implementable plans (typically 2–6).
2. For each plan, create a folder under `plans/<id>/` (or the configured `--plans` path):
   - `plan.json` — metadata + decision questions (see `docs/plan-format.md` for the schema)
   - `proposal.md` — what the plan does, why, and what changes
   - `tasks.md` — a Markdown checklist (`- [ ]` / `- [x]`) broken into phases
3. Use clear, URL-safe IDs (`api-versioning`, `dark-mode`, `rate-limiting`).
4. Keep plans independent where possible; note explicit dependencies in `proposal.md`.
5. Populate `decisions` in `plan.json` for any fork-in-the-road choices the reviewer must make.

**From OpenSpec changes (auto-detected):**
If `openspec/changes/` exists and no `plans/` directory is present, the hub auto-detects
it. You can also add a `plan.json` inside any change directory to enrich it with decisions.
See `examples/openspec-note.md` for details.

---

## 2. Serve the hub

Start the server bound to the LAN so the reviewer can open it in a browser:

```bash
# Python (recommended — zero dependencies)
python3 scripts/serve.py --plans plans --port 8770

# or Node (built-ins only, no npm needed)
node scripts/serve.mjs --plans plans --port 8770
```

The server prints the hub URL and one URL per plan. Share them with the reviewer.
The hub auto-reloads plan data on every request — edit plans without restarting.

**GitHub Copilot CLI — special requirements:**

Each `bash` tool call runs in a fresh process; background processes started with `&` are
killed when that shell exits. You **must** use `mode="async"` with `detach=true`, and
**always pass absolute paths** to `--plans` and `--state` (relative paths resolve against
an unpredictable working directory):

```python
bash(
    command='python3 /abs/path/to/skills/plan-review-hub/scripts/serve.py '
            '--plans /abs/path/to/project/plans '
            '--state /abs/path/to/project/.planning-hub '
            '--port 8770',
    mode='async',
    detach=True,
    shellId='plan-hub',
    initial_wait=5,
)
```

Verify in a follow-up call: `curl -s http://localhost:8770/ | grep -o "[0-9]* plans"`.
To stop: `lsof -i :8770 | grep LISTEN | awk '{print $2}'` then `kill <PID>`
(`pkill` is not available in the Copilot CLI environment).

See `references/provider-notes.md` for the full Copilot CLI section, including plan
ordering, LAN IP retrieval, and the GFM table patch for `serve.py`.

**Optional: token-protected access**

```bash
python3 scripts/serve.py --token mysecret
# reviewer opens: http://<ip>:8770/?token=mysecret  (cookie set; subsequent requests need no token)
```

**Config file:** edit `plan-review-hub.config.json` to set permanent defaults.
**Env vars:** `PLAN_HUB_PORT`, `PLAN_HUB_HOST`, `PLAN_HUB_PLANS_DIR`, `PLAN_HUB_SOURCE`,
`PLAN_HUB_THEME`, `PLAN_HUB_STATE_DIR`, `PLAN_HUB_TOKEN`.

---

## 3. Collect and interpret feedback

After the reviewer submits feedback via the hub, each plan's feedback is written to
`.planning-hub/feedback/<id>.json`. Read all of them:

```bash
# quick JSON dump of all feedback (while server is running)
curl http://localhost:8770/feedback | python3 -m json.tool

# or read directly from disk
cat .planning-hub/feedback/*.json
```

Interpret each file:
- `verdict`: `approve` | `approve_with_changes` | `hold` | `reject`
- `decisions`: map of decision-id → chosen option value
- `notes`: free-text guidance; apply these instructions to the implementation
- `priority`: ordering hint (e.g. `high`, `1`, `urgent`)
- `assignee`: optional routing hint

Plans with `approve` or `approve_with_changes` proceed to dispatch.
Plans with `hold` wait for further discussion.
Plans with `reject` are dropped from the queue.

---

## 4. Dispatch approved plans to worktree implementation agents

For each approved plan, create an isolated git worktree on a new branch and launch,
resume, or manually continue a dedicated implementation agent scoped to that directory.
This keeps the base branch untouched until each plan is explicitly merged.

```bash
# 1. Identify base branch
BASE=$(git symbolic-ref --short HEAD)   # e.g. main

# 2. For each approved plan (replace <branch> from plan.json):
git worktree add ../worktrees/<id> -b <branch>

# 3. Copy the plan into the worktree for the implementation agent's reference
cp -r plans/<id> ../worktrees/<id>/.plan-context/
# (or the agent can read it from the main worktree via relative path)
```

**Dependency setup note:** if the project uses a bundler (Vite, Turbopack, webpack),
do a real `npm install` (or `pnpm install`) inside each worktree rather than symlinking
`node_modules` from the main tree — some bundlers reject symlinked module directories.
For type-check-only or test-only worktrees, a symlink is fine.

**Launch one implementation agent per plan** with a prompt that includes:
- The plan folder (`plans/<id>/`) and feedback file (`.planning-hub/feedback/<id>.json`)
- The reviewer's decisions and notes from the feedback file
- The instruction: implement everything in this worktree; do not touch the base branch
- The rule: **commits must NOT add a `Co-Authored-By` trailer**

Keep one implementation agent per plan. Do not share worktrees between plans.

If the current provider does not expose background agents or delegation tools, keep the
same isolation guarantees by doing the work manually in the relevant worktree. If plans
overlap heavily and the reviewer approves a combined implementation, record that choice in
`.planning-hub/progress.json` before proceeding.

For provider-specific install and dispatch notes, read `references/provider-notes.md` only
when you need Codex or Claude Code details.

---

## 5. Track progress

As each implementation agent completes phases, update `.planning-hub/progress.json`:

```json
{
  "api-versioning": {
    "state":     "in_progress",
    "label":     "In progress",
    "branch":    "feat/api-versioning",
    "done":      ["Version middleware added", "Unit tests pass"],
    "remaining": ["OpenAPI spec update", "Integration tests", "Merge"]
  }
}
```

States: `not_started` | `in_progress` | `done` (extend with project-specific states as
needed, e.g. `planned`, `ready_to_ship`, `blocked` — each mapped to a status badge).

The hub reflects this live — the hub index shows a progress chip per plan, and each plan
page shows a "Completed / Remaining" card. The reviewer can watch progress at
`http://<ip>:8770/`.

### Keep the hub current — update it after EVERY status change (not just at the end)

The hub is the reviewer's single source of truth, so it must never drift from reality.
**Whenever a plan's real state changes, immediately update its entry on the hub and
restart the server** — treat this as part of the action, not an afterthought. Update on
each of these transitions:

- **approved** → reflect the verdict/decisions the reviewer submitted
- **work started** → flip the plan from its `backlogged`/`planned`/`not_started` state to
  `in_progress` **the moment you begin, before writing code** — not when you finish. This
  applies even when you implement directly in the main repo with no separate worktree (set
  `branch` to e.g. `main (combined local implementation)`). A plan that is being worked on
  must never still read `backlogged` on the hub.
- **dispatched** → `in_progress` with the worktree branch + agent
- **implemented / committed** → record what landed + the commit
- **PR opened / CI green** → e.g. a `ready_to_ship` state with the PR number
- **merged / deployed / shipped** → `done`; if the project separates "open proposals"
  from "past reviews", **move the shipped plan into the past-reviews/completed section**
- **backlogged or deferred** → mark it so, with the reason
- **plan fully fleshed out** (design + spec written) → e.g. a `planned` state

Also surface each plan's **open decisions** on its page (don't leave the decisions block
empty) so the reviewer always has something actionable. After any edit: re-run the
server's syntax check, restart it, and verify the index + the affected plan page render.

If you find yourself reporting progress to the user without having updated the hub, that's
the signal you've drifted — update the hub first, then report.

---

## 6. Merge helper

Once one or more plans reach `done` state, suggest a merge order:

1. **Check file overlap** between branches to identify conflicts:
   ```bash
   for branch in feat/plan-a feat/plan-b feat/plan-c; do
     git diff --name-only main..."$branch"
   done
   ```
2. **Suggest an order**: merge plans with no shared files first; flag overlapping branches
   as requiring manual conflict resolution.
3. **Before merging each branch**: run the project's quality gate (tests, lint, type-check).
4. **Merge**: open a PR or merge directly per the project's workflow.
5. **Clean up worktrees** after merge:
   ```bash
   git worktree remove ../worktrees/<id>
   git branch -d <branch>
   ```

Common patterns:
- Plans that touch different layers (API vs UI vs DB) are usually safe to merge in any order.
- Plans that both touch shared config, middleware, or schema files must be merged sequentially;
  merge the simpler one first and rebase the other onto the updated base.

---

## 7. Findings audits (optional visual report)

A **findings audit** is a sibling artefact to a plan. A plan answers *what should we build?*;
an audit answers *where does this problem already exist, what does the fix look like, and
which instances are done?* It renders cross-file code findings — the same bug, anti-pattern,
deprecated call, or risky idiom repeated across many files — as before/after diffs with a
status badge per finding, headline stat cards, and a "why this is a bug" box. The hub serves
it at `/audit/<id>` using the active theme.

**Create an audit when** a scan/search has turned up the same shape in **3+ files**, when the
reviewer asks for "an overview of where this pattern appears" or "an audit report", or when a
set of before/after fixes is clearer visually than as a wall of text. **Do not** create one
for a single-file finding (just show the diff inline) or for planning/proposal content (that
is a plan, not an audit). This is **not a linter or scanner** — it renders findings some other
step produced; it never runs analysis on its own, and never posts to any external code host.

**Steps:**

1. Gather findings (run the search). For each hit record: repo-relative file path, line, the
   buggy code and its fix, a plain-English reason **specific to that instance**, and whether
   it is `bug` (needs fixing), `fixed`, or `fine` (a false positive that matched but is
   correct).
2. Write one JSON file to `<auditsDir>/<id>.json` (default `.planning-hub/audits/<id>.json`).
   See `docs/plan-format.md` for the schema. Set `planId` to attach it to a plan; omit it for
   a standalone audit. The stat cards are derived from the findings, so never hand-maintain
   counts. Quality bar: real file paths and line numbers, real commit SHAs, no placeholder
   text, and a `why` box that names the exact failure mode.
3. Point the reviewer at `http://<ip>:<port>/audit/<id>` (it is also linked from the hub index
   and from any plan it names).
4. **Update in place as fixes land** — same discipline as progress: change the finding's
   `status` from `bug` to `fixed` and add its `commit`; the card moves to the Fixed section and
   the counts recompute on the next request. Drop the "confirmed fine" findings once the
   reviewer has reviewed them. Do this after each fix, not only at the end.

To preview the bundled example: `python3 scripts/serve.py --audits examples/audits`
(or `--state examples` if you keep audits under a state dir).

---

## Configuration reference

| Config key | Env var | Default | Description |
|------------|---------|---------|-------------|
| `port` | `PLAN_HUB_PORT` | `8770` | TCP port |
| `host` | `PLAN_HUB_HOST` | `0.0.0.0` | Bind address |
| `plansDir` | `PLAN_HUB_PLANS_DIR` | `plans` | Directory containing plan folders |
| `source` | `PLAN_HUB_SOURCE` | `auto` | `auto` / `generic` / `openspec` |
| `themePath` | `PLAN_HUB_THEME` | `assets/themes/default.css` | CSS theme file path |
| `stateDir` | `PLAN_HUB_STATE_DIR` | `.planning-hub` | Feedback + progress state directory |
| `auditsDir` | `PLAN_HUB_AUDITS_DIR` | `<stateDir>/audits` | Findings-audit JSON directory |
| `token` | `PLAN_HUB_TOKEN` | _(none)_ | Optional shared-secret for LAN access control |

---

## Security note

The hub binds to `0.0.0.0` by default — it is reachable by everyone on your LAN.
It is designed for a **trusted LAN** (home or office network) only.
**Never expose it to the public internet** without a reverse proxy, TLS, and proper authentication.
Use `--token` for light access control within a shared LAN.
