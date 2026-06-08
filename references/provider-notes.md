# Provider notes

Keep the core workflow provider-neutral. Use these notes only when a task requires a
provider-specific install or dispatch detail.

## Codex

- Install the skill where Codex discovers local skills:
  `${CODEX_HOME:-$HOME/.codex}/skills/plan-review-hub`.
- Codex reads `SKILL.md` frontmatter for trigger metadata and can also use
  `agents/openai.yaml` for UI-facing metadata.
- Use the standard hub commands from the skill directory:
  `python3 scripts/serve.py --plans plans --port 8770` or
  `node scripts/serve.mjs --plans plans --port 8770`.
- When background agent tools are available and explicitly permitted, assign one approved
  plan per worktree. If not, implement manually in the approved worktree and keep
  `.planning-hub/progress.json` current.

## Claude Code

- Existing Claude installs can continue using:
  `npx skills add abassaf/plan-review-hub --copy`.
- Use the same plan files, server commands, feedback files, and progress state as Codex.
- When launching Claude Code subagents, keep one approved plan per worktree and include the
  plan folder plus feedback file in the prompt.
