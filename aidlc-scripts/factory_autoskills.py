#!/usr/bin/env python3
"""factory_autoskills.py — Install custom/internal/private skills from skill-sources.yaml.

This script handles skills that are NOT in the public autoskills registry
(https://github.com/midudev/autoskills). Use it for:
  - Company-internal or project-specific skills
  - Skills for frameworks not yet covered by autoskills
  - Any skill you want to pin to a specific URL + SHA-256

For public framework skills (Next.js, Angular, Express, Vue, etc.),
use factory_skill_sync.py — it wraps the autoskills CLI and handles
monorepo workspaces automatically.

Both scripts install to .agents/skills/<name>/ and coexist safely.

Usage:
    python3 aidlc-scripts/factory_autoskills.py            # install/update all
    python3 aidlc-scripts/factory_autoskills.py --dry-run  # preview without writing
    python3 aidlc-scripts/factory_autoskills.py --skill my-internal-skill
    python3 aidlc-scripts/factory_autoskills.py --check    # verify SHAs of installed skills

Exit codes:
    0  all skills installed/verified OK
    1  one or more skills failed (SHA mismatch, download error)
    2  usage error or missing skill-sources.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
SOURCES_FILE = REPO_ROOT / "skill-sources.yaml"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

sys.path.insert(0, str(Path(__file__).parent))
from skill_utils import sha256_file as _sha256_file


# ── minimal YAML parser (subset: only what skill-sources.yaml needs) ──────────

def _parse_yaml_sources(text: str) -> list[dict]:
    """Parse skill-sources.yaml without depending on pyyaml."""
    sources: list[dict] = []
    current: dict | None = None
    applies_to: dict | None = None
    in_sources = False
    in_applies_to = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()

        # skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "sources:":
            in_sources = True
            continue

        if not in_sources:
            continue

        indent = len(line) - len(stripped)

        if indent == 2 and stripped.startswith("- name:"):
            # flush previous entry
            if current is not None:
                if applies_to is not None:
                    current["applies_to"] = applies_to
                sources.append(current)
            name_val = stripped[len("- name:"):].strip().strip('"\'')
            current = {"name": name_val, "url": "", "sha256": ""}
            applies_to = None
            in_applies_to = False
            continue

        if current is None:
            continue

        if indent == 4:
            if stripped.startswith("applies_to:"):
                in_applies_to = True
                applies_to = {}
                continue
            in_applies_to = False
            key, _, val = stripped.partition(":")
            current[key.strip()] = val.strip().strip('"\'')
            continue

        if indent == 6 and in_applies_to and applies_to is not None:
            key, _, val = stripped.partition(":")
            applies_to[key.strip()] = val.strip().strip('"\'')

    # flush last entry
    if current is not None:
        if applies_to is not None:
            current["applies_to"] = applies_to
        sources.append(current)

    return sources


# ── helpers ───────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _download(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "factory_autoskills/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _skill_target(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def _is_placeholder(entry: dict) -> bool:
    return entry.get("name", "").startswith("_") or not entry.get("url")


# ── core operations ───────────────────────────────────────────────────────────

def install_skill(entry: dict, *, dry_run: bool = False) -> dict[str, Any]:
    """Download, verify, and write one skill. Returns a result dict."""
    name = entry["name"]
    url = entry["url"]
    expected_sha = entry.get("sha256", "").strip()
    target = _skill_target(name)

    result: dict[str, Any] = {"name": name, "status": "ok", "detail": ""}

    if _is_placeholder(entry):
        result["status"] = "skipped"
        result["detail"] = "placeholder entry"
        return result

    if not url:
        result["status"] = "error"
        result["detail"] = "url is empty"
        return result

    # download
    try:
        data = _download(url)
    except (urllib.error.URLError, ValueError) as exc:
        result["status"] = "error"
        result["detail"] = f"download failed: {exc}"
        return result

    actual_sha = _sha256(data)

    # SHA verification
    if expected_sha:
        if actual_sha != expected_sha:
            result["status"] = "error"
            result["detail"] = (
                f"SHA-256 mismatch — expected {expected_sha[:16]}… "
                f"got {actual_sha[:16]}…"
            )
            return result
    else:
        result["detail"] = f"no sha256 pinned — actual: {actual_sha}"

    # idempotency check
    if not dry_run:
        if target.exists() and _sha256(target.read_bytes()) == actual_sha:
            result["status"] = "unchanged"
            result["detail"] = "content identical, skipped write"
            return result

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            _rel = target.relative_to(REPO_ROOT)
        except ValueError:
            _rel = target
        _sha_note = f" (sha256: {actual_sha[:8]}…)" if not expected_sha else ""
        result["detail"] = f"written → {_rel}{_sha_note}"
    else:
        result["status"] = "dry-run"
        try:
            _rel = target.relative_to(REPO_ROOT)
        except ValueError:
            _rel = target
        result["detail"] = f"would write → {_rel}"

    return result


def check_skill(entry: dict) -> dict[str, Any]:
    """Verify SHA-256 of an already-installed skill without downloading."""
    name = entry["name"]
    expected_sha = entry.get("sha256", "").strip()
    target = _skill_target(name)

    result: dict[str, Any] = {"name": name, "status": "ok", "detail": ""}

    if _is_placeholder(entry):
        result["status"] = "skipped"
        result["detail"] = "placeholder"
        return result

    if not target.exists():
        result["status"] = "missing"
        try:
            _rel = target.relative_to(REPO_ROOT)
        except ValueError:
            _rel = target
        result["detail"] = f"{_rel} not found"
        return result

    if not expected_sha:
        result["status"] = "unverified"
        result["detail"] = "no sha256 pinned in skill-sources.yaml"
        return result

    actual = _sha256(target.read_bytes())
    if actual != expected_sha:
        result["status"] = "drift"
        result["detail"] = f"SHA mismatch — pinned {expected_sha[:16]}… on disk {actual[:16]}…"
    else:
        result["detail"] = "SHA matches"

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_sources(only: str | None) -> list[dict]:
    if not SOURCES_FILE.exists():
        print(f"ERROR: {SOURCES_FILE} not found", file=sys.stderr)
        sys.exit(2)

    text = SOURCES_FILE.read_text(encoding="utf-8")
    entries = _parse_yaml_sources(text)

    if only:
        entries = [e for e in entries if e["name"] == only]
        if not entries:
            print(f"ERROR: skill '{only}' not found in skill-sources.yaml", file=sys.stderr)
            sys.exit(2)

    return entries


def _print_result(r: dict) -> None:
    icons = {"ok": "✓", "unchanged": "–", "dry-run": "○", "skipped": "·",
             "error": "✗", "missing": "✗", "drift": "⚠", "unverified": "?"}
    icon = icons.get(r["status"], "?")
    detail = f"  {r['detail']}" if r["detail"] else ""
    print(f"  {icon} {r['name']} [{r['status']}]{detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview actions without writing files")
    parser.add_argument("--skill", metavar="NAME",
                        help="Only operate on this skill by name")
    parser.add_argument("--check", action="store_true",
                        help="Verify SHA-256 of installed skills (no download)")
    args = parser.parse_args()

    entries = _load_sources(args.skill)
    results = []

    if args.check:
        print(f"Checking {len(entries)} skill(s)…")
        for entry in entries:
            results.append(check_skill(entry))
    else:
        mode = "dry-run " if args.dry_run else ""
        print(f"Installing {mode}{len(entries)} skill(s) from skill-sources.yaml…")
        for entry in entries:
            results.append(install_skill(entry, dry_run=args.dry_run))

    for r in results:
        _print_result(r)

    errors = [r for r in results if r["status"] in ("error", "missing", "drift")]
    if errors:
        print(f"\n{len(errors)} skill(s) failed.", file=sys.stderr)
        sys.exit(1)

    ok_count = sum(1 for r in results if r["status"] in ("ok",))
    skipped = sum(1 for r in results if r["status"] in ("unchanged", "skipped", "dry-run", "unverified"))
    print(f"\n{ok_count} installed, {skipped} unchanged/skipped, {len(errors)} errors.")


if __name__ == "__main__":
    main()
