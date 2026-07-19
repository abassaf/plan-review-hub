# Provider notes

Keep the core workflow provider-neutral. Use these notes only when a task requires a
provider-specific install or dispatch detail.

## Codex

- Install with `npx skills add abassaf/plan-review-hub --copy` (recommended).
  Manual fallback: clone or copy into `${CODEX_HOME:-$HOME/.codex}/skills/plan-review-hub`.
- Codex reads `SKILL.md` frontmatter for trigger metadata and can also use
  `agents/openai.yaml` for UI-facing metadata.
- Detach the hub from the agent lifecycle (session-tied background tasks die with the
  agent; the reviewer then gets "could not save"). Absolute paths; log under state dir:

  ```bash
  STATE_DIR=/abs/path/to/project/.planning-hub
  mkdir -p "$STATE_DIR"
  nohup python3 /abs/path/to/skills/plan-review-hub/scripts/serve.py \
    --plans /abs/path/to/project/plans \
    --state "$STATE_DIR" \
    --port 8770 \
    > "$STATE_DIR/server.log" 2>&1 & disown
  lsof -nP -iTCP:8770 -sTCP:LISTEN
  ```

- Annotation POST endpoints (`/anno-feedback-add`, etc.) take **form-encoded** bodies, not
  JSON (`400 {"error": "empty feedback"}` on JSON is a body-format miss, not a dead server).
  Smoke test: `curl -s -X POST http://localhost:8770/anno-feedback-add --data-urlencode
  'page=<plan-id>' --data-urlencode 'text=q' --data-urlencode 'comment=smoke'` then
  `/anno-feedback-remove` with `page` + returned `id`.
- If the reviewer reports "could not save", check `lsof -nP -iTCP:<port> -sTCP:LISTEN`
  first — usual cause is a dead server; restart detached.
- When background agent tools are available and explicitly permitted, assign one approved
  plan per worktree. If not, implement manually in the approved worktree and keep
  `.planning-hub/progress.json` current.

## Claude Code

- Install with `npx skills add abassaf/plan-review-hub --copy`.
- Use the same plan files, detached server launch (`nohup … & disown`), feedback files, and
  progress state as Codex. Verify with `lsof -nP -iTCP:<port> -sTCP:LISTEN`.
- When launching Claude Code subagents, keep one approved plan per worktree and include the
  plan folder plus feedback file in the prompt.

---

## GitHub Copilot CLI

Install the skill:

```bash
npx skills add abassaf/plan-review-hub --copy
```

Manual fallback — clone directly into Copilot CLI's skills directory:

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/abassaf/plan-review-hub.git \
  "$HOME/.agents/skills/plan-review-hub"
```

### Starting the server — critical differences from other providers

Copilot CLI runs each `bash` tool call in a **fresh process**. Background processes started
with `&` inside a sync shell call are killed the moment that shell exits — even with `nohup`.
The only reliable way to keep the server alive across turns is to use the `bash` tool with
**`mode="async"` and `detach=true`**:

```python
bash(
    command='python3 /absolute/path/to/serve.py '
            '--plans /absolute/path/to/plans '
            '--state /absolute/path/to/.planning-hub '
            '--port 8770',
    mode='async',
    detach=True,
    shellId='plan-hub',
    initial_wait=5,
)
```

**Always use absolute paths** for `--plans` and `--state`. Each bash call starts in a fresh
shell; relative paths like `plans/` resolve against whatever the OS picks as the working
directory, not the project root. Use `os.path.abspath` or hard-code the full path.

### Verifying the server is running

After the detached launch, verify in a follow-up sync bash call (listener first — a dead
server is the usual "could not save" cause):

```python
bash(command='lsof -nP -iTCP:8770 -sTCP:LISTEN')
bash(command='sleep 3 && curl -s http://localhost:8770/ | grep -o "[0-9]* plans\\|No plans"')
```

Smoke-test annotations with **form-encoded** bodies (JSON → `400 empty feedback`):

```python
bash(command="curl -s -X POST http://localhost:8770/anno-feedback-add "
             "--data-urlencode 'page=<plan-id>' "
             "--data-urlencode 'text=q' "
             "--data-urlencode 'comment=smoke'")
# then /anno-feedback-remove with page + returned id
```

### Getting the LAN IP (to share with reviewers)

```python
bash(command='ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null')
```

### Stopping the server

The `pkill` command is not available in the Copilot CLI environment. Find the PID first,
then kill by PID:

```python
bash(command='lsof -i :8770 | grep LISTEN | awk \'{print $2}\'')
bash(command='kill <PID>')
```

### Plan ordering

The hub sorts plan folders alphabetically by folder name (`sorted(os.listdir(...))`).
The `"num"` field in `plan.json` controls the display number shown on the page but does
**not** affect sort order. To control the order plans appear on the hub index, prefix folder
names with a zero-padded number:

```
plans/
├── 01-e2e-orchestration/
├── 02-web-testing/
├── 03-mobile-testing/
└── 04-backend-mocking/
```

### Markdown table rendering

The built-in `md_to_html` renderer in `scripts/serve.py` does not include GFM table
support by default. If your `proposal.md` or `tasks.md` files use Markdown tables
(`| col | col |` syntax), add the following patch to `scripts/serve.py`:

**1. Add helpers alongside the other `is_*` lambdas (around line 239):**

```python
is_table_row = lambda s: s.strip().startswith("|") and s.strip().endswith("|")
is_table_sep = lambda s: bool(re.match(r"^\s*\|[\s\|\-:]+\|\s*$", s))
```

**2. Include `is_table_row` in `block_starts`:**

```python
def block_starts(raw_line):
    cs = raw_line.strip()
    return (is_bullet(raw_line) or is_olist(raw_line) or is_heading(cs)
            or is_quote(raw_line) or is_fence(raw_line) or is_table_row(raw_line))
```

**3. Add the table rendering block just before the paragraph fallback:**

```python
# GFM table: header row | separator row | data rows
if is_table_row(line) and i + 1 < n and is_table_sep(lines[i + 1]):
    def split_row(r):
        return [c.strip() for c in r.strip().strip("|").split("|")]
    headers = split_row(lines[i])
    i += 2  # skip header + separator
    cells = []
    while i < n and is_table_row(lines[i]):
        cells.append(split_row(lines[i]))
        i += 1
    thead = "".join(f"<th>{inline(h)}</th>" for h in headers)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
        for row in cells
    )
    out.append(f"<table class='md-table'><thead><tr>{thead}</tr></thead>"
               f"<tbody>{tbody}</tbody></table>")
    continue
```

**4. Add table CSS alongside the other `.md-*` rules:**

```css
.md-table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
.md-table th,.md-table td{border:1px solid var(--line);padding:7px 12px;text-align:left;vertical-align:top}
.md-table thead tr{background:var(--surface-warm)}
.md-table th{font-weight:700;color:var(--ink-900)}
.md-table tbody tr:nth-child(even){background:var(--surface-warm)}
```

> Note: this patch has already been applied to the copy of `serve.py` in this repository.
> It is documented here so it is not accidentally lost if `serve.py` is regenerated or
> replaced.
