#!/usr/bin/env python3
"""factory_features.py — Read AIDLC feature flags.

Feature flags live in `.aidlc-orchestrator/budgets/default.yaml` under a top-level
`features:` map. Each flag is a `<key>: <bool>` pair.

Resolution order:
    1. Env var `AIDLC_FEATURE_<KEY_UPPER>` (KEY uppercased, dashes → underscores).
       Values: 1/0, true/false, yes/no, on/off.
    2. budgets/default.yaml `features.<key>`.
    3. Built-in default (False).

Usage:
    python3 aidlc-scripts/factory_features.py get <key>            # prints "true" or "false", exit 0
    python3 aidlc-scripts/factory_features.py is-set <key>         # exit 0 if true, 1 if false
    python3 aidlc-scripts/factory_features.py list                 # print all flags as KEY=VALUE

Exit codes:
    0  on success (or true for is-set)
    1  flag is false (only for is-set subcommand)
    2  usage error / unknown flag
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

# Bake in the canonical set of known flags so typos are caught.
KNOWN_FLAGS: set[str] = {
    "content_validator_strict",
    "slo_blocking",
    "knowledge_promotion",
    "shared_corpus_injection",
}

TRUTHY = {"1", "true", "yes", "on", "y", "t"}
FALSY = {"0", "false", "no", "off", "n", "f", ""}


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_features: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _coerce_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    # Unknown — treat as false but warn
    print(f"factory_features: warning: unrecognized truth value {v!r} — coerced to False",
          file=sys.stderr)
    return False


def _budget_path(repo_root: Path) -> Path:
    return repo_root / ".aidlc-orchestrator" / "budgets" / "default.yaml"


def _load_budget_features(repo_root: Path) -> dict[str, bool]:
    p = _budget_path(repo_root)
    if not p.exists():
        return {}
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _die(f"could not parse {p}: {exc}")
    return {k: _coerce_bool(v) for k, v in (data.get("features") or {}).items()}


def _env_override(flag: str) -> bool | None:
    env_key = "AIDLC_FEATURE_" + flag.upper().replace("-", "_")
    if env_key in os.environ:
        return _coerce_bool(os.environ[env_key])
    return None


def resolve(flag: str, repo_root: Path | None = None) -> bool:
    """Return the effective value of a feature flag."""
    if flag not in KNOWN_FLAGS:
        _die(f"unknown flag: {flag} (known: {sorted(KNOWN_FLAGS)})")
    env = _env_override(flag)
    if env is not None:
        return env
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    budget = _load_budget_features(repo_root)
    return budget.get(flag, False)


def list_all(repo_root: Path | None = None) -> dict[str, bool]:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    return {f: resolve(f, repo_root) for f in sorted(KNOWN_FLAGS)}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_features.py",
        description="Read AIDLC feature flags.",
    )
    parser.add_argument(
        "--repo-root", default=None,
        help="Repo root (default: auto-detect from script location)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("get", help="print 'true' or 'false' for a flag")
    pg.add_argument("flag")

    pis = sub.add_parser("is-set", help="exit 0 if flag is true, 1 if false")
    pis.add_argument("flag")

    sub.add_parser("list", help="print every known flag as KEY=VALUE")

    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None

    if args.cmd == "get":
        v = resolve(args.flag, repo_root)
        print("true" if v else "false")
        sys.exit(0)
    elif args.cmd == "is-set":
        v = resolve(args.flag, repo_root)
        sys.exit(0 if v else 1)
    elif args.cmd == "list":
        for k, v in list_all(repo_root).items():
            print(f"{k}={'true' if v else 'false'}")
        sys.exit(0)


if __name__ == "__main__":
    main()
