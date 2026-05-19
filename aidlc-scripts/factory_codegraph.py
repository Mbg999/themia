#!/usr/bin/env python3
"""
factory_codegraph.py

CLI helper for CodeGraph integration in the AIDLC orchestrator.
Handles install checks, index status, and graceful degradation reporting.

Usage:
  python3 aidlc-scripts/factory_codegraph.py status
  python3 aidlc-scripts/factory_codegraph.py check          # exits 0 if ready, 1 if not
  python3 aidlc-scripts/factory_codegraph.py affected <file1> [file2 ...]
  python3 aidlc-scripts/factory_codegraph.py affected --stdin  # read filenames from stdin

Exit codes:
  0 — OK / indexed / tests found
  1 — CodeGraph not installed or not indexed
  2 — usage error
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess. Return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd)}"


def cmd_status(args: list[str]) -> int:
    """Print CodeGraph status as JSON-ish dict."""
    rc, out, err = _run(["codegraph", "status", "--json"])
    if rc == 127:
        result = {
            "installed": False,
            "indexed": False,
            "error": "codegraph not found — install with: npm install -g @colbymchenry/codegraph",
        }
        print(json.dumps(result, indent=2))
        return 1

    db_path = Path(".codegraph/codegraph.db")
    indexed = db_path.exists()

    if rc == 0 and out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    result = {
        "installed": True,
        "indexed": indexed,
        "nodes": data.get("nodes", data.get("nodeCount", 0)),
        "files": data.get("files", data.get("fileCount", 0)),
        "backend": data.get("backend", "native"),
    }

    if not indexed:
        result["suggestion"] = "Run: codegraph init -i"

    print(json.dumps(result, indent=2))
    return 0 if indexed else 1


def cmd_check(args: list[str]) -> int:
    """Exit 0 if CodeGraph is installed and indexed, 1 otherwise. Quiet."""
    rc, _, _ = _run(["codegraph", "--version"])
    if rc == 127:
        return 1
    db_path = Path(".codegraph/codegraph.db")
    return 0 if db_path.exists() else 1


def cmd_affected(args: list[str]) -> int:
    """
    Run `codegraph affected` on a list of changed files.

    Either pass filenames as positional args, or use --stdin to read from stdin.
    Prints affected test files to stdout (one per line).
    Returns 0 if tests found, 1 if codegraph unavailable or no affected tests.
    """
    if not args or (len(args) == 1 and args[0] == "--help"):
        print("Usage: factory_codegraph.py affected <file1> [file2 ...] | --stdin")
        return 2

    use_stdin = "--stdin" in args
    if use_stdin:
        changed_files = [line.strip() for line in sys.stdin if line.strip()]
    else:
        changed_files = [a for a in args if not a.startswith("--")]

    if not changed_files:
        return 0

    # Try `codegraph affected --stdin --quiet`
    rc_ver, _, _ = _run(["codegraph", "--version"])
    if rc_ver == 127:
        # Graceful degradation — print nothing, caller falls back to full suite
        return 1

    proc = subprocess.Popen(
        ["codegraph", "affected", "--stdin", "--quiet"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdin_data = "\n".join(changed_files)
    try:
        out, err = proc.communicate(input=stdin_data, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        return 1

    affected = [line.strip() for line in out.splitlines() if line.strip()]
    if affected:
        print("\n".join(affected))
        return 0
    return 1


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: factory_codegraph.py <status|check|affected> [args...]", file=sys.stderr)
        return 2

    command = argv[0]
    rest = argv[1:]

    dispatch = {
        "status": cmd_status,
        "check": cmd_check,
        "affected": cmd_affected,
    }

    if command not in dispatch:
        print(f"Unknown command: {command}. Valid: {', '.join(dispatch)}", file=sys.stderr)
        return 2

    return dispatch[command](rest)


if __name__ == "__main__":
    raise SystemExit(main())
