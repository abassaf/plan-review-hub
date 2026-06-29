#!/usr/bin/env node
/**
 * plan-review-hub — Node built-ins-only server (no npm dependencies).
 * Requires Node 18+ (http, fs, path, url, os built-ins; no ESM bundler needed).
 *
 * Functionally equivalent to scripts/serve.py.
 *
 * Usage:
 *   node scripts/serve.mjs [--port 8770] [--host 0.0.0.0]
 *              [--plans plans] [--source auto|generic|openspec]
 *              [--theme assets/themes/default.css]
 *              [--state .planning-hub] [--token SECRET]
 *
 * Environment variables: PLAN_HUB_PORT, PLAN_HUB_HOST, PLAN_HUB_PLANS_DIR,
 *                        PLAN_HUB_SOURCE, PLAN_HUB_THEME, PLAN_HUB_STATE_DIR,
 *                        PLAN_HUB_TOKEN
 */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO = path.resolve(__dirname, "..");

// ─── configuration ─────────────────────────────────────────────────────────────

function loadConfig() {
  const defaults = {
    port:      8770,
    host:      "0.0.0.0",
    plansDir:  "plans",
    source:    "auto",
    themePath: "assets/themes/default.css",
    stateDir:  ".planning-hub",
    auditsDir: null,
    token:     null,
  };
  // config file
  const cfgPath = path.join(REPO, "plan-review-hub.config.json");
  if (fs.existsSync(cfgPath)) {
    try {
      const file = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
      for (const k of Object.keys(defaults)) {
        if (k in file) defaults[k] = file[k];
      }
    } catch (_) {}
  }
  // env var overrides
  const envMap = {
    PLAN_HUB_PORT:      ["port",      Number],
    PLAN_HUB_HOST:      ["host",      String],
    PLAN_HUB_PLANS_DIR: ["plansDir",  String],
    PLAN_HUB_SOURCE:    ["source",    String],
    PLAN_HUB_THEME:     ["themePath", String],
    PLAN_HUB_STATE_DIR: ["stateDir",  String],
    PLAN_HUB_AUDITS_DIR:["auditsDir", String],
    PLAN_HUB_TOKEN:     ["token",     String],
  };
  for (const [envKey, [cfgKey, cast]] of Object.entries(envMap)) {
    const v = process.env[envKey];
    if (v != null) defaults[cfgKey] = cast(v);
  }
  return defaults;
}

const CFG = loadConfig();

// CLI flags (applied in main())
function applyCLIArgs() {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i];
    const val  = argv[i + 1];
    if (!val) continue;
    const flagMap = {
      "--port":   ["port",      Number],
      "--host":   ["host",      String],
      "--plans":  ["plansDir",  String],
      "--source": ["source",    String],
      "--theme":  ["themePath", String],
      "--state":  ["stateDir",  String],
      "--audits": ["auditsDir", String],
      "--token":  ["token",     String],
    };
    if (flag in flagMap) {
      const [k, cast] = flagMap[flag];
      CFG[k] = cast(val);
    }
  }
}

// ─── helpers ───────────────────────────────────────────────────────────────────

