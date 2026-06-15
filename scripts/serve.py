#!/usr/bin/env python3
"""
plan-review-hub — Python stdlib server (zero dependencies beyond Python 3.8+).

Serves a styled LAN hub for reviewing and approving multi-step work plans,
collecting structured feedback, and tracking implementation progress.

GET  /                  hub index (all plans + status)
GET  /plan/<id>         single plan page (summary + docs + feedback form)
GET  /assets/<path>     theme CSS and any other static assets
GET  /feedback          JSON dump of all collected feedback
GET  /healthz           200 {"status":"ok"}
POST /submit            write feedback JSON; returns {"ok":true}

Usage:
  python3 scripts/serve.py [--port 8770] [--host 0.0.0.0]
             [--plans plans] [--source auto|generic|openspec]
             [--theme assets/themes/default.css]
             [--state .planning-hub] [--token SECRET]

Environment variables override config file; CLI flags override env vars.
"""
import http.server
import socketserver
import json
import os
import re
import html
import urllib.parse
import socket
import argparse
import sys
import http.cookies
import datetime

# ─── configuration ────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def load_config():
    """Merge built-in defaults < config file < env vars. CLI flags applied later."""
    defaults = {
        "port":      8770,
        "host":      "0.0.0.0",
        "plansDir":  "plans",
        "source":    "auto",
        "themePath": "assets/themes/default.css",
        "stateDir":  ".planning-hub",
        "auditsDir": None,
        "token":     None,
    }
    cfg_path = os.path.join(REPO, "plan-review-hub.config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                file_cfg = json.load(f)
            for k in defaults:
                if k in file_cfg and not str(k).startswith("_"):
                    defaults[k] = file_cfg[k]
        except Exception:
            pass
    # env var overrides
    env_map = {
        "PLAN_HUB_PORT":      ("port",      int),
        "PLAN_HUB_HOST":      ("host",      str),
        "PLAN_HUB_PLANS_DIR": ("plansDir",  str),
        "PLAN_HUB_SOURCE":    ("source",    str),
        "PLAN_HUB_THEME":     ("themePath", str),
        "PLAN_HUB_STATE_DIR": ("stateDir",  str),
        "PLAN_HUB_AUDITS_DIR":("auditsDir", str),
        "PLAN_HUB_TOKEN":     ("token",     str),
    }
    for env_key, (cfg_key, cast) in env_map.items():
        v = os.environ.get(env_key)
        if v is not None:
            defaults[cfg_key] = cast(v)
    return defaults


CFG = load_config()

# ─── plan loading ──────────────────────────────────────────────────────────────

def _abs(path):
    """Resolve path relative to REPO if not absolute."""
    return path if os.path.isabs(path) else os.path.join(REPO, path)


def _infer_title_tagline(text):
    """Extract title from first # heading and tagline from first plain paragraph."""
    title, tagline = "", ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            for rest in lines[i+1:]:
                rest = rest.strip()
                if rest and not rest.startswith("#"):
                    tagline = rest
                    break
            break
    return title or "Untitled plan", tagline


def load_plans():
    """Return ordered list of plan dicts based on source setting."""
    source = CFG["source"]
    plans_dir = _abs(CFG["plansDir"])
    openspec_dir = os.path.join(REPO, "openspec", "changes")

    if source == "generic":
        return _load_generic(plans_dir)
    if source == "openspec":
        return _load_openspec(openspec_dir)
    # auto
    generic = _load_generic(plans_dir)
    if generic:
        return generic
    if os.path.isdir(openspec_dir):
        return _load_openspec(openspec_dir)
    return []


def _load_generic(plans_dir):
    """Load plans from <plansDir>/<id>/plan.json subdirectories."""
    if not os.path.isdir(plans_dir):
        return []
    plans = []
    for name in sorted(os.listdir(plans_dir)):
        pdir = os.path.join(plans_dir, name)
        pjson = os.path.join(pdir, "plan.json")
        if not os.path.isdir(pdir) or not os.path.isfile(pjson):
            continue
        try:
            with open(pjson) as f:
                p = json.load(f)
        except Exception:
            continue
        p.setdefault("id", name)
        p.setdefault("num", f"{len(plans)+1:02d}")
        p.setdefault("title", name.replace("-", " ").title())
        p.setdefault("tagline", "")
        p.setdefault("branch", "")
        p.setdefault("effort", "")
        p.setdefault("risk", "")
        p.setdefault("headline", "")
        p.setdefault("docs", [])
        p.setdefault("decisions", [])
        p["_dir"] = pdir
        plans.append(p)
    return plans


def _load_openspec(changes_dir):
    """Load plans from openspec/changes/<id>/ directories."""
    if not os.path.isdir(changes_dir):
        return []
    plans = []
    for name in sorted(os.listdir(changes_dir)):
        cdir = os.path.join(changes_dir, name)
        if not os.path.isdir(cdir):
            continue
        # optional plan.json inside the change dir
        pjson_path = os.path.join(cdir, "plan.json")
        p = {}
        if os.path.isfile(pjson_path):
            try:
                with open(pjson_path) as f:
                    p = json.load(f)
            except Exception:
                p = {}
        # infer title/tagline from proposal.md if not set
        proposal_path = os.path.join(cdir, "proposal.md")
        if "title" not in p or "tagline" not in p:
            proposal_text = ""
            if os.path.isfile(proposal_path):
                with open(proposal_path) as f:
                    proposal_text = f.read()
            inf_title, inf_tagline = _infer_title_tagline(proposal_text)
            p.setdefault("title", inf_title)
            p.setdefault("tagline", inf_tagline)
        p.setdefault("id", name)
        p.setdefault("num", f"{len(plans)+1:02d}")
        p.setdefault("branch", "")
        p.setdefault("effort", "")
        p.setdefault("risk", "")
        p.setdefault("headline", "")
        p.setdefault("decisions", [])
        # docs: use all md files that exist in the change dir
        if "docs" not in p:
            candidate_docs = ["proposal.md", "design.md", "tasks.md"]
            p["docs"] = [d for d in candidate_docs if os.path.isfile(os.path.join(cdir, d))]
        p["_dir"] = cdir
        plans.append(p)
    return plans

# ─── markdown renderer ─────────────────────────────────────────────────────────

def inline_md(s, links=True):
    """Render inline markdown (bold, italic, code, links) to HTML. Escapes HTML first.
    Pass links=False to collapse [text](url) to just the text — use inside <a> containers
    to avoid invalid nested anchors."""
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    # italics: a single * pair, not part of a ** run, wrapping non-space text
    s = re.sub(r"(?<!\*)\*(?!\*)(?=\S)([^*\n]+?)(?<=\S)\*(?!\*)", r"<em>\1</em>", s)
    # markdown links [text](url)
    if links:
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    else:
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", s)
    return s


def md_to_html(text):
    """
    Minimal Markdown → HTML.
    Block-level: ATX headings (#–####), bullet lists (- / *) with wrapped
    continuation lines, blockquotes (>), fenced code blocks, and paragraphs.
    Soft-wrapped source lines within a block are reflowed into one element, so
    hard-wrapped Markdown renders as continuous prose instead of one <p> per
    source line.
    Inline: **bold**, *italic*, `code`.
    Checkboxes: [ ] → ☐  [x]/[X] → ☑  (rendered AFTER html.escape so the
    span is never escaped).
    """
    def inline(s):
        return inline_md(s)

    def checkbox(rendered):
        # html.escape has already run; inject the span safely
        return re.sub(
            r"^\[([xX ])\]\s*",
            lambda mm: (
                "<span class='chk chk-done'>&#9745;</span> "
                if mm.group(1) in "xX"
                else "<span class='chk'>&#9744;</span> "
            ),
            rendered,
        )

    lines = text.splitlines()
    n = len(lines)
    out = []
    i = 0

    is_heading = lambda s: re.match(r"^#{1,4}\s+", s)
    is_bullet = lambda s: re.match(r"^\s*[-*]\s+", s)
    is_olist = lambda s: re.match(r"^\s*\d+\.\s+", s)
    is_quote = lambda s: s.lstrip().startswith(">")
    is_fence = lambda s: s.lstrip().startswith("```")
    is_table_row = lambda s: s.strip().startswith("|") and s.strip().endswith("|")
    is_table_sep = lambda s: bool(re.match(r"^\s*\|[\s\|\-:]+\|\s*$", s))
    is_hr = lambda s: bool(re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", s))
    # GFM table support — see references/provider-notes.md (GitHub Copilot CLI section)

    def block_starts(raw_line):
        cs = raw_line.strip()
        return (is_bullet(raw_line) or is_olist(raw_line) or is_heading(cs)
                or is_quote(raw_line) or is_fence(raw_line) or is_table_row(raw_line)
                or is_hr(raw_line))

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank line → block separator
        if not stripped:
            i += 1
            continue

        # fenced code block (verbatim until the closing fence)
        if is_fence(line):
            i += 1
            code = []
            while i < n and not is_fence(lines[i]):
                code.append(html.escape(lines[i]))
                i += 1
            i += 1  # consume the closing fence if present
            out.append(
                "<pre class='code-block'><code>" + "\n".join(code) + "</code></pre>"
            )
            continue

        # heading (single line)
        m = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m:
            lvl = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lvl} class='md-h'>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        # blockquote: gather consecutive '>' lines, reflow into paragraphs
        if is_quote(line):
            q_lines = []
            while i < n and is_quote(lines[i]):
                q_lines.append(re.sub(r"^\s*>\s?", "", lines[i].rstrip()))
                i += 1
            paras, buf = [], []
            for q in q_lines:
                if q.strip():
                    buf.append(q.strip())
                elif buf:
                    paras.append(" ".join(buf))
                    buf = []
            if buf:
                paras.append(" ".join(buf))
            inner = "".join(f"<p>{inline(p)}</p>" for p in paras)
            out.append(f"<blockquote class='md-quote'>{inner}</blockquote>")
            continue

        # bullet list: each item may wrap across indented continuation lines
        if is_bullet(line):
            out.append("<ul class='md-ul'>")
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    break
                mm = re.match(r"^\s*[-*]\s+(.*)$", cur)
                if not mm:
                    break
                parts = [mm.group(1).strip()]
                i += 1
                while i < n and lines[i].strip() and not block_starts(lines[i]):
                    parts.append(lines[i].strip())
                    i += 1
                out.append(f"<li>{checkbox(inline(' '.join(parts)))}</li>")
            out.append("</ul>")
            continue

        # ordered list: "1. ", "2. " … each item may wrap across lines
        if is_olist(line):
            out.append("<ol class='md-ol'>")
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    break
                mm = re.match(r"^\s*\d+\.\s+(.*)$", cur)
                if not mm:
                    break
                parts = [mm.group(1).strip()]
                i += 1
                while i < n and lines[i].strip() and not block_starts(lines[i]):
                    parts.append(lines[i].strip())
                    i += 1
                out.append(f"<li>{inline(' '.join(parts))}</li>")
            out.append("</ol>")
            continue

        # horizontal rule: ---, ***, ___
        if is_hr(line):
            out.append("<hr class='md-hr'>")
            i += 1
            continue

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
            out.append(f"<table class='md-table'><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue

        # paragraph: reflow wrapped lines until a blank line or a new block
        parts = []
        while i < n and lines[i].strip() and not block_starts(lines[i]):
            parts.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(parts))}</p>")

    return "\n".join(out)


