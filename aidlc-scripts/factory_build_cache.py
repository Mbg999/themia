#!/usr/bin/env python3
"""factory_build_cache.py — Build cache for unchanged design units (Phase 7+).

Computes a content-addressable hash of each unit's source files before spawning
build-test-agent. If the hash matches a prior run's successful build, the unit
can be skipped and the prior result reused.

Usage
-----
    factory_build_cache.py check <run-id> <unit> [--manifest PATH]
        Check if a cached build result exists for this unit.
        Exit codes: 0 = cache hit (print cached result), 1 = cache miss

    factory_build_cache.py save <run-id> <unit> --hash <sha> [--status <s>]
        Save a build result to the cache.

    factory_build_cache.py hash <run-id> <unit> --files <file>...
        Compute a combined hash of the given files (git hash-object).

Storage
-------
    .aidlc-orchestrator/build-cache/<unit-hash>.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))
CACHE_DIR = REPO_ROOT / ".aidlc-orchestrator" / "build-cache"


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def compute_hash(files: list[str]) -> str:
    """Compute a combined hash for a set of files using git hash-object."""
    hasher = hashlib.sha256()
    for f in sorted(files):
        path = REPO_ROOT / f
        if not path.exists():
            continue
        try:
            result = subprocess.run(
                ["git", "hash-object", str(path)],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
                timeout=30,
            )
            if result.returncode == 0:
                hasher.update(result.stdout.strip().encode())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Fall back to file content hash
            hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


def cmd_check(args: argparse.Namespace) -> None:
    if not CACHE_DIR.exists():
        print(json.dumps({"hit": False, "reason": "no cache directory"}))
        sys.exit(1)

    # Compute hash from files if provided, otherwise from unit handoff
    hash_val = args.hash
    if not hash_val and args.files:
        hash_val = compute_hash(args.files)
    if not hash_val:
        _die("provide --hash or --files to compute cache key")

    cache_file = CACHE_DIR / f"{hash_val}.yaml"
    if not cache_file.exists():
        print(json.dumps({"hit": False, "hash": hash_val}))
        sys.exit(1)

    try:
        cached = yaml.safe_load(cache_file.read_text()) if yaml else json.loads(cache_file.read_text())
    except (json.JSONDecodeError, yaml.YAMLError if yaml else ValueError):
        cached = {}
    print(json.dumps({
        "hit": True,
        "hash": hash_val,
        "result": cached,
    }))
    sys.exit(0)


def cmd_save(args: argparse.Namespace) -> None:
    hash_val = args.hash or compute_hash(args.files or [])
    if not hash_val:
        _die("provide --hash or --files to compute cache key")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "hash": hash_val,
        "unit": args.unit,
        "run_id": args.run_id,
        "status": args.status or "complete",
    }
    (CACHE_DIR / f"{hash_val}.yaml").write_text(
        yaml.safe_dump(entry, sort_keys=False) if yaml else json.dumps(entry)
    )
    print(f"saved build cache for {args.unit} (hash={hash_val})")


def cmd_hash(args: argparse.Namespace) -> None:
    if not args.files:
        _die("--files is required")
    h = compute_hash(args.files)
    print(json.dumps({"hash": h, "files": args.files}))


def main() -> None:
    p = argparse.ArgumentParser(description="AIDLC Build Cache")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="check cache for a unit")
    p_check.add_argument("run_id")
    p_check.add_argument("unit")
    p_check.add_argument("--hash")
    p_check.add_argument("--files", nargs="+")
    p_check.set_defaults(func=cmd_check)

    p_save = sub.add_parser("save", help="save a build result to cache")
    p_save.add_argument("run_id")
    p_save.add_argument("unit")
    p_save.add_argument("--hash")
    p_save.add_argument("--status", default="complete")
    p_save.add_argument("--files", nargs="+")
    p_save.set_defaults(func=cmd_save)

    p_hash = sub.add_parser("hash", help="compute combined hash for files")
    p_hash.add_argument("--files", nargs="+", required=True)
    p_hash.set_defaults(func=cmd_hash)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
