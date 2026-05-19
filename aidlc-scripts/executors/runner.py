#!/usr/bin/env python3
"""Secure executor CLI used by the manager to run allowlisted scripts.

Reads a JSON payload from stdin with shape:
  {"run_folder": "...", "aidlc_docs": "...", "actions": [ {action...} ]}

Supported action types:
  - {"action":"run_script","script": "path/to/script","args": [..]}

The executor enforces a conservative allowlist: only files under `aidlc-scripts/`
or `.venv/bin` or `bin/` in the repo root are allowed. No shell=True is used.
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def _allowed_bases() -> list[Path]:
    bases = [REPO_ROOT / "aidlc-scripts", REPO_ROOT / "bin", REPO_ROOT / ".venv" / "bin"]

    # Allow additional paths from environment variable (colon-separated)
    extra = os.environ.get("EXECUTOR_ALLOW_BASES")
    if extra:
        for p in extra.split(":"):
            p = p.strip()
            if p:
                bases.append((REPO_ROOT / p) if not p.startswith("/") else Path(p))

    # Allow additional entries from an allowlist file
    allow_file = REPO_ROOT / "aidlc-scripts" / "executors" / "allowlist.txt"
    try:
        if allow_file.exists():
            for line in allow_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                p = Path(line) if line.startswith("/") else REPO_ROOT / line
                bases.append(p)
    except Exception:
        # Best-effort: ignore file errors
        pass

    # Deduplicate while preserving order
    seen = set()
    out: list[Path] = []
    for b in bases:
        try:
            key = str(b.resolve())
        except Exception:
            key = str(b)
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def _is_allowed(path: Path) -> bool:
    try:
        rp = path.resolve()
    except Exception:
        return False
    for base in _allowed_bases():
        try:
            if rp == base.resolve() or rp.is_relative_to(base.resolve()):
                return True
        except Exception:
            if str(rp).startswith(str(base.resolve())):
                return True
    return False


def _run_script(script: str, args: list[str] | None = None, run_folder: str | None = None, timeout: int = 300) -> dict:
    args = args or []
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = REPO_ROOT / script_path
    if not script_path.exists():
        return {"ok": False, "error": "script not found", "script": str(script_path)}
    if not _is_allowed(script_path):
        return {"ok": False, "error": "script not allowed by executor policy", "script": str(script_path)}

    # Build command without shell
    if script_path.suffix == ".py":
        cmd = [sys.executable, str(script_path)] + list(args)
    elif script_path.suffix == ".sh":
        cmd = ["bash", str(script_path)] + list(args)
    else:
        # If executable, run directly; otherwise reject
        if os.access(str(script_path), os.X_OK):
            cmd = [str(script_path)] + list(args)
        else:
            return {"ok": False, "error": "unsupported script type and not executable", "script": str(script_path)}

    cwd = str(Path(run_folder).resolve()) if run_folder else str(REPO_ROOT)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": f"timeout after {timeout}s", "stdout": e.stdout, "stderr": e.stderr}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"error": "failed to read JSON payload from stdin"}))
        return 2

    run_folder = payload.get("run_folder")
    actions = payload.get("actions") or []
    results: list[Any] = []

    for i, act in enumerate(actions):
        if not isinstance(act, dict):
            results.append({"action_index": i, "ok": False, "error": "invalid action object"})
            continue
        if act.get("action") == "run_script":
            script = act.get("script")
            args = act.get("args") or []
            res = _run_script(script, args, run_folder)
            res["action_index"] = i
            results.append(res)
        else:
            results.append({"action_index": i, "ok": False, "error": "unsupported action type"})

    print(json.dumps({"results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
