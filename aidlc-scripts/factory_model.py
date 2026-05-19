#!/usr/bin/env python3
"""factory_model.py — Per-stage model router for the AIDLC Orchestrator.

Reads the stage model assignment from budgets/default.yaml and returns the
recommended model for a given stage. The orchestrator injects this into
input handoffs as `model_override`.

Usage
-----
    factory_model.py resolve <stage> [--budget PATH]

    Prints the model name to stdout (e.g. "opus", "sonnet").
    Exit codes:
        0 — model resolved
        1 — stage not found in budget (prints default)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))
DEFAULT_BUDGET = REPO_ROOT / ".aidlc-orchestrator" / "budgets" / "default.yaml"

# Fallback when budget config is missing or stage not found.
# "default" lets the tool use its configured default model.
DEFAULT_MODEL = "default"


def resolve(stage: str, budget_path: Path | None = None) -> str:
    """Return the recommended model for a stage.

    Resolution order:
        1. AIDLC_MODEL_<STAGE> env var (uppercased stage, dashes → underscores)
        2. AIDLC_DEFAULT_MODEL env var (global override for all stages)
        3. Budget file per_stage[<stage>].model
        4. Budget file per_stage["custom-agent"].model (fallback for unknown stages)
        5. DEFAULT_MODEL
    """
    env_key = f"AIDLC_MODEL_{stage.upper().replace('-', '_')}"
    env_model = os.environ.get(env_key)
    if env_model:
        return env_model

    global_default = os.environ.get("AIDLC_DEFAULT_MODEL")
    if global_default:
        return global_default

    bp = budget_path or DEFAULT_BUDGET
    if bp.exists() and yaml:
        try:
            budget = yaml.safe_load(bp.read_text())
            per_stage = budget.get("per_stage", {})
            # reviewer-* wildcard fallback
            entry = per_stage.get(stage)
            if entry and "model" in entry:
                return entry["model"]
            if not entry and stage.startswith("reviewer-"):
                entry = per_stage.get("reviewer-code")
            if not entry:
                entry = per_stage.get("custom-agent")
            if entry and "model" in entry:
                return entry["model"]
        except Exception as exc:
            print(f"WARNING: failed to parse budget config {bp}: {exc}", file=sys.stderr)

    return DEFAULT_MODEL


def main() -> None:
    p = argparse.ArgumentParser(description="AIDLC Orchestrator — Model Router")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_resolve = sub.add_parser("resolve", help="resolve model for a stage")
    p_resolve.add_argument("stage", help="stage name (e.g. code-generator)")
    p_resolve.add_argument("--budget", type=str, default=None,
                           help="path to budget YAML (default: budgets/default.yaml)")
    p_resolve.set_defaults(func=cmd_resolve)

    args = p.parse_args()
    args.func(args)


def cmd_resolve(args: argparse.Namespace) -> None:
    budget_path = Path(args.budget).resolve() if args.budget else None
    model = resolve(args.stage, budget_path)
    print(model)
    sys.exit(0)


if __name__ == "__main__":
    main()