function abs(p) {
  return path.isAbsolute(p) ? p : path.join(REPO, p);
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stateDir() { return abs(CFG.stateDir); }
function feedbackDir() {
  const d = path.join(stateDir(), "feedback");
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function getFeedback(planId) {
  const p = path.join(feedbackDir(), `${planId}.json`);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch (_) { return null; }
}

function getProgress() {
  const p = path.join(stateDir(), "progress.json");
  if (!fs.existsSync(p)) return {};
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch (_) { return {}; }
}

// ─── audit loading ───────────────────────────────────────────────────────────────
// A "findings audit" renders cross-file code findings (the same bug/anti-pattern
// repeated across many files) as before/after diffs with a per-finding status.
// Audits load from <auditsDir> (default <stateDir>/audits); an audit may name a
// planId to link it to a plan.

function auditsDir() {
  return CFG.auditsDir ? abs(CFG.auditsDir) : path.join(stateDir(), "audits");
}

function normaliseAudit(a, fallbackId) {
  a.id       ??= fallbackId;
  a.title    ??= a.id.replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  a.planId   ??= null;
  a.pattern  ??= {};
  a.why      ??= "";
  a.summary  ??= "";
  a.findings ??= [];
  return a;
}

function loadAudits() {
  const d = auditsDir();
  if (!fs.existsSync(d)) return [];
  const audits = [];
  for (const name of fs.readdirSync(d).sort()) {
    if (!name.endsWith(".json")) continue;
    let a;
    try { a = JSON.parse(fs.readFileSync(path.join(d, name), "utf8")); } catch (_) { continue; }
    if (typeof a !== "object" || a === null || Array.isArray(a)) continue;
    audits.push(normaliseAudit(a, name.slice(0, -".json".length)));
  }
  return audits;
}

function getAudit(auditId) {
  return loadAudits().find(a => a.id === auditId) || null;
}

function auditCounts(audit) {
  let fixed = 0, bug = 0, fine = 0;
  for (const f of audit.findings || []) {
    const st = f.status || "bug";
    if (st === "fixed") fixed++;
    else if (st === "fine") fine++;
    else bug++;
  }
  return { fixed, bug, fine, total: (audit.findings || []).length };
}

function localIPs() {
  const ifaces = os.networkInterfaces();
  const ips = [];
  for (const list of Object.values(ifaces)) {
    for (const iface of list) {
      if (iface.family === "IPv4" && !iface.internal) {
        ips.push(iface.address);
      }
    }
  }
  return ips.length ? ips : ["127.0.0.1"];
}

function loadThemeCSS() {
  const tp = abs(CFG.themePath);
  if (fs.existsSync(tp)) return fs.readFileSync(tp, "utf8");
  return `
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
}`;
}

// ─── plan loading ───────────────────────────────────────────────────────────────

function inferTitleTagline(text) {
  let title = "", tagline = "";
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].trim().match(/^#\s+(.+)$/);
    if (m) {
      title = m[1].trim();
      for (let j = i + 1; j < lines.length; j++) {
        const rest = lines[j].trim();
        if (rest && !rest.startsWith("#")) { tagline = rest; break; }
      }
      break;
    }
  }
  return [title || "Untitled plan", tagline];
}

function loadGeneric(plansDir) {
  if (!fs.existsSync(plansDir)) return [];
  const plans = [];
  const entries = fs.readdirSync(plansDir).sort();
  for (const name of entries) {
    const pdir = path.join(plansDir, name);
    const pjson = path.join(pdir, "plan.json");
    if (!fs.statSync(pdir).isDirectory() || !fs.existsSync(pjson)) continue;
    let p;
    try { p = JSON.parse(fs.readFileSync(pjson, "utf8")); } catch (_) { continue; }
    p.id       ??= name;
    p.num      ??= String(plans.length + 1).padStart(2, "0");
    p.title    ??= name.replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    p.tagline  ??= "";
    p.branch   ??= "";
    p.effort   ??= "";
    p.risk     ??= "";
    p.headline ??= "";
    p.docs     ??= [];
    p.decisions ??= [];
    p._dir = pdir;
    plans.push(p);
  }
  return plans;
}

function loadOpenSpec(changesDir) {
  if (!fs.existsSync(changesDir)) return [];
  const plans = [];
  const entries = fs.readdirSync(changesDir).sort();
  for (const name of entries) {
    const cdir = path.join(changesDir, name);
    if (!fs.statSync(cdir).isDirectory()) continue;
    let p = {};
    const pjson = path.join(cdir, "plan.json");
    if (fs.existsSync(pjson)) {
      try { p = JSON.parse(fs.readFileSync(pjson, "utf8")); } catch (_) { p = {}; }
    }
    if (!p.title || !p.tagline) {
      const propPath = path.join(cdir, "proposal.md");
      const text = fs.existsSync(propPath) ? fs.readFileSync(propPath, "utf8") : "";
      const [t, tg] = inferTitleTagline(text);
      p.title   ??= t;
      p.tagline ??= tg;
    }
    p.id        ??= name;
    p.num       ??= String(plans.length + 1).padStart(2, "0");
    p.branch    ??= "";
    p.effort    ??= "";
    p.risk      ??= "";
    p.headline  ??= "";
    p.decisions ??= [];
    if (!p.docs) {
      p.docs = ["proposal.md","design.md","tasks.md"]
        .filter(d => fs.existsSync(path.join(cdir, d)));
    }
    p._dir = cdir;
    plans.push(p);
  }
  return plans;
}

function loadPlans() {
  const source    = CFG.source;
  const plansDir  = abs(CFG.plansDir);
  const openspecDir = path.join(REPO, "openspec", "changes");

  if (source === "generic") return loadGeneric(plansDir);
  if (source === "openspec") return loadOpenSpec(openspecDir);
  // auto
  const generic = loadGeneric(plansDir);
  if (generic.length) return generic;
  if (fs.existsSync(openspecDir)) return loadOpenSpec(openspecDir);
  return [];
}

// ─── markdown renderer ──────────────────────────────────────────────────────────

function mdToHtml(text) {
  const out = [];
  let inUl = false, inCode = false;

  function inline(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    return s;
  }

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^```/.test(line)) {
      inCode = !inCode;
      if (inCode) {
        if (inUl) { out.push("</ul>"); inUl = false; }
        out.push("<pre class='code-block'><code>");
      } else {
        out.push("</code></pre>");
      }
      continue;
    }
    if (inCode) { out.push(esc(raw)); continue; }
    // headings
    const hm = line.match(/^(#{1,4})\s+(.+)$/);
    if (hm) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      const lvl = Math.min(hm[1].length + 2, 6);
      out.push(`<h${lvl} class='md-h'>${inline(hm[2])}</h${lvl}>`);
      continue;
    }
    // list item
    const lm = line.match(/^\s*[-*]\s+(.*)$/);
    if (lm) {
      if (!inUl) { out.push("<ul class='md-ul'>"); inUl = true; }
      let rendered = inline(lm[1]);
      // checkboxes (after esc — inject span unsafely on purpose)
      rendered = rendered.replace(
        /^\[([xX ])\]\s*/,
        (_, c) => c === " "
          ? "<span class='chk'>&#9744;</span> "
          : "<span class='chk chk-done'>&#9745;</span> "
      );
      out.push(`<li>${rendered}</li>`);
      continue;
    }
    // blank
    if (!line.trim()) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      continue;
    }
    // paragraph
    if (inUl) { out.push("</ul>"); inUl = false; }
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inUl) out.push("</ul>");
  return out.join("\n");
}

function readPlanDoc(plan, filename) {
  const pdir = plan._dir;
  if (!pdir) return "";
  const fp = path.join(pdir, filename);
  if (!fs.existsSync(fp)) return "";
  return fs.readFileSync(fp, "utf8");
}

// ─── HTML components ────────────────────────────────────────────────────────────

const PROGRESS_CHIP = {
  done:        ["chip-done",        "Done"],
  in_progress: ["chip-in-progress", "In progress"],
  not_started: ["chip-none",        "Not started"],
};
const VERDICT_CHIP = {
  approve:              ["chip-approve", "Approve"],
  approve_with_changes: ["chip-awc",     "Approve with changes"],
  hold:                 ["chip-hold",    "Hold"],
  reject:               ["chip-reject",  "Reject"],
};

function chip(cls, label) {
  return `<span class='chip ${esc(cls)}'>${esc(label)}</span>`;
}

function renderProgressCard(planId, progress) {
  const pr = progress[planId];
  if (!pr) return "";
  const state = pr.state || "not_started";
  const [chipCls, chipLabel] = PROGRESS_CHIP[state] || ["chip-none", state];
  const done = (pr.done || []).map(x => `<li><span class='chk chk-done'>&#9745;</span> ${esc(x)}</li>`).join("");
  const rem  = (pr.remaining || []).map(x => `<li><span class='chk'>&#9744;</span> ${esc(x)}</li>`).join("");
  const branchNote = pr.branch ? `<div class='branch-note'>Branch <code>${esc(pr.branch)}</code></div>` : "";
  const doneCol = done ? `<div class='prog-col'><div class='prog-h prog-done'>Completed</div><ul class='md-ul'>${done}</ul></div>` : "";
  const remCol  = rem  ? `<div class='prog-col'><div class='prog-h prog-rem'>Remaining</div><ul class='md-ul'>${rem}</ul></div>`  : "";
  return `
<div class='card'>
  <h2>Implementation progress ${chip(chipCls, chipLabel)}</h2>
  ${branchNote}
  <div class='prog-grid'>${doneCol}${remCol}</div>
</div>`;
}

function pageShell(title, crumbsHtml, bodyHtml, themeCSS) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>
${themeCSS}
/* ── layout ── */
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink-900);font-family:var(--font-body);line-height:1.55}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.topbar{background:var(--ink-900);color:#fff;padding:13px 22px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:20}
.topbar .logo{width:28px;height:28px;border-radius:var(--radius-sm);background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:#fff;flex-shrink:0}
.topbar .title-block b{font-size:15px}
.topbar .sub{color:#9ca3af;font-size:12px;margin-left:6px}
.topbar .crumbs{margin-left:auto;font-size:12.5px;color:#9ca3af}
.topbar .crumbs a{color:#d1d5db}
.wrap{max-width:1100px;margin:0 auto;padding:0 22px 80px}
.hero{padding:26px 0 10px}
.eyebrow{font:600 11px/1 var(--font-display);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
h1.page-title{font:700 28px/1.15 var(--font-display);letter-spacing:-.01em;margin:6px 0 6px}
.lead{color:var(--ink-700);font-size:14.5px;max-width:720px;margin:0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:20px 22px;margin:14px 0;box-shadow:var(--shadow-sm)}
.card h2{font:700 17px/1.2 var(--font-display);margin:0 0 10px}
.chip{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:3px 9px;font:600 11px/1.4 var(--font-display)}
.chip-none{background:var(--line);color:var(--ink-700)}
.chip-done{background:var(--green-bg);color:var(--green)}
.chip-in-progress{background:var(--blue-bg);color:var(--blue)}
.chip-approve{background:var(--green-bg);color:var(--green)}
.chip-awc{background:var(--yellow-bg);color:var(--yellow)}
.chip-hold{background:var(--blue-bg);color:var(--blue)}
.chip-reject{background:var(--red-bg);color:var(--red)}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}
.kv{background:var(--accent-soft);border-radius:var(--radius);padding:7px 11px;font-size:12px;color:var(--ink-700)}
.kv b{display:block;color:var(--ink-900);font-size:13px}
.headline-box{background:var(--surface-warm);border:1px solid var(--line-2);border-radius:var(--radius);padding:13px 15px;font-size:13.5px}
.index-row{display:flex;gap:14px;align-items:center;padding:16px 18px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);margin:10px 0;text-decoration:none;color:inherit;transition:border-color .15s}
.index-row:hover{border-color:var(--accent);text-decoration:none}
.index-row .num{font:800 20px/1 var(--font-display);color:var(--accent);opacity:.35;width:34px;flex-shrink:0}
.index-row .body{flex:1}
.index-row .body h3{margin:0 0 2px;font:700 15px/1.2 var(--font-display)}
.index-row .body p{margin:0;color:var(--ink-700);font-size:13px}
.index-row .aside{text-align:right;min-width:130px;flex-shrink:0}
.two-col{display:grid;grid-template-columns:1fr 260px;gap:22px;align-items:start}
@media(max-width:860px){.two-col{grid-template-columns:1fr}}
.sticky-side{position:sticky;top:60px}
.side-nav a{display:flex;justify-content:space-between;align-items:center;padding:9px 11px;border-radius:var(--radius);color:var(--ink-900);font-size:12.5px;font-weight:600;text-decoration:none}
.side-nav a:hover{background:var(--accent-soft);text-decoration:none}
.side-nav a.active{background:var(--accent);color:#fff}
.side-nav .n{opacity:.45;font-weight:700}
.md-h{font-family:var(--font-display);margin:16px 0 5px}
h3.md-h{font-size:15px;font-weight:700}
h4.md-h{font-size:13.5px;font-weight:700;color:var(--ink-700)}
.md-ul{margin:5px 0 10px;padding-left:18px}
.md-ul li{margin:3px 0;font-size:13.5px}
.chk{color:var(--ink-500)}
.chk-done{color:var(--green)}
code{font-family:var(--font-mono);font-size:.84em;background:var(--accent-soft);color:var(--accent);padding:1px 5px;border-radius:5px}
pre.code-block{background:#1e2030;color:#c0caf5;padding:14px 16px;border-radius:var(--radius);overflow:auto;font-size:12.5px;line-height:1.5}
pre.code-block code{background:none;color:inherit;padding:0;font-size:inherit}
details.spec-section{margin:12px 0}
details.spec-section>summary{cursor:pointer;font:700 13.5px/1 var(--font-display);color:var(--accent);padding:10px 0;user-select:none}
details.spec-section>summary:hover{text-decoration:underline}
.branch-note{font-size:12px;color:var(--ink-500);margin:-6px 0 12px}
.prog-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:640px){.prog-grid{grid-template-columns:1fr}}
.prog-h{font:700 11px/1 var(--font-display);letter-spacing:.07em;text-transform:uppercase;margin:0 0 6px}
.prog-done{color:var(--green)}
.prog-rem{color:var(--ink-700)}
.prog-col .md-ul{margin:3px 0 0;padding-left:3px;list-style:none}
.prog-col .md-ul li{display:flex;gap:7px;align-items:flex-start;font-size:12.5px;margin:5px 0}
.fb label.q{display:block;font:700 13.5px/1.3 var(--font-display);margin:15px 0 3px}
.fb .help-text{font-size:12px;color:var(--ink-500);margin-bottom:7px}
.opt{display:flex;gap:9px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius);padding:10px 12px;margin:6px 0;cursor:pointer;font-size:13px;transition:border-color .15s}
.opt:hover{border-color:var(--accent)}
.opt.sel{border-color:var(--accent);background:var(--accent-soft)}
.opt input{margin-top:3px;accent-color:var(--accent)}
.verdict-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
textarea{width:100%;min-height:110px;border:1px solid var(--line);border-radius:var(--radius);padding:11px;font-family:var(--font-body);font-size:13.5px;resize:vertical;color:var(--ink-900)}
textarea:focus{outline:2px solid var(--accent);border-color:transparent}
.field-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}
@media(max-width:540px){.field-row{grid-template-columns:1fr}}
.field-row input{width:100%;border:1px solid var(--line);border-radius:var(--radius);padding:9px 11px;font-family:var(--font-body);font-size:13.5px;color:var(--ink-900)}
.field-row input:focus{outline:2px solid var(--accent);border-color:transparent}
.field-label{font:700 12px/1 var(--font-display);margin-bottom:4px;color:var(--ink-700)}
.btn{display:inline-flex;align-items:center;gap:7px;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-pill);padding:11px 20px;font:600 13.5px/1 var(--font-display);cursor:pointer}
.btn:hover{background:var(--accent-dark)}
.btn.ghost{background:var(--surface);color:var(--accent);border:1px solid var(--line)}
.btn.ghost:hover{background:var(--accent-soft)}
.receipt{font-size:12.5px;margin-top:8px}
.receipt.ok{color:var(--green)}
.receipt.err{color:var(--red)}
.empty-state{text-align:center;padding:60px 20px;color:var(--ink-500)}
.empty-state h2{font:700 20px/1.2 var(--font-display);color:var(--ink-700);margin-bottom:10px}
.footer{color:var(--ink-500);font-size:11.5px;margin-top:28px;padding-top:18px;border-top:1px solid var(--line)}
.hub-progress{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0 6px}
.hub-progress .stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:10px 14px;font-size:13px}
.hub-progress .stat b{display:block;font-size:22px;font-weight:800;color:var(--accent)}
/* ── audit reports ── */
.audit-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:18px 0}
@media(max-width:700px){.audit-stats{grid-template-columns:1fr}}
.audit-stats .stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;text-align:center}
.audit-stats .stat b{display:block;font-size:28px;font-weight:800;line-height:1.1}
.audit-stats .stat span{font-size:12px;color:var(--ink-500);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.stat-fixed b{color:var(--green)}
.stat-bug b{color:var(--red)}
.stat-total b{color:var(--blue)}
.why-box{background:var(--blue-bg);border-left:3px solid var(--blue);border-radius:var(--radius);padding:13px 16px;font-size:13.5px;color:var(--ink-900);margin:14px 0}
.why-box code{background:rgba(0,0,0,.06);color:inherit}
.audit-section-title{font:700 14px/1.2 var(--font-display);margin:26px 0 8px;display:flex;align-items:center;gap:8px}
.audit-section-title .n{color:var(--ink-500);font-weight:600;font-size:12.5px}
.audit-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);margin:12px 0;overflow:hidden;box-shadow:var(--shadow-sm)}
.ac-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px;background:var(--surface-warm);border-bottom:1px solid var(--line)}
.ac-file{font-family:var(--font-mono);font-size:12.5px;color:var(--ink-900)}
.ac-line{font-size:12px;color:var(--ink-500)}
.ac-ref{margin-left:auto;font-size:12px}
.badge{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:3px 10px;font:700 11px/1.4 var(--font-display)}
.badge-fixed{background:var(--green-bg);color:var(--green)}
.badge-bug{background:var(--red-bg);color:var(--red)}
.badge-fine{background:var(--blue-bg);color:var(--blue)}
.diff-wrap{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line)}
@media(max-width:700px){.diff-wrap{grid-template-columns:1fr}}
.diff-pane{background:var(--surface);padding:12px 14px;min-width:0}
.diff-pane h4{font:700 10.5px/1 var(--font-display);letter-spacing:.07em;text-transform:uppercase;color:var(--ink-500);margin:0 0 8px}
.diff-pane pre{margin:0;overflow:auto;font-family:var(--font-mono);font-size:12px;line-height:1.55}
.line{display:block;padding:0 7px;border-radius:4px;white-space:pre}
.line-removed{background:var(--diff-removed-bg,rgba(220,38,38,.10));color:var(--diff-removed-ink,#b42318)}
.line-added{background:var(--diff-added-bg,rgba(5,150,105,.12));color:var(--diff-added-ink,#067647)}
.line-neutral{color:var(--ink-700)}
.audit-explain{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid var(--line);font-size:13px;color:var(--ink-700)}
.audit-explain .text{flex:1;min-width:200px}
.verdict{display:inline-flex;align-items:center;border-radius:var(--radius-pill);padding:4px 11px;font:700 11px/1.4 var(--font-display);white-space:nowrap}
.verdict-fixed{background:var(--green-bg);color:var(--green)}
.verdict-todo{background:var(--yellow-bg);color:var(--yellow)}
.verdict-fine{background:var(--blue-bg);color:var(--blue)}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">&#9646;</div>
  <div class="title-block"><b>Plan Review Hub</b><span class="sub">plan-review-hub</span></div>
  <div class="crumbs">${crumbsHtml}</div>
</div>
${bodyHtml}
</body>
</html>`;
}

// ─── page renderers ─────────────────────────────────────────────────────────────

function renderIndex(plans, themeCSS) {
  const progress = getProgress();
  const total = plans.length;
  const decided = plans.filter(p => getFeedback(p.id)).length;
  const doneCount = Object.values(progress).filter(pr => pr.state === "done").length;

  if (!plans.length) {
    const body = `
<div class='wrap'>
  <div class='empty-state'>
    <h2>No plans found</h2>
    <p>Create a <code>plans/</code> directory with plan subfolders, or point the server at an existing directory:<br>
    <code>node scripts/serve.mjs --plans path/to/plans</code></p>
    <p>See <code>examples/plans/</code> for sample plans and <code>docs/plan-format.md</code> for the schema.</p>
  </div>
</div>`;
    return pageShell("Plan Review Hub", "Hub", body, themeCSS);
  }

  const rows = plans.map(p => {
    const fb = getFeedback(p.id) || {};
    const verdict = fb.verdict;
    let verdictChip = "";
    if (verdict) {
      const [vcls, vlabel] = VERDICT_CHIP[verdict] || ["chip-none", verdict.replace(/_/g, " ")];
      verdictChip = chip(vcls, vlabel);
    }
    const pr = progress[p.id];
    let asideHtml = "";
    if (pr) {
      const [pcls, plabel] = PROGRESS_CHIP[pr.state || "not_started"] || ["chip-none", pr.state];
      const ndone = (pr.done || []).length, nrem = (pr.remaining || []).length;
      const sub = ndone ? `${ndone} done · ${nrem} remaining` : (nrem ? `${nrem} steps` : "");
      asideHtml = `<div style='margin-bottom:5px'>${chip(pcls, plabel)}</div>`;
      if (sub) asideHtml += `<div style='font-size:11px;color:var(--ink-500)'>${esc(sub)}</div>`;
    } else {
      asideHtml = verdictChip || chip("chip-none", "No feedback yet");
    }
    const effortHtml = p.effort ? `<span style='font-size:11.5px;color:var(--ink-500);margin-left:8px'>${esc(p.effort)}</span>` : "";
    return `
<a class='index-row' href='/plan/${esc(p.id)}'>
  <div class='num'>${esc(p.num)}</div>
  <div class='body'>
    <h3>${esc(p.title)}${effortHtml}</h3>
    <p>${esc(p.tagline)}</p>
  </div>
  <div class='aside'>${asideHtml}</div>
</a>`;
  }).join("");

  const audits = loadAudits();
  const statsHtml = `
<div class='hub-progress'>
  <div class='stat'><b>${total}</b> Plans</div>
  <div class='stat'><b>${decided}</b> Reviewed</div>
  <div class='stat'><b>${doneCount}</b> Implemented</div>
  <div class='stat'><b>${total - doneCount}</b> Remaining</div>
  ${audits.length ? `<div class='stat'><b>${audits.length}</b> Audits</div>` : ""}
</div>`;

  let auditsSection = "";
  if (audits.length) {
    const auditRows = audits.map(a => {
      const { fixed, bug, total: atotal } = auditCounts(a);
      const sub = `${fixed} fixed · ${bug} open · ${atotal} scanned`;
      return `
<a class='index-row' href='/audit/${esc(a.id)}'>
  <div class='num'>&#9670;</div>
  <div class='body'>
    <h3>${esc(a.title)}</h3>
    <p>${esc((a.summary || "").trim())}</p>
  </div>
  <div class='aside'><div style='font-size:11px;color:var(--ink-500)'>${esc(sub)}</div></div>
</a>`;
    }).join("");
    auditsSection = `<div class='eyebrow' style='margin:26px 0 4px'>Findings audits</div>${auditRows}`;
  }

  const body = `
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Planning hub · ${total} plan${total !== 1 ? "s" : ""}</div>
    <h1 class='page-title'>Plan Review Hub</h1>
    <p class='lead'>Review each plan, answer the decisions, set a verdict, and submit. After feedback is collected, Claude dispatches each approved plan to its own git worktree and subagent.</p>
  </div>
  ${statsHtml}
  ${rows}
  ${auditsSection}
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
</div>`;
  return pageShell("Plan Review Hub", "Hub", body, themeCSS);
}

function renderPlan(plan, plans, themeCSS) {
  const pid = plan.id;
  const progress = getProgress();
  const fb = getFeedback(pid) || {};

  // side nav
  const navItems = plans.map(p => {
    const active = p.id === pid ? " active" : "";
    return `<a class='${active}' href='/plan/${esc(p.id)}'><span>${esc(p.title)}</span><span class='n'>${esc(p.num)}</span></a>`;
  }).join("");

  // decisions
  const decBlocks = (plan.decisions || []).map(d => {
    const saved = (fb.decisions || {})[d.id] ?? d.default;
    const optsHtml = (d.options || []).map(o => {
      const isSel = saved === o.v;
      const recBadge = o.recommended ? ` <span style='font-size:10.5px;color:var(--green);font-weight:700'>recommended</span>` : "";
      return `<label class='opt${isSel ? " sel" : ""}'>` +
        `<input type='radio' name='dec__${esc(d.id)}' value='${esc(o.v)}'${isSel ? " checked" : ""}>` +
        `<span>${esc(o.label)}${recBadge}</span></label>`;
    }).join("");
    return `<label class='q'>${esc(d.q)}</label><div class='help-text'>${esc(d.help || "")}</div>${optsHtml}`;
  }).join("");

  // verdict
  const verdicts = [
    ["approve",              "Approve — build it"],
    ["approve_with_changes", "Approve with changes (see notes)"],
    ["hold",                 "Hold — discuss first"],
    ["reject",               "Reject — do not build"],
  ];
  const savedV = fb.verdict;
  const verdictHtml = verdicts.map(([v, lbl]) =>
    `<label class='opt${savedV === v ? " sel" : ""}'>` +
    `<input type='radio' name='verdict' value='${v}'${savedV === v ? " checked" : ""}>` +
    `<span>${esc(lbl)}</span></label>`
  ).join("");

  // doc sections
  let firstDoc = true;
  const docSections = (plan.docs || []).map(docFile => {
    const raw = readPlanDoc(plan, docFile);
    if (!raw) return "";
    const sectionName = docFile.replace(".md","").replace(/-/g," ").replace(/\b\w/g, c => c.toUpperCase());
    const rendered = mdToHtml(raw);
    const openAttr = firstDoc ? " open" : "";
    firstDoc = false;
    return `<details class='spec-section card'${openAttr}><summary>${esc(sectionName)}</summary><div style='margin-top:12px'>${rendered}</div></details>`;
  }).join("");

  // meta
  const metaItems = [];
  if (plan.effort) metaItems.push(`<div class='kv'>Effort<b>${esc(plan.effort)}</b></div>`);
  if (plan.risk)   metaItems.push(`<div class='kv'>Risk<b>${esc(plan.risk)}</b></div>`);
  if (plan.branch) metaItems.push(`<div class='kv'>Branch<b><code>${esc(plan.branch)}</code></b></div>`);
  metaItems.push(`<div class='kv'>Plan ID<b><code>${esc(pid)}</code></b></div>`);
  const metaHtml = `<div class='meta'>${metaItems.join("")}</div>`;

  const headlineHtml = plan.headline
    ? `<div class='card'><h2>Overview</h2><div class='headline-box'>${plan.headline}</div></div>`
    : "";

  const progressCard = renderProgressCard(pid, progress);

  // audits linked to this plan
  const linkedAudits = loadAudits().filter(a => a.planId === pid);
  let auditsCard = "";
  if (linkedAudits.length) {
    const links = linkedAudits.map(a => {
      const { fixed, bug, total: atotal } = auditCounts(a);
      return `<li><a href='/audit/${esc(a.id)}'>${esc(a.title)}</a> <span style='color:var(--ink-500);font-size:12px'>— ${fixed} fixed · ${bug} open · ${atotal} scanned</span></li>`;
    }).join("");
    auditsCard = `<div class='card'><h2>Findings audits</h2><ul class='md-ul'>${links}</ul></div>`;
  }

  const savedNotes    = esc(fb.notes || "");
  const savedPriority = esc(String(fb.priority || ""));
  const savedAssignee = esc(fb.assignee || "");

  const body = `
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Plan ${esc(plan.num)}</div>
    <h1 class='page-title'>${esc(plan.title)}</h1>
    <p class='lead'>${esc(plan.tagline)}</p>
    ${metaHtml}
  </div>
  <div class='two-col'>
    <div class='main-col'>
      ${headlineHtml}
      ${progressCard}
      ${auditsCard}
      ${docSections}
      <div class='card fb'>
        <h2>Your feedback</h2>
        <form id='fbform'>
          <input type='hidden' name='planId' value='${esc(pid)}'>
          <input type='hidden' name='title' value='${esc(plan.title)}'>
          <label class='q'>Verdict</label>
          <div class='verdict-grid'>${verdictHtml}</div>
          ${decBlocks}
          <label class='q' style='margin-top:18px'>Notes</label>
          <textarea name='notes' placeholder='Guidance, caveats, decision rationale…'>${savedNotes}</textarea>
          <div class='field-row'>
            <div>
              <div class='field-label'>Priority</div>
              <input type='text' name='priority' value='${savedPriority}' placeholder='e.g. high, 1, urgent'>
            </div>
            <div>
              <div class='field-label'>Assignee</div>
              <input type='text' name='assignee' value='${savedAssignee}' placeholder='e.g. alice'>
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
        <div class='side-nav'>${navItems}</div>
      </div>
    </div>
  </div>
  <div class='footer'>plan-review-hub · <a href='/'>hub</a> · <a href='/feedback'>feedback JSON</a></div>
</div>
<script>
  document.querySelectorAll('.opt input').forEach(i => i.addEventListener('change', e => {
    const name = e.target.name;
    if (e.target.type === 'radio') {
      document.querySelectorAll('input[name="' + name + '"]').forEach(x => x.closest('.opt').classList.remove('sel'));
    }
    e.target.closest('.opt').classList.toggle('sel', e.target.checked);
  }));
  document.getElementById('fbform').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const data = {
      planId:    f.planId.value,
      title:     f.title.value,
      verdict:   (f.querySelector('input[name=verdict]:checked') || {}).value || null,
      decisions: {},
      notes:     f.notes.value,
      priority:  f.priority.value,
      assignee:  f.assignee.value,
      submittedAt: new Date().toISOString(),
      ua: navigator.userAgent
    };
    f.querySelectorAll('input[type=radio]:checked').forEach(r => {
      if (r.name.startsWith('dec__')) data.decisions[r.name.slice(5)] = r.value;
    });
    const receipt = document.getElementById('receipt');
    try {
      const resp = await fetch('/submit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      const j = await resp.json();
      receipt.className = j.ok ? 'receipt ok' : 'receipt err';
      receipt.textContent = j.ok
        ? '\\u2713 Saved \\u2014 verdict: ' + (data.verdict || 'none') + '. You can revise and resubmit anytime.'
        : 'Error: ' + j.error;
    } catch (err) {
      receipt.className = 'receipt err';
      receipt.textContent = 'Network error: ' + err;
    }
  });
</script>`;

  const crumbs = `<a href='/'>Hub</a> &nbsp;/&nbsp; Plan ${esc(plan.num)}`;
  return pageShell(`${plan.title} — Plan Review Hub`, crumbs, body, themeCSS);
}

const AUDIT_BADGE = {
  fixed: ["badge-fixed", "Fixed"],
  bug:   ["badge-bug",   "Bug"],
  fine:  ["badge-fine",  "Fine"],
};
const AUDIT_SECTIONS = [
  ["fixed", "&#9989; Fixed"],
  ["bug",   "&#9888;&#65039; Needs fixing"],
  ["fine",  "&#128064; Reviewed &mdash; confirmed fine"],
];

function renderDiffLines(lines, defaultKind) {
  const out = [];
  for (const ln of lines || []) {
    let text, kind;
    if (ln && typeof ln === "object") {
      text = ln.text ?? "";
      kind = ln.kind ?? defaultKind;
    } else {
      text = ln; kind = defaultKind;
    }
    if (!["removed", "added", "neutral"].includes(kind)) kind = defaultKind;
    out.push(`<span class='line line-${kind}'>${esc(text)}</span>`);
  }
  return out.join("") || "<span class='line line-neutral'></span>";
}

function renderFinding(f) {
  const status = f.status || "bug";
  const [badgeCls, badgeLabel] = AUDIT_BADGE[status] || ["badge-bug", status];
  const fileHtml = esc(f.file || "(unknown file)");
  const lineHtml = (f.line !== undefined && f.line !== null) ? `<span class='ac-line'>line ${esc(String(f.line))}</span>` : "";
  const refHtml = f.ref ? `<span class='ac-ref'><a href='${esc(f.ref)}' target='_blank' rel='noopener'>reference &#8599;</a></span>` : "";

  const beforeHtml = renderDiffLines(f.before, "removed");
  const afterHtml = renderDiffLines(f.after, "added");

  let vtext, vcls;
  if (status === "fixed") {
    vtext = f.verdict || (f.commit ? `Fixed in ${f.commit}` : "Fixed");
    vcls = "verdict-fixed";
  } else if (status === "fine") {
    vtext = f.verdict || "No change needed";
    vcls = "verdict-fine";
  } else {
    vtext = f.verdict || "To fix";
    vcls = "verdict-todo";
  }

  return `
<div class='audit-card'>
  <div class='ac-head'>
    <span class='badge ${badgeCls}'>${badgeLabel}</span>
    <span class='ac-file'>${fileHtml}</span>
    ${lineHtml}
    ${refHtml}
  </div>
  <div class='diff-wrap'>
    <div class='diff-pane'><h4>Before</h4><pre>${beforeHtml}</pre></div>
    <div class='diff-pane'><h4>After</h4><pre>${afterHtml}</pre></div>
  </div>
  <div class='audit-explain'>
    <span class='text'>${esc(f.explanation || "")}</span>
    <span class='verdict ${vcls}'>${esc(vtext)}</span>
  </div>
</div>`;
}

function renderAudit(audit, themeCSS) {
  const aid = audit.id;
  const { fixed, bug, total } = auditCounts(audit);

  const pattern = audit.pattern || {};
  let patHtml = "";
  if (pattern.buggy || pattern.correct) {
    const parts = [];
    if (pattern.buggy) parts.push(`buggy <code>${esc(pattern.buggy)}</code>`);
    if (pattern.correct) parts.push(`correct <code>${esc(pattern.correct)}</code>`);
    patHtml = parts.join(" &rarr; ");
  }

  const whyHtml = audit.why ? `<div class='why-box'>${audit.why}</div>` : "";

  const statsHtml = `
<div class='audit-stats'>
  <div class='stat stat-fixed'><b>${fixed}</b><span>Fixed</span></div>
  <div class='stat stat-bug'><b>${bug}</b><span>Needs fixing</span></div>
  <div class='stat stat-total'><b>${total}</b><span>Total scanned</span></div>
</div>`;

  const byStatus = { fixed: [], bug: [], fine: [] };
  for (const f of audit.findings || []) {
    (byStatus[f.status] || byStatus.bug).push(f);
  }

  const sectionsHtml = AUDIT_SECTIONS.map(([status, label]) => {
    const items = byStatus[status] || [];
    if (!items.length) return "";
    const cards = items.map(renderFinding).join("");
    return `<div class='audit-section-title'>${label} <span class='n'>${items.length}</span></div>${cards}`;
  }).join("");

  const today = new Date().toISOString().slice(0, 10);
  const summary = esc(audit.summary || "") || `${fixed} fixed · ${bug} open · ${total} scanned`;

  const planLink = audit.planId
    ? `<div class='kv'>Plan<b><a href='/plan/${esc(audit.planId)}'>${esc(audit.planId)}</a></b></div>`
    : "";

  const body = `
<div class='wrap'>
  <div class='hero'>
    <div class='eyebrow'>Findings audit</div>
    <h1 class='page-title'>${esc(audit.title)}</h1>
    ${patHtml ? `<p class='lead'>${patHtml}</p>` : ""}
    <div class='meta'>
      <div class='kv'>Audit ID<b><code>${esc(aid)}</code></b></div>
      ${planLink}
    </div>
  </div>
  ${statsHtml}
  ${whyHtml}
  ${sectionsHtml || "<div class='empty-state'><h2>No findings</h2><p>This audit has no findings yet.</p></div>"}
  <div class='footer'>Generated ${today} · audit <code>${esc(aid)}</code> · ${summary}</div>
</div>`;

  const crumbs = `<a href='/'>Hub</a> &nbsp;/&nbsp; Audit`;
  return pageShell(`${audit.title} — Findings audit`, crumbs, body, themeCSS);
}

// ─── token auth ─────────────────────────────────────────────────────────────────

const COOKIE_NAME = "prh_token";

function parseCookies(cookieHeader) {
  const out = {};
  for (const part of (cookieHeader || "").split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k) out[k.trim()] = rest.join("=").trim();
  }
  return out;
}

function checkAuth(req) {
  const tok = CFG.token;
  if (!tok) return { ok: true };
  const cookies = parseCookies(req.headers.cookie);
  if (cookies[COOKIE_NAME] === tok) return { ok: true };
  const urlObj = new URL(req.url, "http://localhost");
  if (urlObj.searchParams.get("token") === tok) return { ok: true, setCookie: tok };
  return { ok: false };
}

// ─── request handler ─────────────────────────────────────────────────────────────

function send(res, code, body, ctype = "text/html; charset=utf-8", extraHeaders = {}) {
  const buf = typeof body === "string" ? Buffer.from(body, "utf8") : body;
  res.writeHead(code, {
    "Content-Type": ctype,
    "Cache-Control": "no-store",
    "Content-Length": buf.length,
    ...extraHeaders,
  });
  res.end(buf);
}

function serveAsset(rel, res) {
  const safe = rel.replace(/\.\.\//g, "").replace(/^\/+/, "");
  const full = path.join(REPO, "assets", safe);
  if (!fs.existsSync(full) || !fs.statSync(full).isFile()) {
    return send(res, 404, "not found", "text/plain");
  }
  const ctype = full.endsWith(".css") ? "text/css; charset=utf-8" : "application/octet-stream";
  const body = fs.readFileSync(full);
  res.writeHead(200, { "Content-Type": ctype, "Cache-Control": "max-age=3600", "Content-Length": body.length });
  res.end(body);
}

function handleRequest(req, res) {
  const urlObj = new URL(req.url, "http://localhost");
  const rawPath = urlObj.pathname;
  const normPath = rawPath.replace(/\/+$/, "") || "/";

  const auth = checkAuth(req);
  const extraHeaders = {};
  if (auth.setCookie) {
    extraHeaders["Set-Cookie"] = `${COOKIE_NAME}=${auth.setCookie}; Path=/; HttpOnly; SameSite=Strict`;
  }

  if (!auth.ok) {
    return send(res, 401, "401 Unauthorised — supply ?token=<secret>", "text/plain");
  }

  if (req.method === "GET" || req.method === "HEAD") {
    const plans = loadPlans();
    const planById = Object.fromEntries(plans.map(p => [p.id, p]));
    const themeCSS = loadThemeCSS();

    if (normPath === "/" || normPath === "") {
      return send(res, 200, renderIndex(plans, themeCSS), "text/html; charset=utf-8", extraHeaders);
    }
    if (normPath === "/healthz") {
      return send(res, 200, '{"status":"ok"}', "application/json", extraHeaders);
    }
    if (normPath === "/feedback") {
      const data = Object.fromEntries(plans.map(p => [p.id, getFeedback(p.id)]));
      return send(res, 200, JSON.stringify(data, null, 2), "application/json", extraHeaders);
    }
    if (normPath === "/audits") {
      const data = Object.fromEntries(loadAudits().map(a => [a.id, a]));
      return send(res, 200, JSON.stringify(data, null, 2), "application/json", extraHeaders);
    }
    if (normPath.startsWith("/audit/")) {
      const aid = normPath.slice("/audit/".length).replace(/^\/+|\/+$/g, "");
      const audit = getAudit(aid);
      if (!audit) return send(res, 404, `<div style='font-family:sans-serif;padding:40px'><h1>404</h1><p>Unknown audit '${esc(aid)}'</p><a href='/'>Back</a></div>`, "text/html; charset=utf-8");
      return send(res, 200, renderAudit(audit, themeCSS), "text/html; charset=utf-8", extraHeaders);
    }
    if (normPath.startsWith("/plan/")) {
      const pid = normPath.slice("/plan/".length).replace(/^\/+|\/+$/g, "");
      const plan = planById[pid];
      if (!plan) return send(res, 404, `<div style='font-family:sans-serif;padding:40px'><h1>404</h1><p>Unknown plan '${esc(pid)}'</p><a href='/'>Back</a></div>`, "text/html; charset=utf-8");
      return send(res, 200, renderPlan(plan, plans, themeCSS), "text/html; charset=utf-8", extraHeaders);
    }
    if (normPath.startsWith("/assets/")) {
      return serveAsset(normPath.slice("/assets/".length), res);
    }
    return send(res, 404, "<div style='font-family:sans-serif;padding:40px'><h1>404</h1><a href='/'>Back</a></div>", "text/html; charset=utf-8");
  }

  if (req.method === "POST") {
    if (normPath !== "/submit") {
      return send(res, 404, JSON.stringify({ ok: false, error: "not found" }), "application/json");
    }
    let body = "";
    req.on("data", chunk => { body += chunk; });
    req.on("end", () => {
      let data;
      try {
        data = JSON.parse(body);
        const pid = data.planId;
        if (!pid) throw new Error("missing planId");
        const plans = loadPlans();
        const planById = Object.fromEntries(plans.map(p => [p.id, p]));
        if (!planById[pid]) throw new Error(`unknown planId '${pid}'`);
        const outPath = path.join(feedbackDir(), `${pid}.json`);
        fs.writeFileSync(outPath, JSON.stringify(data, null, 2));
        console.log(`  [feedback] ${pid}: verdict=${data.verdict} priority=${data.priority} assignee=${data.assignee}`);
        send(res, 200, JSON.stringify({ ok: true, planId: pid }), "application/json");
      } catch (e) {
        send(res, 400, JSON.stringify({ ok: false, error: e.message }), "application/json");
      }
    });
    return;
  }

  send(res, 405, "Method Not Allowed", "text/plain");
}

// ─── main ──────────────────────────────────────────────────────────────────────

applyCLIArgs();
fs.mkdirSync(stateDir(), { recursive: true });
fs.mkdirSync(feedbackDir(), { recursive: true });

const server = http.createServer(handleRequest);
server.listen(CFG.port, CFG.host, () => {
  const plans = loadPlans();
  const audits = loadAudits();
  const ips = localIPs();
  console.log(`\nplan-review-hub running on ${CFG.host}:${CFG.port}`);
  console.log(`  source: ${CFG.source}  plans: ${abs(CFG.plansDir)}  state: ${stateDir()}`);
  console.log(CFG.token ? "  token:  set (required)" : "  token:  not set (open on LAN — see security note in README)");
  console.log();
  for (const ip of ips) {
    console.log(`  HUB    http://${ip}:${CFG.port}/`);
    for (const p of plans) {
      console.log(`    ${p.num}  http://${ip}:${CFG.port}/plan/${encodeURIComponent(p.id)}`);
    }
  }
  if (!plans.length) console.log("  (no plans found — see examples/plans/ for sample plans)");
  console.log();
});
