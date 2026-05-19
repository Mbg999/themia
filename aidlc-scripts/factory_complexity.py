#!/usr/bin/env python3
"""factory_complexity.py — Complexity Tier Router for the AIDLC Orchestrator.

Reads the requirements-analyst output handoff and assigns a complexity tier
(TINY / SMALL / MEDIUM / LARGE). The orchestrator uses this to route to
FAST_PATH (TINY) or skip stages, reduce gate count, and cap the token budget.

Usage
-----
    factory_complexity.py <run-id> [--apply]

    <run-id>   The run ID (directory name under .aidlc-orchestrator/runs/).
    --apply    Write the tier and token cap into the run's budget.yaml in
               addition to printing the JSON decision.

Output (stdout)
---------------
    JSON object:
    {
      "tier": "TINY" | "SMALL" | "MEDIUM" | "LARGE",
      "fast_path": true | false,
      "skip_stages": [...],
      "merge_codegen_gate": true | false,
      "reviewer_pool": [...],
      "tokens_max": <int>,
      "wall_clock_max_min": <int>,
      "rationale": "<scope> + <complexity> → <tier>"
    }

Exit codes
----------
    0  Success — tier determined, JSON printed.
    1  Input error — requirements output missing or request_classification absent.

Tier rules
----------
    TINY:   scope == Single File AND complexity == Trivial → FAST_PATH
    SMALL:  scope in {Single File, Single Component}
            AND complexity in {Trivial, Simple}  (but not both at TINY level)
    MEDIUM: scope in {Multiple Components}
            OR complexity == Moderate
    LARGE:  scope in {System-wide, Cross-system}
            OR complexity == Complex
    Tie-break: take the higher tier when scope and complexity disagree.
    TINY is only assigned when BOTH dimensions independently resolve to TINY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
_AIDLC_ROOT = Path(os.environ["AIDLC_ROOT"]) if "AIDLC_ROOT" in os.environ else REPO_ROOT
RUNS_ROOT = _AIDLC_ROOT / ".aidlc-orchestrator" / "runs"

# Tier ordering (higher index = higher tier)
_TIER_RANK = {"TINY": 0, "SMALL": 1, "MEDIUM": 2, "LARGE": 3}

_SCOPE_TIER: dict[str, str] = {
    "Single File": "TINY",
    "Single Component": "SMALL",
    "Multiple Components": "MEDIUM",
    "System-wide": "LARGE",
    "Cross-system": "LARGE",
}

_COMPLEXITY_TIER: dict[str, str] = {
    "Trivial": "TINY",
    "Simple": "SMALL",
    "Moderate": "MEDIUM",
    "Complex": "LARGE",
}

_ROUTING: dict[str, dict] = {
    "TINY": {
        "fast_path": True,
        "skip_stages": ["story-writer", "unit-decomposer", "workflow-planner", "build-test-agent"],
        "merge_codegen_gate": True,
        "reviewer_pool": [],
        "tokens_max": 100_000,
        "wall_clock_max_min": 10,
    },
    "SMALL": {
        "fast_path": False,
        "skip_stages": ["story-writer", "unit-decomposer"],
        "merge_codegen_gate": True,
        "reviewer_pool": ["reviewer-code"],
        "tokens_max": 500_000,
        "wall_clock_max_min": 30,
    },
    "MEDIUM": {
        "fast_path": False,
        "skip_stages": ["story-writer"],
        "merge_codegen_gate": False,
        "reviewer_pool": ["reviewer-code", "reviewer-security", "reviewer-simplifier"],
        "tokens_max": 1_500_000,
        "wall_clock_max_min": 90,
    },
    "LARGE": {
        "fast_path": False,
        "skip_stages": [],
        "merge_codegen_gate": False,
        "reviewer_pool": [
            "reviewer-code",
            "reviewer-security",
            "reviewer-performance",
            "reviewer-simplifier",
        ],
        "tokens_max": 5_000_000,
        "wall_clock_max_min": 240,
    },
}


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _resolve_tier(scope: str | None, complexity: str | None) -> tuple[str, str]:
    """Return (tier, rationale). Tie-break: take the higher tier."""
    scope_tier = _SCOPE_TIER.get(scope or "", "MEDIUM")
    complexity_tier = _COMPLEXITY_TIER.get(complexity or "", "MEDIUM")
    if scope and scope not in _SCOPE_TIER:
        print(f"WARNING: unrecognized scope {scope!r}, falling back to MEDIUM", file=sys.stderr)
    if complexity and complexity not in _COMPLEXITY_TIER:
        print(f"WARNING: unrecognized complexity {complexity!r}, falling back to MEDIUM", file=sys.stderr)

    if _TIER_RANK[scope_tier] >= _TIER_RANK[complexity_tier]:
        winner = scope_tier
        rationale = f"scope={scope!r} → {scope_tier} (wins tie-break over complexity={complexity!r} → {complexity_tier})" if scope_tier != complexity_tier else f"scope={scope!r} + complexity={complexity!r} → {scope_tier}"
    else:
        winner = complexity_tier
        rationale = f"complexity={complexity!r} → {complexity_tier} (wins tie-break over scope={scope!r} → {scope_tier})"

    return winner, rationale


def cmd_assess(args: argparse.Namespace) -> None:
    run_dir = RUNS_ROOT / args.run_id
    handoff_path = run_dir / "handoffs" / "requirements-analyst.output.yaml"

    if not handoff_path.exists():
        _die(
            f"requirements-analyst output not found: {handoff_path}\n"
            "Run requirements-analyst stage before calling factory_complexity.py."
        )

    raw = yaml.safe_load(handoff_path.read_text()) or {}
    classification = raw.get("request_classification")
    if not classification:
        _die(
            f"request_classification missing in {handoff_path}\n"
            "The requirements-analyst output does not contain a request_classification block."
        )

    scope = classification.get("scope")
    complexity = classification.get("complexity")
    tier, rationale = _resolve_tier(scope, complexity)

    routing = _ROUTING[tier]
    result = {
        "tier": tier,
        "fast_path": routing["fast_path"],
        "skip_stages": routing["skip_stages"],
        "merge_codegen_gate": routing["merge_codegen_gate"],
        "reviewer_pool": routing["reviewer_pool"],
        "tokens_max": routing["tokens_max"],
        "wall_clock_max_min": routing["wall_clock_max_min"],
        "rationale": rationale,
    }

    print(json.dumps(result, indent=2))

    if args.apply:
        _apply_to_budget(args.run_id, tier, routing)


def _apply_to_budget(run_id: str, tier: str, routing: dict) -> None:
    budget_path = RUNS_ROOT / run_id / "budget.yaml"
    if not budget_path.exists():
        print(
            f"[ComplexityGov] budget.yaml not found at {budget_path} — skipping apply",
            file=sys.stderr,
        )
        return

    state = yaml.safe_load(budget_path.read_text()) or {}
    state.setdefault("budget", {})
    state["budget"]["tokens_max"] = routing["tokens_max"]
    state["budget"]["wall_clock_max_min"] = routing["wall_clock_max_min"]
    state["complexity_tier"] = tier

    tmp = budget_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(state, default_flow_style=False, sort_keys=False))
    tmp.replace(budget_path)
    print(
        f"[ComplexityGov] Applied tier={tier}: tokens_max={routing['tokens_max']:,}, "
        f"wall_clock_max_min={routing['wall_clock_max_min']}",
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="factory_complexity.py",
        description="Assign a complexity tier to an AIDLC run based on requirements output.",
    )
    p.add_argument("run_id", help="Run ID (directory under .aidlc-orchestrator/runs/)")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write tier + token cap into the run's budget.yaml",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    cmd_assess(args)


if __name__ == "__main__":
    main()
