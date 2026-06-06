---
name: plan-review-hub
description: >
  Serve a set of work plans as a styled LAN hub so a human reviewer can approve,
  decide, and give structured feedback on each one — then dispatch each approved
  plan to its own isolated git-worktree subagent and track implementation
  progress live. Use this skill when the user wants to plan multi-step work,
  review proposals via a browser, approve individual plans, and have each plan
  implemented in isolation before merging.
---

# plan-review-hub — workflow instructions

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

## 4. Dispatch approved plans to worktree subagents

For each approved plan, create an isolated git worktree on a new branch and launch
a dedicated subagent scoped to that directory. This keeps the base branch untouched
until each plan is explicitly merged.

```bash
# 1. Identify base branch
BASE=$(git symbolic-ref --short HEAD)   # e.g. main

# 2. For each approved plan (replace <branch> from plan.json):
git worktree add ../worktrees/<id> -b <branch>

# 3. Copy the plan into the worktree for the subagent's reference
cp -r plans/<id> ../worktrees/<id>/.plan-context/
# (or the subagent can read it from the main worktree via relative path)
```

**Dependency setup note:** if the project uses a bundler (Vite, Turbopack, webpack),
do a real `npm install` (or `pnpm install`) inside each worktree rather than symlinking
`node_modules` from the main tree — some bundlers reject symlinked module directories.
For type-check-only or test-only worktrees, a symlink is fine.

**Launch a subagent per plan** with a prompt that includes:
- The plan folder (`plans/<id>/`) and feedback file (`.planning-hub/feedback/<id>.json`)
- The reviewer's decisions and notes from the feedback file
- The instruction: implement everything in this worktree; do not touch the base branch
- The rule: **commits must NOT add a `Co-Authored-By` trailer**

Keep one subagent per plan. Do not share worktrees between plans.

---

## 5. Track progress

As each subagent completes phases, update `.planning-hub/progress.json`:

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

States: `not_started` | `in_progress` | `done`

The hub reflects this live — the hub index shows a progress chip per plan, and each plan
page shows a "Completed / Remaining" card. The reviewer can watch progress at
`http://<ip>:8770/`.

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

## Configuration reference

| Config key | Env var | Default | Description |
|------------|---------|---------|-------------|
| `port` | `PLAN_HUB_PORT` | `8770` | TCP port |
| `host` | `PLAN_HUB_HOST` | `0.0.0.0` | Bind address |
| `plansDir` | `PLAN_HUB_PLANS_DIR` | `plans` | Directory containing plan folders |
| `source` | `PLAN_HUB_SOURCE` | `auto` | `auto` / `generic` / `openspec` |
| `themePath` | `PLAN_HUB_THEME` | `assets/themes/default.css` | CSS theme file path |
| `stateDir` | `PLAN_HUB_STATE_DIR` | `.planning-hub` | Feedback + progress state directory |
| `token` | `PLAN_HUB_TOKEN` | _(none)_ | Optional shared-secret for LAN access control |

---

## Security note

The hub binds to `0.0.0.0` by default — it is reachable by everyone on your LAN.
It is designed for a **trusted LAN** (home or office network) only.
**Never expose it to the public internet** without a reverse proxy, TLS, and proper authentication.
Use `--token` for light access control within a shared LAN.
