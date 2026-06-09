#!/usr/bin/env python3
"""Validate plan-review-hub skill packaging and runtime smoke checks."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CheckError(Exception):
    pass


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"Missing required file: {rel(path)}") from exc


def check_skill_frontmatter() -> None:
    path = ROOT / "SKILL.md"
    text = read_text(path)
    match = re.match(r"\A---\n(?P<body>.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise CheckError("SKILL.md must start with YAML frontmatter delimited by ---")

    fields: dict[str, str] = {}
    current_key = None
    for raw in match.group("body").splitlines():
        if not raw.strip():
            continue
        if raw.startswith((" ", "\t")) and current_key:
            fields[current_key] += " " + raw.strip()
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise CheckError(f"Invalid frontmatter line in SKILL.md: {raw}")
        current_key = key.strip()
        fields[current_key] = value.strip()

    if fields.get("name") != "plan-review-hub":
        raise CheckError("SKILL.md frontmatter name must be plan-review-hub")
    description = fields.get("description", "")
    if not description:
        raise CheckError("SKILL.md frontmatter description is required")
    for term in ("Codex", "Claude Code", "coding-agent"):
        if term not in description:
            raise CheckError(f"SKILL.md description should mention {term!r}")


def check_openai_yaml() -> None:
    path = ROOT / "agents" / "openai.yaml"
    text = read_text(path)
    required = [
        "interface:",
        'display_name: "Plan Review Hub"',
        'short_description: "Review and dispatch implementation plans"',
        "default_prompt:",
        "$plan-review-hub",
    ]
    for needle in required:
        if needle not in text:
            raise CheckError(f"{rel(path)} is missing expected content: {needle}")


def load_json(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise CheckError(f"Invalid JSON in {rel(path)}: {exc}") from exc


def check_plan_json(path: Path) -> None:
    data = load_json(path)
    if not isinstance(data, dict):
        raise CheckError(f"{rel(path)} must contain a JSON object")
    plan_id = data.get("id")
    if not isinstance(plan_id, str) or not plan_id:
        raise CheckError(f"{rel(path)} must define a non-empty string id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", plan_id):
        raise CheckError(f"{rel(path)} id must be URL-safe lowercase kebab-case")
    if not data.get("title"):
        raise CheckError(f"{rel(path)} must define title")
    docs = data.get("docs", [])
    if not isinstance(docs, list):
        raise CheckError(f"{rel(path)} docs must be a list")
    for doc in docs:
        if not isinstance(doc, str):
            raise CheckError(f"{rel(path)} docs entries must be strings")
        doc_path = path.parent / doc
        if not doc_path.is_file():
            raise CheckError(f"{rel(path)} references missing doc: {doc}")
    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        raise CheckError(f"{rel(path)} decisions must be a list")
    for decision in decisions:
        if not isinstance(decision, dict) or not decision.get("id") or not decision.get("q"):
            raise CheckError(f"{rel(path)} has an invalid decision entry")
        options = decision.get("options", [])
        if not isinstance(options, list) or not options:
            raise CheckError(f"{rel(path)} decision {decision.get('id')} needs options")


def check_audit_json(path: Path) -> None:
    data = load_json(path)
    if not isinstance(data, dict):
        raise CheckError(f"{rel(path)} must contain a JSON object")
    audit_id = data.get("id")
    if audit_id is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(audit_id)):
        raise CheckError(f"{rel(path)} id must be URL-safe lowercase kebab-case")
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise CheckError(f"{rel(path)} findings must be a list")
    for finding in findings:
        if not isinstance(finding, dict):
            raise CheckError(f"{rel(path)} has a non-object finding entry")
        status = finding.get("status", "bug")
        if status not in ("bug", "fixed", "fine"):
            raise CheckError(f"{rel(path)} finding status must be bug|fixed|fine, got {status!r}")
        for key in ("before", "after"):
            if key in finding and not isinstance(finding[key], list):
                raise CheckError(f"{rel(path)} finding {key} must be a list")


def check_json_files() -> None:
    load_json(ROOT / "plan-review-hub.config.json")
    for pattern in ("examples/plans/*/plan.json", "plans/*/plan.json"):
        for path in sorted(ROOT.glob(pattern)):
            check_plan_json(path)
    for pattern in ("examples/audits/*.json", ".planning-hub/audits/*.json"):
        for path in sorted(ROOT.glob(pattern)):
            check_audit_json(path)
    progress_path = ROOT / ".planning-hub" / "progress.json"
    if progress_path.exists():
        load_json(progress_path)


def run_checked(cmd: list[str], *, optional: bool = False) -> None:
    if optional and not shutil.which(cmd[0]):
        print(f"skip: {cmd[0]} not found")
        return
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise CheckError(f"Command failed: {' '.join(cmd)}\n{detail}")


def check_server_syntax() -> None:
    run_checked([sys.executable, "-m", "py_compile", "scripts/serve.py"])
    run_checked(["node", "--check", "scripts/serve.mjs"], optional=True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.read().decode("utf-8")


def smoke_server() -> None:
    port = free_port()
    cmd = [
        sys.executable,
        "scripts/serve.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--plans",
        "examples/plans",
        "--audits",
        "examples/audits",
        "--state",
        ".planning-hub/validate-smoke",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 5
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise CheckError(f"Smoke server exited early:\n{output.strip()}")
            try:
                if fetch_json(f"{base}/healthz").get("status") == "ok":
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise CheckError("Smoke server did not become healthy")

        index = fetch_text(f"{base}/")
        plan = fetch_text(f"{base}/plan/api-versioning")
        audit = fetch_text(f"{base}/audit/operator-precedence-sweep")
        if "Plan Review Hub" not in index:
            raise CheckError("Smoke index did not render Plan Review Hub")
        if "API versioning strategy" not in plan:
            raise CheckError("Smoke plan page did not render expected example plan")
        if "Findings audit" not in audit or "Needs fixing" not in audit:
            raise CheckError("Smoke audit page did not render the example findings audit")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        shutil.rmtree(ROOT / ".planning-hub" / "validate-smoke", ignore_errors=True)


def check_provider_wording() -> None:
    """Keep provider names out of core workflow text except labeled provider sections."""
    skill = read_text(ROOT / "SKILL.md")
    provider_section = "For provider-specific install and dispatch notes"
    if provider_section not in skill:
        raise CheckError("SKILL.md should point provider-specific details to references/provider-notes.md")
    notes = read_text(ROOT / "references" / "provider-notes.md")
    for heading in ("## Codex", "## Claude Code"):
        if heading not in notes:
            raise CheckError(f"references/provider-notes.md is missing {heading}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="start the Python server and fetch smoke-test pages")
    args = parser.parse_args()

    checks = [
        ("skill frontmatter", check_skill_frontmatter),
        ("Codex UI metadata", check_openai_yaml),
        ("JSON and plan docs", check_json_files),
        ("server syntax", check_server_syntax),
        ("provider wording", check_provider_wording),
    ]
    if args.smoke:
        checks.append(("Python server smoke", smoke_server))

    failed = False
    for label, fn in checks:
        try:
            fn()
            print(f"ok: {label}")
        except CheckError as exc:
            failed = True
            print(f"fail: {label}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
