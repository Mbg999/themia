#!/usr/bin/env python3
"""factory_cost_estimate.py — Pre-flight cost projection for AIDLC runs.

Projects token spend and wall-clock for a planned run BEFORE construction
kicks off. The orchestrator surfaces this estimate on the plan-approval
surface so the user can sanity-check before committing to long runs.

Inputs:
    1. The run manifest (`<run-dir>/manifest.yaml`) — provides current_stage,
       project_profile, completed_stages.
    2. The plan handoff (`workflow-planner.output.yaml`) — provides unit_count,
       task_count. Optional.
    3. Per-stage budgets (`.aidlc-orchestrator/budgets/default.yaml`).
    4. Historical telemetry (`<run-dir>/manifest.yaml` cost blocks from prior
       runs) — uses median where available, falls back to budget defaults.

Output:
    Markdown report to stdout (or --out <file>). Format:
        ## Pre-flight cost estimate — <run-id>
        | Stage | Est. tokens | Est. min | Confidence | Source |
        | --- | --- | --- | --- | --- |
        | requirements-analyst | 250,000 | 8 | high | 4 historical samples |
        ...
        **Total: ~1,800,000 tokens · ~45 min**

Usage:
    python3 aidlc-scripts/factory_cost_estimate.py --run-dir <run-dir> [--out <file>]
    python3 aidlc-scripts/factory_cost_estimate.py --manifest <path> --plan <path>

Exit codes:
    0  estimate produced
    1  cost projection over a configured ceiling
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

# Default per-stage token estimates when no telemetry is available.
# Conservative — used as upper-bound fallback.
DEFAULT_TOKEN_ESTIMATES = {
    "workspace-scout":       (50_000,  5),
    "reverse-engineer":     (300_000, 25),
    "requirements-analyst": (250_000, 12),
    "story-writer":         (100_000,  8),
    "workflow-planner":     (200_000, 15),
    "unit-decomposer":      (100_000,  8),
    "code-generator":       (500_000, 30),  # per unit
    "build-test-agent":     (200_000, 15),  # per unit
    "reviewer-code":        (100_000,  8),
    "reviewer-security":    (100_000,  8),
    "reviewer-performance": (100_000,  8),
    "reviewer-simplifier":  (100_000,  8),
    "ship-agent":           (150_000, 12),
}

# Stages that scale with unit count (×N for N units).
PER_UNIT_STAGES = {"code-generator", "build-test-agent"}

# Stages that are conditional on project profile.
CONDITIONAL_STAGES = {"reverse-engineer", "story-writer", "unit-decomposer"}


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_cost_estimate: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_yaml(p: Path) -> dict:
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _die(f"could not parse {p}: {exc}")


def _runs_root(repo_root: Path) -> Path:
    return repo_root / ".aidlc-orchestrator" / "runs"


def _historical_samples(repo_root: Path, stage: str) -> list[tuple[int, float]]:
    """Read cost blocks from completed runs for the given stage.

    Returns list of (tokens, wall_clock_min) tuples.
    """
    runs = _runs_root(repo_root)
    if not runs.is_dir():
        return []
    samples: list[tuple[int, float]] = []
    for run_dir in runs.iterdir():
        if not run_dir.is_dir():
            continue
        mp = run_dir / "manifest.yaml"
        if not mp.exists():
            continue
        try:
            manifest = _load_yaml(mp)
        except SystemExit:
            continue
        # Cost blocks may live under manifest['costs'][<stage>] in older runs
        # or under handoff files. Look in both places.
        costs = manifest.get("costs", {}) or {}
        entry = costs.get(stage)
        if entry and isinstance(entry, dict):
            tokens = (entry.get("tokens_in") or 0) + (entry.get("tokens_out") or 0)
            wall = float(entry.get("wall_clock_min") or 0)
            if tokens > 0:
                samples.append((tokens, wall))
        # Look at handoff files too
        hd = run_dir / "handoffs"
        if hd.is_dir():
            for hf in hd.glob(f"{stage}.output*.yaml"):
                try:
                    h = _load_yaml(hf)
                except SystemExit:
                    continue
                c = h.get("cost") or {}
                tokens = (c.get("tokens_in") or 0) + (c.get("tokens_out") or 0)
                wall = float(c.get("wall_clock_min") or 0)
                if tokens > 0:
                    samples.append((tokens, wall))
    return samples


def _stage_estimate(repo_root: Path, stage: str) -> tuple[int, float, str, str]:
    """Return (tokens, wall_min, confidence, source) for one stage."""
    samples = _historical_samples(repo_root, stage)
    if len(samples) >= 3:
        tokens = int(statistics.median(s[0] for s in samples))
        wall = statistics.median(s[1] for s in samples)
        return (tokens, wall, "high", f"{len(samples)} historical samples")
    if len(samples) >= 1:
        tokens = int(statistics.median(s[0] for s in samples))
        wall = statistics.median(s[1] for s in samples)
        return (tokens, wall, "medium", f"{len(samples)} historical sample(s)")
    # Fallback to defaults
    default = DEFAULT_TOKEN_ESTIMATES.get(stage, (100_000, 5))
    return (default[0], default[1], "low", "static default")


def project(
    repo_root: Path,
    *,
    unit_count: int = 1,
    profile: dict | None = None,
) -> dict:
    """Build the cost projection.

    profile: optional project profile {ui: bool, api: bool, has_legacy: bool}
             used to skip conditional stages.
    """
    profile = profile or {}
    has_legacy = profile.get("has_legacy", False)
    is_multi_unit = unit_count >= 2

    rows: list[dict] = []
    for stage in DEFAULT_TOKEN_ESTIMATES:
        # Skip conditional stages that don't apply to this profile
        if stage == "reverse-engineer" and not has_legacy:
            continue
        if stage == "unit-decomposer" and not is_multi_unit:
            continue

        tokens, wall, conf, src = _stage_estimate(repo_root, stage)
        multiplier = unit_count if stage in PER_UNIT_STAGES else 1
        rows.append({
            "stage": stage,
            "tokens": tokens * multiplier,
            "wall_min": round(wall * multiplier, 1),
            "multiplier": multiplier,
            "confidence": conf,
            "source": src,
        })

    total_tokens = sum(r["tokens"] for r in rows)
    total_wall = sum(r["wall_min"] for r in rows)
    return {
        "rows": rows,
        "total_tokens": total_tokens,
        "total_wall_min": round(total_wall, 1),
        "unit_count": unit_count,
        "profile": profile,
    }


def render_markdown(projection: dict, run_id: str = "<run-id>") -> str:
    lines = [
        f"## Pre-flight cost estimate — {run_id}",
        "",
        f"Units: **{projection['unit_count']}** · Profile: `{projection['profile'] or 'default'}`",
        "",
        "| Stage | Est. tokens | Est. min | × | Confidence | Source |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in projection["rows"]:
        lines.append(
            f"| {r['stage']} | {r['tokens']:,} | {r['wall_min']} | "
            f"{r['multiplier']} | {r['confidence']} | {r['source']} |"
        )
    lines += [
        "",
        f"**Total: ~{projection['total_tokens']:,} tokens · ~{projection['total_wall_min']} min**",
        "",
        "*Confidence: high = ≥3 historical samples; medium = 1–2 samples; "
        "low = static default.*",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_cost_estimate.py",
        description="Pre-flight cost projection for AIDLC runs.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--run-dir", help="path to run directory (auto-discovers manifest + plan)")
    src.add_argument("--manifest", help="path to manifest.yaml")
    parser.add_argument("--plan", help="path to workflow-planner.output.yaml")
    parser.add_argument("--repo-root", help="repo root (default: auto-detect)")
    parser.add_argument("--unit-count", type=int, default=None,
                        help="override unit count (default: from plan)")
    parser.add_argument("--ceiling-tokens", type=int, default=None,
                        help="fail with exit 1 if total exceeds this many tokens")
    parser.add_argument("--out", help="write markdown to file (default: stdout)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parent.parent

    manifest: dict = {}
    plan: dict = {}
    run_id = "unknown"

    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        run_id = run_dir.name
        mp = run_dir / "manifest.yaml"
        if mp.exists():
            manifest = _load_yaml(mp)
        pp = run_dir / "handoffs" / "workflow-planner.output.yaml"
        if pp.exists():
            plan = _load_yaml(pp)
    if args.manifest:
        manifest = _load_yaml(Path(args.manifest).resolve())
        run_id = manifest.get("run_id", run_id)
    if args.plan:
        plan = _load_yaml(Path(args.plan).resolve())

    profile = manifest.get("project_profile") or {}
    unit_count = args.unit_count or plan.get("unit_count") or 1

    proj = project(repo_root, unit_count=unit_count, profile=profile)

    if args.json:
        out_text = json.dumps({**proj, "run_id": run_id}, indent=2)
    else:
        out_text = render_markdown(proj, run_id=run_id)

    if args.out:
        Path(args.out).write_text(out_text + "\n", encoding="utf-8")
    else:
        print(out_text)

    if args.ceiling_tokens and proj["total_tokens"] > args.ceiling_tokens:
        print(
            f"\nfactory_cost_estimate: projection {proj['total_tokens']:,} > "
            f"ceiling {args.ceiling_tokens:,}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