def read_plan_doc(plan, filename):
    pdir = plan.get("_dir", "")
    if not pdir:
        return ""
    path = os.path.join(pdir, filename)
    if not os.path.isfile(path):
        return ""
    with open(path) as f:
        return f.read()

# ─── state helpers ─────────────────────────────────────────────────────────────

def state_dir():
    return _abs(CFG["stateDir"])


def feedback_dir():
    d = os.path.join(state_dir(), "feedback")
    os.makedirs(d, exist_ok=True)
    return d


def get_feedback(plan_id):
    path = os.path.join(feedback_dir(), f"{plan_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def get_progress():
    path = os.path.join(state_dir(), "progress.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


# ─── audit loading ─────────────────────────────────────────────────────────────
# A "findings audit" renders cross-file code findings (the same bug/anti-pattern
# repeated across many files) as before/after diffs with a per-finding status.
# Audits are standalone artefacts; an audit may optionally name a planId to link
# it to a plan. They are loaded from <auditsDir> (default <stateDir>/audits).

def audits_dir():
    if CFG.get("auditsDir"):
        return _abs(CFG["auditsDir"])
    return os.path.join(state_dir(), "audits")


def _normalise_audit(a, fallback_id):
    a.setdefault("id", fallback_id)
    a.setdefault("title", a["id"].replace("-", " ").title())
    a.setdefault("planId", None)
    a.setdefault("pattern", {})
    a.setdefault("why", "")
    a.setdefault("summary", "")
    a.setdefault("findings", [])
    return a


def load_audits():
    """Return ordered list of audit dicts from the audits directory."""
    d = audits_dir()
    if not os.path.isdir(d):
        return []
    audits = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(d, name)
        try:
            with open(path) as f:
                a = json.load(f)
        except Exception:
            continue
        if not isinstance(a, dict):
            continue
        audits.append(_normalise_audit(a, name[:-len(".json")]))
    return audits


def get_audit(audit_id):
    for a in load_audits():
        if a["id"] == audit_id:
            return a
    return None


def audit_counts(audit):
    """Return (fixed, bug, fine, total) counts derived from findings."""
    fixed = bug = fine = 0
    for f in audit.get("findings", []):
        st = f.get("status", "bug")
        if st == "fixed":
            fixed += 1
        elif st == "fine":
            fine += 1
        else:
            bug += 1
    return fixed, bug, fine, len(audit.get("findings", []))

# ─── research docs ─────────────────────────────────────────────────────────────
# Markdown files in <plans_parent>/research/ (or <stateDir>/research/) are served
# as styled reference pages at /docs/<id> and linked from the hub index.

def research_dir():
    candidate = os.path.join(os.path.dirname(_abs(CFG["plansDir"])), "research")
    if os.path.isdir(candidate):
        return candidate
    return os.path.join(state_dir(), "research")


def load_research_docs():
    d = research_dir()
    if not os.path.isdir(d):
        return []
    docs = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(d, fname)
        try:
            text = open(fpath, encoding="utf-8").read()
        except Exception:
            continue
        doc_id = fname[:-3]
        title, tagline = _infer_title_tagline(text)
        docs.append({"id": doc_id, "title": title, "tagline": tagline, "text": text})
    return docs


def get_research_doc(doc_id):
    for d in load_research_docs():
        if d["id"] == doc_id:
            return d
    return None


def render_doc(doc, theme_css):
    crumb = f"<a href='/'>Hub</a> › <span>Research</span>"
    body = f"""
<div class='wrap'>
  <div class='with-sidebar'>
    <div class='sidebar'>
      <div class='eyebrow' style='margin-bottom:8px'>Research &amp; References</div>
{''.join(
    f"<a class='{'active' if d['id']==doc['id'] else ''}' href='/docs/{html.escape(d['id'])}'>"
    f"<span>{html.escape(d['title'])}</span></a>"
    for d in load_research_docs()
)}
    </div>
    <div class='main-col'>
      <div class='eyebrow'>Reference document</div>
      <h1 class='page-title'>{html.escape(doc['title'])}</h1>
      {'<p class="lead">'+inline_md(doc['tagline'])+'</p>' if doc['tagline'] else ''}
      <div class='card' style='margin-top:16px'>
        <div class='prose'>{md_to_html(doc['text'])}</div>
      </div>
    </div>
  </div>
  <div class='footer'>Superloop E2E Hub · <a href='/'>hub</a></div>
</div>"""
    return page_shell(doc['title'], crumb, body, theme_css)



def local_ips():
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except Exception:
        pass
    if not ips:
        ips.append("127.0.0.1")
    return ips

# ─── theming ───────────────────────────────────────────────────────────────────

def load_theme_css():
    theme_path = _abs(CFG["themePath"])
    if os.path.isfile(theme_path):
        with open(theme_path) as f:
            return f.read()
    # minimal built-in fallback (neutral indigo palette)
    return """
:root {
  --bg:#f5f6f8; --surface:#fff; --surface-warm:#fafaf9;
  --line:#e4e7ec; --line-2:#d0d5dd;
  --ink-900:#111827; --ink-700:#374151; --ink-500:#6b7280;
  --accent:#4f46e5; --accent-soft:#eef2ff; --accent-dark:#3730a3;
  --green:#059669; --green-bg:#d1fae5;
  --yellow:#d97706; --yellow-bg:#fef3c7;
  --red:#dc2626; --red-bg:#fee2e2;
  --blue:#2563eb; --blue-bg:#dbeafe;
  --font-body:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --font-display:var(--font-body);
  --font-mono:ui-monospace,Menlo,Consolas,monospace;
  --radius-sm:8px; --radius:12px; --radius-lg:16px; --radius-pill:999px;
  --shadow-sm:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
}
"""

# ─── HTML components ───────────────────────────────────────────────────────────

PROGRESS_STATE_CHIP = {
    "done":         ("chip-done",        "Done"),
    "in_progress":  ("chip-in-progress", "In progress"),
    "not_started":  ("chip-none",        "Not started"),
}
VERDICT_CHIP = {
    "approve":              ("chip-approve",   "Approve"),
    "approve_with_changes": ("chip-awc",       "Approve with changes"),
    "hold":                 ("chip-hold",      "Hold"),
    "reject":               ("chip-reject",    "Reject"),
}


def chip(cls, label):
    return f"<span class='chip {html.escape(cls)}'>{html.escape(label)}</span>"


def render_progress_card(plan_id, progress):
    pr = progress.get(plan_id)
    if not pr:
        return ""
    state = pr.get("state", "not_started")
    chip_cls, chip_label = PROGRESS_STATE_CHIP.get(state, ("chip-none", state))
    done_items = pr.get("done", [])
    rem_items = pr.get("remaining", [])
    branch = html.escape(pr.get("branch", ""))

    done_rows = "".join(
        f"<li><span class='chk chk-done'>&#9745;</span> {html.escape(x)}</li>"
        for x in done_items
    )
    rem_rows = "".join(
        f"<li><span class='chk'>&#9744;</span> {html.escape(x)}</li>"
        for x in rem_items
    )
    done_col = f"<div class='prog-col'><div class='prog-h prog-done'>Completed</div><ul class='md-ul'>{done_rows}</ul></div>" if done_items else ""
    rem_col = f"<div class='prog-col'><div class='prog-h prog-rem'>Remaining</div><ul class='md-ul'>{rem_rows}</ul></div>" if rem_items else ""
    branch_note = f"<div class='branch-note'>Branch <code>{branch}</code></div>" if branch else ""
    return f"""
<div class='card'>
  <h2>Implementation progress {chip(chip_cls, chip_label)}</h2>
  {branch_note}
  <div class='prog-grid'>{done_col}{rem_col}</div>
</div>"""


def page_shell(title, crumbs_html, body_html, theme_css):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{theme_css}
/* ── layout ── */
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink-900);font-family:var(--font-body);line-height:1.55}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
.topbar{{background:var(--ink-900);color:#fff;padding:13px 22px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:20}}
.topbar .logo{{width:28px;height:28px;border-radius:var(--radius-sm);background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:#fff;flex-shrink:0}}
.topbar .title-block b{{font-size:15px}}
.topbar .sub{{color:#9ca3af;font-size:12px;margin-left:6px}}
.topbar .crumbs{{margin-left:auto;font-size:12.5px;color:#9ca3af}}
.topbar .crumbs a{{color:#d1d5db}}
.wrap{{max-width:1100px;margin:0 auto;padding:0 22px 80px}}
.hero{{padding:26px 0 10px}}
.eyebrow{{font:600 11px/1 var(--font-display);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}}
h1.page-title{{font:700 28px/1.15 var(--font-display);letter-spacing:-.01em;margin:6px 0 6px}}
.lead{{color:var(--ink-700);font-size:14.5px;max-width:720px;margin:0}}
/* ── cards ── */
.card{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:20px 22px;margin:14px 0;box-shadow:var(--shadow-sm)}}
.card h2{{font:700 17px/1.2 var(--font-display);margin:0 0 10px}}
/* ── chips ── */
.chip{{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:3px 9px;font:600 11px/1.4 var(--font-display)}}
.chip-none{{background:var(--line);color:var(--ink-700)}}
.chip-done{{background:var(--green-bg);color:var(--green)}}
.chip-in-progress{{background:var(--blue-bg);color:var(--blue)}}
.chip-approve{{background:var(--green-bg);color:var(--green)}}
.chip-awc{{background:var(--yellow-bg);color:var(--yellow)}}
.chip-hold{{background:var(--blue-bg);color:var(--blue)}}
.chip-reject{{background:var(--red-bg);color:var(--red)}}
/* ── meta pills ── */
.meta{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}}
.kv{{background:var(--accent-soft);border-radius:var(--radius);padding:7px 11px;font-size:12px;color:var(--ink-700)}}
.kv b{{display:block;color:var(--ink-900);font-size:13px}}
.headline-box{{background:var(--surface-warm);border:1px solid var(--line-2);border-radius:var(--radius);padding:13px 15px;font-size:13.5px}}
/* ── index rows ── */
.index-row{{display:flex;gap:14px;align-items:center;padding:16px 18px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);margin:10px 0;text-decoration:none;color:inherit;transition:border-color .15s}}
.index-row:hover{{border-color:var(--accent);text-decoration:none}}
.index-row .num{{font:800 20px/1 var(--font-display);color:var(--accent);opacity:.35;width:34px;flex-shrink:0}}
.index-row .body{{flex:1}}
.index-row .body h3{{margin:0 0 2px;font:700 15px/1.2 var(--font-display)}}
.index-row .body p{{margin:0;color:var(--ink-700);font-size:13px}}
.index-row .aside{{text-align:right;min-width:130px;flex-shrink:0}}
/* ── grid layout ── */
.two-col{{display:grid;grid-template-columns:1fr 260px;gap:22px;align-items:start}}
@media(max-width:860px){{.two-col{{grid-template-columns:1fr}}}}
.sticky-side{{position:sticky;top:60px}}
/* ── side nav ── */
.side-nav a{{display:flex;justify-content:space-between;align-items:center;padding:9px 11px;border-radius:var(--radius);color:var(--ink-900);font-size:12.5px;font-weight:600;text-decoration:none}}
.side-nav a:hover{{background:var(--accent-soft);text-decoration:none}}
.side-nav a.active{{background:var(--accent);color:#fff}}
.side-nav .n{{opacity:.45;font-weight:700}}
/* ── markdown ── */
.md-h{{font-family:var(--font-display);margin:16px 0 5px}}
h3.md-h{{font-size:15px;font-weight:700}}
h4.md-h{{font-size:13.5px;font-weight:700;color:var(--ink-700)}}
.md-ul,.md-ol{{margin:5px 0 10px;padding-left:20px}}
.md-ul li,.md-ol li{{margin:3px 0;font-size:13.5px}}
.md-ol li{{padding-left:3px}}
.spec-section p{{margin:9px 0;font-size:13.5px;line-height:1.62;color:var(--ink-700)}}
.spec-section em,.md-quote em{{font-style:italic}}
.md-quote{{margin:13px 0;padding:8px 16px;border-left:3px solid var(--accent);background:var(--surface-warm);border-radius:var(--radius-sm);color:var(--ink-700)}}
.md-quote p{{margin:7px 0;font-size:13.5px;line-height:1.6}}
.md-table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
.md-table th,.md-table td{{border:1px solid var(--line);padding:7px 12px;text-align:left;vertical-align:top}}
.md-table thead tr{{background:var(--surface-warm)}}
.md-table th{{font-weight:700;color:var(--ink-900)}}
.md-table tbody tr:nth-child(even){{background:var(--surface-warm)}}
.chk{{color:var(--ink-500)}}
.chk-done{{color:var(--green)}}
code{{font-family:var(--font-mono);font-size:.84em;background:var(--accent-soft);color:var(--accent);padding:1px 5px;border-radius:5px}}
pre.code-block{{background:#1e2030;color:#c0caf5;padding:14px 16px;border-radius:var(--radius);overflow:auto;font-size:12.5px;line-height:1.5}}
pre.code-block code{{background:none;color:inherit;padding:0;font-size:inherit}}
/* ── collapsibles ── */
details.spec-section{{margin:12px 0}}
details.spec-section>summary{{cursor:pointer;font:700 13.5px/1 var(--font-display);color:var(--accent);padding:10px 0;user-select:none}}
details.spec-section>summary:hover{{text-decoration:underline}}
/* ── progress ── */
.branch-note{{font-size:12px;color:var(--ink-500);margin:-6px 0 12px}}
.prog-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:640px){{.prog-grid{{grid-template-columns:1fr}}}}
.prog-h{{font:700 11px/1 var(--font-display);letter-spacing:.07em;text-transform:uppercase;margin:0 0 6px}}
.prog-done{{color:var(--green)}}
.prog-rem{{color:var(--ink-700)}}
.prog-col .md-ul{{margin:3px 0 0;padding-left:3px;list-style:none}}
.prog-col .md-ul li{{display:flex;gap:7px;align-items:flex-start;font-size:12.5px;margin:5px 0}}
/* ── feedback form ── */
.fb label.q{{display:block;font:700 13.5px/1.3 var(--font-display);margin:15px 0 3px}}
.fb .help-text{{font-size:12px;color:var(--ink-500);margin-bottom:7px}}
.opt{{display:flex;gap:9px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius);padding:10px 12px;margin:6px 0;cursor:pointer;font-size:13px;transition:border-color .15s}}
.opt:hover{{border-color:var(--accent)}}
.opt.sel{{border-color:var(--accent);background:var(--accent-soft)}}
.opt input{{margin-top:3px;accent-color:var(--accent)}}
.verdict-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px}}
textarea{{width:100%;min-height:110px;border:1px solid var(--line);border-radius:var(--radius);padding:11px;font-family:var(--font-body);font-size:13.5px;resize:vertical;color:var(--ink-900)}}
textarea:focus{{outline:2px solid var(--accent);border-color:transparent}}
.field-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}}
@media(max-width:540px){{.field-row{{grid-template-columns:1fr}}}}
.field-row input{{width:100%;border:1px solid var(--line);border-radius:var(--radius);padding:9px 11px;font-family:var(--font-body);font-size:13.5px;color:var(--ink-900)}}
.field-row input:focus{{outline:2px solid var(--accent);border-color:transparent}}
.field-label{{font:700 12px/1 var(--font-display);margin-bottom:4px;color:var(--ink-700)}}
/* ── buttons ── */
.btn{{display:inline-flex;align-items:center;gap:7px;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-pill);padding:11px 20px;font:600 13.5px/1 var(--font-display);cursor:pointer}}
.btn:hover{{background:var(--accent-dark)}}
.btn.ghost{{background:var(--surface);color:var(--accent);border:1px solid var(--line)}}
.btn.ghost:hover{{background:var(--accent-soft)}}
/* ── receipt ── */
.receipt{{font-size:12.5px;margin-top:8px}}
.receipt.ok{{color:var(--green)}}
.receipt.err{{color:var(--red)}}
/* ── empty state ── */
.empty-state{{text-align:center;padding:60px 20px;color:var(--ink-500)}}
.empty-state h2{{font:700 20px/1.2 var(--font-display);color:var(--ink-700);margin-bottom:10px}}
/* ── footer ── */
.footer{{color:var(--ink-500);font-size:11.5px;margin-top:28px;padding-top:18px;border-top:1px solid var(--line)}}
/* ── hub progress summary ── */
.hub-progress{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0 6px}}
.hub-progress .stat{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:10px 14px;font-size:13px}}
.hub-progress .stat b{{display:block;font-size:22px;font-weight:800;color:var(--accent)}}
/* ── audit reports ── */
.audit-stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:18px 0}}
@media(max-width:700px){{.audit-stats{{grid-template-columns:1fr}}}}
.audit-stats .stat{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;text-align:center}}
.audit-stats .stat b{{display:block;font-size:28px;font-weight:800;line-height:1.1}}
.audit-stats .stat span{{font-size:12px;color:var(--ink-500);text-transform:uppercase;letter-spacing:.06em;font-weight:600}}
.stat-fixed b{{color:var(--green)}}
.stat-bug b{{color:var(--red)}}
.stat-total b{{color:var(--blue)}}
.why-box{{background:var(--blue-bg);border-left:3px solid var(--blue);border-radius:var(--radius);padding:13px 16px;font-size:13.5px;color:var(--ink-900);margin:14px 0}}
.why-box code{{background:rgba(0,0,0,.06);color:inherit}}
.audit-section-title{{font:700 14px/1.2 var(--font-display);margin:26px 0 8px;display:flex;align-items:center;gap:8px}}
.audit-section-title .n{{color:var(--ink-500);font-weight:600;font-size:12.5px}}
.audit-card{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);margin:12px 0;overflow:hidden;box-shadow:var(--shadow-sm)}}
.ac-head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px;background:var(--surface-warm);border-bottom:1px solid var(--line)}}
.ac-file{{font-family:var(--font-mono);font-size:12.5px;color:var(--ink-900)}}
.ac-line{{font-size:12px;color:var(--ink-500)}}
.ac-ref{{margin-left:auto;font-size:12px}}
.badge{{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:3px 10px;font:700 11px/1.4 var(--font-display)}}
.badge-fixed{{background:var(--green-bg);color:var(--green)}}
.badge-bug{{background:var(--red-bg);color:var(--red)}}
.badge-fine{{background:var(--blue-bg);color:var(--blue)}}
.diff-wrap{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line)}}
@media(max-width:700px){{.diff-wrap{{grid-template-columns:1fr}}}}
.diff-pane{{background:var(--surface);padding:12px 14px;min-width:0}}
.diff-pane h4{{font:700 10.5px/1 var(--font-display);letter-spacing:.07em;text-transform:uppercase;color:var(--ink-500);margin:0 0 8px}}
.diff-pane pre{{margin:0;overflow:auto;font-family:var(--font-mono);font-size:12px;line-height:1.55}}
.line{{display:block;padding:0 7px;border-radius:4px;white-space:pre}}
.line-removed{{background:var(--diff-removed-bg,rgba(220,38,38,.10));color:var(--diff-removed-ink,#b42318)}}
.line-added{{background:var(--diff-added-bg,rgba(5,150,105,.12));color:var(--diff-added-ink,#067647)}}
.line-neutral{{color:var(--ink-700)}}
.audit-explain{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid var(--line);font-size:13px;color:var(--ink-700)}}
.audit-explain .text{{flex:1;min-width:200px}}
.verdict{{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:4px 11px;font:700 11px/1.4 var(--font-display);white-space:nowrap}}
.verdict-fixed{{background:var(--green-bg);color:var(--green)}}
.verdict-todo{{background:var(--yellow-bg);color:var(--yellow)}}
.verdict-fine{{background:var(--blue-bg);color:var(--blue)}}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">&#9646;</div>
  <div class="title-block"><b>Superloop E2E Hub</b><span class="sub">superloop-e2e</span></div>
  <div class="crumbs">{crumbs_html}</div>
</div>
{body_html}
</body>
</html>"""

# ─── page renderers ────────────────────────────────────────────────────────────

def render_index(plans, theme_css):
    progress = get_progress()
    total = len(plans)
    decided = sum(1 for p in plans if get_feedback(p["id"]))
    done_count = sum(1 for pid, pr in progress.items() if pr.get("state") == "done")

    if not plans:
        body = """
<div class='wrap'>
  <div class='empty-state'>
    <h2>No plans found</h2>
    <p>Create a <code>plans/</code> directory with plan subfolders, or point the server at an existing directory:<br>
    <code>python3 scripts/serve.py --plans path/to/plans</code></p>
    <p>See <code>examples/plans/</code> for sample plans and <code>docs/plan-format.md</code> for the schema.</p>
  </div>
</div>"""
        return page_shell("Superloop E2E Hub", "Hub", body, theme_css)

    rows = []
    for p in plans:
        pid = p["id"]
        fb = get_feedback(pid) or {}
        verdict = fb.get("verdict")
        verdict_chip_html = ""
        if verdict:
            vcls, vlabel = VERDICT_CHIP.get(verdict, ("chip-none", verdict.replace("_", " ")))
            verdict_chip_html = chip(vcls, vlabel)

        pr = progress.get(pid)
        aside_html = ""
        if pr:
            state = pr.get("state", "not_started")
            pcls, plabel = PROGRESS_STATE_CHIP.get(state, ("chip-none", state))
            ndone = len(pr.get("done", []))
            nrem = len(pr.get("remaining", []))
            sub = f"{ndone} done · {nrem} remaining" if pr.get("done") else (f"{nrem} steps" if nrem else "")
            aside_html = f"<div style='margin-bottom:5px'>{chip(pcls, plabel)}</div>"
            if sub:
                aside_html += f"<div style='font-size:11px;color:var(--ink-500)'>{html.escape(sub)}</div>"
        else:
            aside_html = verdict_chip_html or chip("chip-none", "No feedback yet")

        effort_html = f"<span style='font-size:11.5px;color:var(--ink-500);margin-left:8px'>{html.escape(p['effort'])}</span>" if p.get('effort') else ""
        rows.append(f"""
<a class='index-row' href='/plan/{html.escape(pid)}'>
  <div class='num'>{html.escape(p['num'])}</div>
  <div class='body'>
    <h3>{html.escape(p['title'])}{effort_html}</h3>
    <p>{html.escape(p['tagline'] or p.get('headline') or '')}</p>
  </div>
  <div class='aside'>{aside_html}</div>
</a>""")

    audits = load_audits()
    stats_html = f"""
<div class='hub-progress'>
  <div class='stat'><b>{total}</b> Plans</div>
  <div class='stat'><b>{decided}</b> Reviewed</div>
  <div class='stat'><b>{done_count}</b> Implemented</div>
  <div class='stat'><b>{total - done_count}</b> Remaining</div>
  {f"<div class='stat'><b>{len(audits)}</b> Audits</div>" if audits else ""}
</div>"""

    audits_section = ""
    if audits:
        audit_rows = []
        for a in audits:
            fixed, bug, fine, atotal = audit_counts(a)
            sub = f"{fixed} fixed · {bug} open · {atotal} scanned"
            audit_rows.append(f"""
<a class='index-row' href='/audit/{html.escape(a['id'])}'>
  <div class='num'>&#9670;</div>
  <div class='body'>
    <h3>{html.escape(a['title'])}</h3>
    <p>{html.escape((a.get('summary') or '').strip())}</p>
  </div>
  <div class='aside'><div style='font-size:11px;color:var(--ink-500)'>{html.escape(sub)}</div></div>
</a>""")
        audits_section = (
            "<div class='eyebrow' style='margin:26px 0 4px'>Findings audits</div>"
            + "".join(audit_rows)
        )

    research_docs = load_research_docs()
    research_section = ""
    if research_docs:
        doc_rows = []
        for d in research_docs:
            doc_rows.append(f"""
<a class='index-row' href='/docs/{html.escape(d['id'])}'>
  <div class='num'>&#128218;</div>
  <div class='body'>
    <h3>{html.escape(d['title'])}</h3>
    <p>{inline_md(d['tagline'], links=False)}</p>
  </div>
  <div class='aside'><div style='font-size:11px;color:var(--ink-500)'>reference</div></div>
</a>""")
        research_section = (
            "<div class='eyebrow' style='margin:26px 0 4px'>Research &amp; References</div>"
            + "".join(doc_rows)
        )

    body = f"""
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Superloop E2E Planning · {total} plan{'s' if total!=1 else ''}</div>
    <h1 class='page-title'>Superloop E2E Hub</h1>
    <p class='lead'>Review each plan, answer the decisions, set a verdict, and submit feedback. Approved plans will be dispatched to implementation.</p>
  </div>
  {stats_html}
  {''.join(rows)}
  {audits_section}
  {research_section}
  <div class='card' style='margin-top:20px'>
    <h2>How this works</h2>
    <p style='font-size:13.5px;color:var(--ink-700)'>
      Open a plan, read it, answer the decision questions, and submit your verdict + notes.
      Feedback is written to <code>.planning-hub/feedback/&lt;id&gt;.json</code>.
      When you are done, tell Claude <em>"read the feedback"</em> and it will: read every feedback file,
      apply your decisions, create a git worktree per approved plan on a fresh branch,
      and dispatch a dedicated subagent to each — nothing merges to <code>main</code> without you.
    </p>
  </div>
  <div class='footer'>plan-review-hub · state in <code>.planning-hub/</code> · <a href='/feedback'>view raw feedback JSON</a></div>
</div>"""
    return page_shell("Plan Review Hub", "Hub", body, theme_css)


def render_plan(plan, plans, theme_css):
    pid = plan["id"]
    progress = get_progress()
    fb = get_feedback(pid) or {}

    # side nav
    nav_items = []
    for p in plans:
        active = " active" if p["id"] == pid else ""
        nav_items.append(
            f"<a class='{active}' href='/plan/{html.escape(p['id'])}'>"
            f"<span>{html.escape(p['title'])}</span>"
            f"<span class='n'>{html.escape(p['num'])}</span></a>"
        )

    # decision HTML
    dec_blocks = []
    for d in plan.get("decisions", []):
        saved = (fb.get("decisions") or {}).get(d["id"], d.get("default"))
        opts_html = []
        for o in d["options"]:
            opt_val = o.get("v") or o.get("value", "")
            is_sel = (saved == opt_val)
            sel_cls = " sel" if is_sel else ""
            checked = "checked" if is_sel else ""
            rec_badge = " <span style='font-size:10.5px;color:var(--green);font-weight:700'>recommended</span>" if o.get("recommended") else ""
            dec_id = html.escape(d["id"])
            opt_v = html.escape(opt_val)
            opts_html.append(
                f"<label class='opt{sel_cls}'>"
                f"<input type='radio' name='dec__{dec_id}' value='{opt_v}' {checked}>"
                f"<span>{html.escape(o['label'])}{rec_badge}</span></label>"
            )
        d_question = d.get("q") or d.get("question", "")
        dec_blocks.append(
            f"<label class='q'>{html.escape(d_question)}</label>"
            f"<div class='help-text'>{html.escape(d.get('help',''))}</div>"
            + "".join(opts_html)
        )

    # verdict radios
    verdicts = [
        ("approve",              "Approve — build it"),
        ("approve_with_changes", "Approve with changes (see notes)"),
        ("hold",                 "Hold — discuss first"),
        ("reject",               "Reject — do not build"),
    ]
    saved_v = fb.get("verdict")
    verdict_html = "".join(
        f"<label class='opt{' sel' if saved_v==v else ''}'>"
        f"<input type='radio' name='verdict' value='{v}' {'checked' if saved_v==v else ''}>"
        f"<span>{html.escape(lbl)}</span></label>"
        for v, lbl in verdicts
    )

    # rendered docs
    doc_sections = []
    for doc_file in plan.get("docs", []):
        raw = read_plan_doc(plan, doc_file)
        if not raw:
            continue
        section_name = doc_file.replace(".md", "").replace("-", " ").title()
        rendered = md_to_html(raw)
        # first doc open by default; rest collapsed
        open_attr = " open" if not doc_sections else ""
        doc_sections.append(
            f"<details class='spec-section card'{open_attr}>"
            f"<summary>{html.escape(section_name)}</summary>"
            f"<div style='margin-top:12px'>{rendered}</div>"
            f"</details>"
        )

    # metadata chips
    meta_items = []
    if plan.get("effort"):
        meta_items.append(f"<div class='kv'>Effort<b>{html.escape(plan['effort'])}</b></div>")
    if plan.get("risk"):
        meta_items.append(f"<div class='kv'>Risk<b>{html.escape(plan['risk'])}</b></div>")
    if plan.get("branch"):
        meta_items.append(f"<div class='kv'>Branch<b><code>{html.escape(plan['branch'])}</code></b></div>")
    meta_items.append(f"<div class='kv'>Plan ID<b><code>{html.escape(pid)}</code></b></div>")
    meta_html = f"<div class='meta'>{''.join(meta_items)}</div>" if meta_items else ""

    headline_html = ""
    if plan.get("headline"):
        headline_html = f"<div class='card'><h2>Overview</h2><div class='headline-box'>{plan['headline']}</div></div>"

    progress_card = render_progress_card(pid, progress)

    # audits linked to this plan
    linked_audits = [a for a in load_audits() if a.get("planId") == pid]
    audits_card = ""
    if linked_audits:
        links = []
        for a in linked_audits:
            fixed, bug, fine, atotal = audit_counts(a)
            links.append(
                f"<li><a href='/audit/{html.escape(a['id'])}'>{html.escape(a['title'])}</a> "
                f"<span style='color:var(--ink-500);font-size:12px'>— {fixed} fixed · {bug} open · {atotal} scanned</span></li>"
            )
        audits_card = (
            "<div class='card'><h2>Findings audits</h2>"
            f"<ul class='md-ul'>{''.join(links)}</ul></div>"
        )

    saved_notes = html.escape(fb.get("notes", ""))
    saved_priority = html.escape(str(fb.get("priority", "")))
    saved_assignee = html.escape(fb.get("assignee", ""))

    body = f"""
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Plan {html.escape(plan['num'])}</div>
    <h1 class='page-title'>{html.escape(plan['title'])}</h1>
    <p class='lead'>{html.escape(plan['tagline'])}</p>
    {meta_html}
  </div>
  <div class='two-col'>
    <div class='main-col'>
      {headline_html}
      {progress_card}
      {audits_card}
      {''.join(doc_sections)}
      <div class='card fb'>
        <h2>Your feedback</h2>
        <form id='fbform'>
          <input type='hidden' name='planId' value='{html.escape(pid)}'>
          <input type='hidden' name='title' value='{html.escape(plan['title'])}'>
          <label class='q'>Verdict</label>
          <div class='verdict-grid'>{verdict_html}</div>
          {''.join(dec_blocks)}
          <label class='q' style='margin-top:18px'>Notes</label>
          <textarea name='notes' placeholder='Guidance, caveats, decision rationale…'>{saved_notes}</textarea>
          <div class='field-row'>
            <div>
              <div class='field-label'>Priority</div>
              <input type='text' name='priority' value='{saved_priority}' placeholder='e.g. high, 1, urgent'>
            </div>
            <div>
              <div class='field-label'>Assignee</div>
              <input type='text' name='assignee' value='{saved_assignee}' placeholder='e.g. alice'>
            </div>
          </div>
          <div style='margin-top:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap'>
            <button class='btn' type='submit'>Submit feedback</button>
            <a class='btn ghost' href='/'>All plans</a>
          </div>
          <div id='receipt' class='receipt'></div>
        </form>
      </div>
    </div>
    <div class='sticky-side'>
      <div class='card'>
        <h2 style='font-size:13px;margin-bottom:8px'>All plans</h2>
        <div class='side-nav'>{''.join(nav_items)}</div>
      </div>
    </div>
  </div>
  <div class='footer'>plan-review-hub · <a href='/'>hub</a> · <a href='/feedback'>feedback JSON</a></div>
</div>
<script>
  document.querySelectorAll('.opt input').forEach(i => i.addEventListener('change', e => {{
    const name = e.target.name;
    if (e.target.type === 'radio') {{
      document.querySelectorAll('input[name="' + name + '"]').forEach(x => x.closest('.opt').classList.remove('sel'));
    }}
    e.target.closest('.opt').classList.toggle('sel', e.target.checked);
  }}));
  document.getElementById('fbform').addEventListener('submit', async (e) => {{
    e.preventDefault();
    const f = e.target;
    const data = {{
      planId:    f.planId.value,
      title:     f.title.value,
      verdict:   (f.querySelector('input[name=verdict]:checked') || {{}}).value || null,
      decisions: {{}},
      notes:     f.notes.value,
      priority:  f.priority.value,
      assignee:  f.assignee.value,
      submittedAt: new Date().toISOString(),
      ua: navigator.userAgent
    }};
    f.querySelectorAll('input[type=radio]:checked').forEach(r => {{
      if (r.name.startsWith('dec__')) data.decisions[r.name.slice(5)] = r.value;
    }});
    const receipt = document.getElementById('receipt');
    try {{
      const resp = await fetch('/submit', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(data)
      }});
      const j = await resp.json();
      receipt.className = j.ok ? 'receipt ok' : 'receipt err';
      receipt.textContent = j.ok
        ? '\\u2713 Saved — verdict: ' + (data.verdict || 'none') + '. You can revise and resubmit anytime.'
        : 'Error: ' + j.error;
    }} catch (err) {{
      receipt.className = 'receipt err';
      receipt.textContent = 'Network error: ' + err;
    }}
  }});
</script>"""

    crumbs = f"<a href='/'>Hub</a> &nbsp;/&nbsp; Plan {html.escape(plan['num'])}"
    return page_shell(f"{plan['title']} — Plan Review Hub", crumbs, body, theme_css)


AUDIT_BADGE = {
    "fixed": ("badge-fixed", "Fixed"),
    "bug":   ("badge-bug",   "Bug"),
    "fine":  ("badge-fine",  "Fine"),
}
AUDIT_SECTIONS = [
    ("fixed", "&#9989; Fixed"),
    ("bug",   "&#9888;&#65039; Needs fixing"),
    ("fine",  "&#128064; Reviewed &mdash; confirmed fine"),
]


def _render_diff_lines(lines, default_kind):
    """Render code lines for one diff pane. A line is a string (uses default_kind)
    or a dict {"text":..., "kind": "removed"|"added"|"neutral"}."""
    out = []
    for ln in lines or []:
        if isinstance(ln, dict):
            text = ln.get("text", "")
            kind = ln.get("kind", default_kind)
        else:
            text, kind = ln, default_kind
        if kind not in ("removed", "added", "neutral"):
            kind = default_kind
        out.append(f"<span class='line line-{kind}'>{html.escape(text)}</span>")
    return "".join(out) or "<span class='line line-neutral'></span>"


def _render_finding(f):
    status = f.get("status", "bug")
    badge_cls, badge_label = AUDIT_BADGE.get(status, ("badge-bug", status))
    file_html = html.escape(f.get("file", "(unknown file)"))
    line_html = f"<span class='ac-line'>line {html.escape(str(f.get('line')))}</span>" if f.get("line") is not None else ""
    ref = f.get("ref")
    ref_html = f"<span class='ac-ref'><a href='{html.escape(ref)}' target='_blank' rel='noopener'>reference &#8599;</a></span>" if ref else ""

    before_html = _render_diff_lines(f.get("before"), "removed")
    after_html = _render_diff_lines(f.get("after"), "added")

    # verdict pill: explicit text wins, else derived from status (+ commit)
    if status == "fixed":
        commit = f.get("commit")
        vtext = f.get("verdict") or (f"Fixed in {commit}" if commit else "Fixed")
        vcls = "verdict-fixed"
    elif status == "fine":
        vtext = f.get("verdict") or "No change needed"
        vcls = "verdict-fine"
    else:
        vtext = f.get("verdict") or "To fix"
        vcls = "verdict-todo"

    explanation = html.escape(f.get("explanation", ""))
    return f"""
<div class='audit-card'>
  <div class='ac-head'>
    <span class='badge {badge_cls}'>{badge_label}</span>
    <span class='ac-file'>{file_html}</span>
    {line_html}
    {ref_html}
  </div>
  <div class='diff-wrap'>
    <div class='diff-pane'><h4>Before</h4><pre>{before_html}</pre></div>
    <div class='diff-pane'><h4>After</h4><pre>{after_html}</pre></div>
  </div>
  <div class='audit-explain'>
    <span class='text'>{explanation}</span>
    <span class='verdict {vcls}'>{html.escape(vtext)}</span>
  </div>
</div>"""


def render_audit(audit, theme_css):
    aid = audit["id"]
    fixed, bug, fine, total = audit_counts(audit)

    pattern = audit.get("pattern") or {}
    pat_html = ""
    if pattern.get("buggy") or pattern.get("correct"):
        parts = []
        if pattern.get("buggy"):
            parts.append(f"buggy <code>{html.escape(pattern['buggy'])}</code>")
        if pattern.get("correct"):
            parts.append(f"correct <code>{html.escape(pattern['correct'])}</code>")
        pat_html = " &rarr; ".join(parts)

    why_html = f"<div class='why-box'>{audit['why']}</div>" if audit.get("why") else ""

    stats_html = f"""
<div class='audit-stats'>
  <div class='stat stat-fixed'><b>{fixed}</b><span>Fixed</span></div>
  <div class='stat stat-bug'><b>{bug}</b><span>Needs fixing</span></div>
  <div class='stat stat-total'><b>{total}</b><span>Total scanned</span></div>
</div>"""

    # group findings into sections by status, preserving file order within each
    by_status = {"fixed": [], "bug": [], "fine": []}
    for f in audit.get("findings", []):
        by_status.get(f.get("status", "bug"), by_status["bug"]).append(f)

    sections_html = []
    for status, label in AUDIT_SECTIONS:
        items = by_status.get(status, [])
        if not items:
            continue
        cards = "".join(_render_finding(f) for f in items)
        sections_html.append(
            f"<div class='audit-section-title'>{label} <span class='n'>{len(items)}</span></div>{cards}"
        )

    today = datetime.date.today().isoformat()
    summary = html.escape(audit.get("summary", "")) or f"{fixed} fixed · {bug} open · {total} scanned"

    plan_link = ""
    if audit.get("planId"):
        plan_link = f"<div class='kv'>Plan<b><a href='/plan/{html.escape(audit['planId'])}'>{html.escape(audit['planId'])}</a></b></div>"

    body = f"""
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Findings audit</div>
    <h1 class='page-title'>{html.escape(audit['title'])}</h1>
    {f"<p class='lead'>{pat_html}</p>" if pat_html else ""}
    <div class='meta'>
      <div class='kv'>Audit ID<b><code>{html.escape(aid)}</code></b></div>
      {plan_link}
    </div>
  </div>
  {stats_html}
  {why_html}
  {''.join(sections_html) or "<div class='empty-state'><h2>No findings</h2><p>This audit has no findings yet.</p></div>"}
  <div class='footer'>Generated {today} · audit <code>{html.escape(aid)}</code> · {summary}</div>
</div>"""

    crumbs = f"<a href='/'>Hub</a> &nbsp;/&nbsp; Audit"
    return page_shell(f"{audit['title']} — Findings audit", crumbs, body, theme_css)

# ─── token / cookie auth ───────────────────────────────────────────────────────

COOKIE_NAME = "prh_token"


def _check_auth(handler):
    """Return True if the request is authorised (or no token configured)."""
    tok = CFG.get("token")
    if not tok:
        return True
    # check cookie
    cookie_header = handler.headers.get("Cookie", "")
    if cookie_header:
        c = http.cookies.SimpleCookie(cookie_header)
        if COOKIE_NAME in c and c[COOKIE_NAME].value == tok:
            return True
    # check ?token= query param
    parsed = urllib.parse.urlparse(handler.path)
    params = urllib.parse.parse_qs(parsed.query)
    if params.get("token", [""])[0] == tok:
        return True
    return False


def _set_token_cookie(handler, tok):
    """Return a Set-Cookie header value for the token."""
    return f"{COOKIE_NAME}={tok}; Path=/; HttpOnly; SameSite=Strict"

# ─── HTTP handler ──────────────────────────────────────────────────────────────

class HubHandler(http.server.BaseHTTPRequestHandler):

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _401(self):
        self._send(401, "401 Unauthorised — supply ?token=<secret>", "text/plain")

    def _404(self, msg="404 Not Found"):
        self._send(404, f"<div style='font-family:sans-serif;padding:40px'><h1>404</h1><p>{html.escape(msg)}</p><a href='/'>Back to hub</a></div>")

    def do_GET(self):
        # reload plans on every request so file changes are picked up without restart
        plans = load_plans()
        plan_by_id = {p["id"]: p for p in plans}
        theme_css = load_theme_css()

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = urllib.parse.parse_qs(parsed.query)

        # auth gate
        if not _check_auth(self):
            return self._401()

        extra_headers = {}
        # set cookie if token param was supplied
        tok = CFG.get("token")
        if tok and params.get("token", [""])[0] == tok:
            extra_headers["Set-Cookie"] = _set_token_cookie(self, tok)

        if path in ("", "/"):
            return self._send(200, render_index(plans, theme_css), extra_headers=extra_headers)

        if path == "/healthz":
            return self._send(200, '{"status":"ok"}', "application/json", extra_headers=extra_headers)

        if path == "/feedback":
            data = {p["id"]: get_feedback(p["id"]) for p in plans}
            return self._send(200, json.dumps(data, indent=2), "application/json", extra_headers=extra_headers)

        if path == "/audits":
            data = {a["id"]: a for a in load_audits()}
            return self._send(200, json.dumps(data, indent=2), "application/json", extra_headers=extra_headers)

        if path.startswith("/docs/"):
            did = path[len("/docs/"):].strip("/")
            doc = get_research_doc(did)
            if not doc:
                return self._404(f"Unknown research doc '{did}'")
            return self._send(200, render_doc(doc, theme_css), extra_headers=extra_headers)

        if path.startswith("/audit/"):
            aid = path[len("/audit/"):].strip("/")
            audit = get_audit(aid)
            if not audit:
                return self._404(f"Unknown audit '{aid}'")
            return self._send(200, render_audit(audit, theme_css), extra_headers=extra_headers)

        if path.startswith("/plan/"):
            pid = path[len("/plan/"):].strip("/")
            plan = plan_by_id.get(pid)
            if not plan:
                return self._404(f"Unknown plan '{pid}'")
            return self._send(200, render_plan(plan, plans, theme_css), extra_headers=extra_headers)

        if path.startswith("/assets/"):
            return self._serve_asset(path[len("/assets/"):], extra_headers)

        return self._404()

    def _serve_asset(self, rel, extra_headers=None):
        # prevent path traversal
        rel = re.sub(r"\.\./", "", rel).lstrip("/")
        full = os.path.join(REPO, "assets", rel)
        if not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = "text/css; charset=utf-8" if full.endswith(".css") else "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not _check_auth(self):
            return self._401()

        if path != "/submit":
            return self._send(404, json.dumps({"ok": False, "error": "not found"}), "application/json")

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
            pid = data.get("planId")
            if not pid:
                raise ValueError("missing planId")
            # validate plan exists
            plans = load_plans()
            plan_by_id = {p["id"]: p for p in plans}
            if pid not in plan_by_id:
                raise ValueError(f"unknown planId '{pid}'")
        except Exception as e:
            return self._send(400, json.dumps({"ok": False, "error": str(e)}), "application/json")

        out_path = os.path.join(feedback_dir(), f"{pid}.json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  [feedback] {pid}: verdict={data.get('verdict')} priority={data.get('priority')} assignee={data.get('assignee')}")
        return self._send(200, json.dumps({"ok": True, "planId": pid}), "application/json")

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "GET /assets" not in msg and "GET /healthz" not in msg:
            super().log_message(fmt, *args)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="plan-review-hub server (Python)")
    p.add_argument("--port",   type=int, default=None)
    p.add_argument("--host",   default=None)
    p.add_argument("--plans",  dest="plansDir", default=None)
    p.add_argument("--source", choices=["auto", "generic", "openspec"], default=None)
    p.add_argument("--theme",  dest="themePath", default=None)
    p.add_argument("--state",  dest="stateDir", default=None)
    p.add_argument("--audits", dest="auditsDir", default=None)
    p.add_argument("--token",  default=None)
    return p.parse_args()


def main():
    args = parse_args()
    # CLI flags override everything
    for attr, key in [("port","port"),("host","host"),("plansDir","plansDir"),
                      ("source","source"),("themePath","themePath"),
                      ("stateDir","stateDir"),("auditsDir","auditsDir"),("token","token")]:
        v = getattr(args, attr)
        if v is not None:
            CFG[key] = v

    host = CFG["host"]
    port = CFG["port"]

    # ensure state dir
    os.makedirs(state_dir(), exist_ok=True)
    os.makedirs(feedback_dir(), exist_ok=True)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((host, port), HubHandler) as httpd:
        plans = load_plans()
        audits = load_audits()
        ips = local_ips()
        print(f"\nplan-review-hub running on {host}:{port}")
        print(f"  source: {CFG['source']}  plans: {_abs(CFG['plansDir'])}  state: {state_dir()}")
        if CFG.get("token"):
            print(f"  token:  set (required)")
        else:
            print(f"  token:  not set (open on LAN — see security note in README)")
        print()
        for ip in ips:
            print(f"  HUB    http://{ip}:{port}/")
            for p in plans:
                print(f"    {p['num']}  http://{ip}:{port}/plan/{urllib.parse.quote(p['id'])}")
            for a in audits:
                print(f"    audit  http://{ip}:{port}/audit/{urllib.parse.quote(a['id'])}")
        if not plans:
            print(f"  (no plans found — see examples/plans/ for sample plans)")
        print()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
