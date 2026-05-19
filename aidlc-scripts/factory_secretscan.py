#!/usr/bin/env python3
"""factory_secretscan.py — Regex-based secret scanner for handoff artifacts.

Scans YAML/JSON handoff files for potential secrets (API keys, tokens,
passwords, private keys) in `emitted_knowledge[].body`, `findings[].message`,
and any free-text fields.

Usage
-----
    factory_secretscan.py <handoff-file> [--json] [--strip]

Exit codes:
    0 — no secrets detected
    1 — secrets detected
    2 — usage error

With --strip, secrets are replaced with '[REDACTED]' in-place (writes a new
version; original is backed up with .original suffix).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


# Regex patterns for common secret formats.
# Keys are descriptive labels, values are compiled regexes.
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"(?<![a-zA-Z0-9/+\-=])AKIA[0-9A-Z]{16}(?![a-zA-Z0-9/+\-=])")),
    ("AWS Secret Key", re.compile(r"(?<![a-zA-Z0-9/+\-=])(?:aws_secret[_-]access[_-]key|secret[_-]access[_-]key|aws_secret_key|secret_key)[:=]\s*['\"]?[a-zA-Z0-9/+=]{40}['\"]?", re.IGNORECASE)),
    ("GitHub Token", re.compile(r"(?<![a-zA-Z0-9])gh[pousr]_[A-Za-z0-9_]{36,}(?![a-zA-Z0-9])")),
    ("GitLab Token", re.compile(r"(?<![a-zA-Z0-9])glpat-[A-Za-z0-9\-_]{20,}(?![a-zA-Z0-9])")),
    ("Slack Token", re.compile(r"(?<![a-zA-Z0-9])xox[baprs]-[0-9a-zA-Z\-]{10,}(?![a-zA-Z0-9])")),
    ("JWT Token", re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")),
    ("Private Key", re.compile(r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY-----")),
    ("Generic Password", re.compile(r'(?:"|\')?(?:password|passwd|pwd|secret)(?:"|\')?\s*[:=]\s*["\']?[^"\'{}\[\],\s]{8,}["\']?', re.IGNORECASE)),
    ("API Key Header", re.compile(r'(?:"|\')?(?:api[_-]?key|apikey|api_secret)(?:"|\')?\s*[:=]\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("Bearer Token", re.compile(r'["\']?bearer["\']?\s+[a-zA-Z0-9\-_\.]{20,}', re.IGNORECASE)),
    ("Connection String", re.compile(r"(?:mongodb|postgresql|mysql|redis|amqp)://[^\s]{10,}")),
]

TEXT_KEYS = {"body", "message", "recommendation", "description", "evidence", "note", "summary"}


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def scan_text(text: str) -> list[dict]:
    """Scan a single text string for secrets. Returns list of {pattern, match}."""
    findings: list[dict] = []
    for label, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            findings.append({
                "pattern": label,
                "match": m.group()[:40] + "..." if len(m.group()) > 40 else m.group(),
                "start": m.start(),
                "end": m.end(),
            })
    return findings


def scan_doc(doc, path: str = "<root>") -> list[dict]:
    """Recursively scan a parsed document for secrets in text fields."""
    findings: list[dict] = []
    if isinstance(doc, str):
        for f in scan_text(doc):
            f["path"] = path
            findings.append(f)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            fp = f"{path}.{k}" if path != "<root>" else k
            if isinstance(v, str) and k in TEXT_KEYS:
                for f in scan_text(v):
                    f["path"] = fp
                    findings.append(f)
            elif isinstance(v, (dict, list)):
                findings.extend(scan_doc(v, fp))
    elif isinstance(doc, list):
        for i, item in enumerate(doc):
            findings.extend(scan_doc(item, f"{path}[{i}]"))
    return findings


def strip_secrets(text: str) -> str:
    """Replace secret matches with [REDACTED]."""
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def main() -> None:
    p = argparse.ArgumentParser(description="Secret scanner for handoff artifacts")
    p.add_argument("handoff", help="path to YAML or JSON handoff file")
    p.add_argument("--json", action="store_true", help="output as JSON")
    p.add_argument("--strip", action="store_true",
                   help="replace secrets with [REDACTED] (writes .stripped file)")
    args = p.parse_args()

    path = Path(args.handoff)
    if not path.exists():
        _die(f"file not found: {path}")

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                _die(f"missing dependency: {sys.executable} -m pip install pyyaml")
            doc = yaml.safe_load(path.read_text())
        elif suffix == ".json":
            doc = json.loads(path.read_text())
        else:
            _die(f"unsupported extension: {suffix} (expected .yaml/.yml/.json)")
    except (yaml.YAMLError if yaml is not None else (), json.JSONDecodeError) as e:
        _die(f"parse error: {e}")

    findings = scan_doc(doc)

    if args.strip and findings:
        text = path.read_text()
        stripped = strip_secrets(text)
        backup = path.with_name(path.stem + suffix + ".original")
        if backup.exists():
            import time
            backup = path.with_name(path.stem + suffix + f".original.{int(time.time())}")
        backup.write_text(text)
        tmp = path.with_name(path.stem + suffix + ".stripped.tmp")
        tmp.write_text(stripped)
        tmp.replace(path)
        print(f"stripped {len(findings)} secret(s) from {path.name} (backup: {backup.name})")

    if args.json:
        print(json.dumps({
            "file": str(path),
            "secrets_found": len(findings),
            "findings": findings,
        }, indent=2))
    else:
        if findings:
            print(f"SECRETS DETECTED in {path.name} ({len(findings)} finding(s)):", file=sys.stderr)
            for f in findings:
                print(f"  - {f['path']}: {f['pattern']} match={f['match']}", file=sys.stderr)
        else:
            print(f"OK {path.name} — no secrets detected")

    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
