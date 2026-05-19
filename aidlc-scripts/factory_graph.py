#!/usr/bin/env python3
"""factory_graph.py — Unit Dependency Graph Computer for LARGE-tier runs.

Reads the unit-decomposer output handoff, builds a dependency DAG from each
unit's `dependencies[]` field, runs Kahn's topological sort, and emits a list
of "waves" — sets of units that can be spawned in parallel by the orchestrator.

Usage
-----
    factory_graph.py compute <run-id> [--apply]
    factory_graph.py show <run-id>

Subcommands
-----------
    compute   Reads unit-decomposer output, builds DAG, topo-sorts into waves.
              With --apply, writes the result to manifest.unit_waves.
    show      Prints the current manifest.unit_waves (debug helper).

Wave semantics
--------------
    Wave 0: units with no dependencies — spawn in parallel first.
    Wave N: units whose dependencies are all in waves 0..N-1.
    Output shape: [[u1, u2], [u3], [u4, u5]]

Exit codes
----------
    0   Waves computed (and written if --apply).
    1   Cycle detected, undefined dependency, or input error.
    2   Usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / ".aidlc-orchestrator" / "runs"


def _die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _handoff_path(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "handoffs" / "unit-decomposer.output.yaml"


def _manifest_path(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "manifest.yaml"


def _load_units(run_id: str) -> list[dict]:
    p = _handoff_path(run_id)
    if not p.exists():
        _die(
            f"unit-decomposer output not found: {p}\n"
            "Run unit-decomposer stage before calling factory_graph.py."
        )
    raw = yaml.safe_load(p.read_text()) or {}
    units = raw.get("units_decomposed")
    if not units:
        _die(f"units_decomposed missing or empty in {p}")
    return units


def compute_waves(units: list[dict]) -> list[list[str]]:
    """Kahn's algorithm. Returns waves[] or raises ValueError on bad input."""
    names = [u["name"] for u in units]
    name_set = set(names)

    deps: dict[str, set[str]] = {}
    for u in units:
        unit_deps = u.get("dependencies") or []
        if u["name"] in unit_deps:
            raise ValueError(
                f"unit {u['name']!r} declares dependency on itself (self-loop)"
            )
        unknown = [d for d in unit_deps if d not in name_set]
        if unknown:
            raise ValueError(
                f"unit {u['name']!r} declares dependency on undefined unit(s): {unknown}"
            )
        deps[u["name"]] = set(unit_deps)

    waves: list[list[str]] = []
    remaining = dict(deps)

    while remaining:
        ready = sorted([n for n, d in remaining.items() if not d])
        if not ready:
            # Cycle: every remaining unit has at least one unsatisfied dep
            cycle_members = sorted(remaining.keys())
            raise ValueError(
                f"cycle detected in unit dependency graph; "
                f"remaining units with unsatisfied deps: {cycle_members}"
            )
        waves.append(ready)
        for n in ready:
            remaining.pop(n)
        for n in remaining:
            remaining[n] -= set(ready)

    return waves


def _apply_to_manifest(run_id: str, waves: list[list[str]]) -> None:
    mp = _manifest_path(run_id)
    if not mp.exists():
        _die(f"manifest not found: {mp} (run factory_run.py init first)")

    state = yaml.safe_load(mp.read_text()) or {}
    state["unit_waves"] = waves
    state["unit_wave_count"] = len(waves)
    state["unit_max_parallelism"] = max((len(w) for w in waves), default=0)

    tmp = mp.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(state, default_flow_style=False, sort_keys=False))
    tmp.rename(mp)
    print(
        f"[UnitGraph] Applied {len(waves)} wave(s), "
        f"max_parallelism={state['unit_max_parallelism']}",
        file=sys.stderr,
    )


def cmd_compute(args: argparse.Namespace) -> None:
    units = _load_units(args.run_id)
    try:
        waves = compute_waves(units)
    except ValueError as e:
        _die(str(e))

    result = {
        "run_id": args.run_id,
        "wave_count": len(waves),
        "max_parallelism": max((len(w) for w in waves), default=0),
        "waves": waves,
    }
    print(json.dumps(result, indent=2))

    if args.apply:
        _apply_to_manifest(args.run_id, waves)


def cmd_show(args: argparse.Namespace) -> None:
    mp = _manifest_path(args.run_id)
    if not mp.exists():
        _die(f"manifest not found: {mp}")
    state = yaml.safe_load(mp.read_text()) or {}
    waves = state.get("unit_waves") or []
    print(json.dumps({
        "run_id": args.run_id,
        "wave_count": len(waves),
        "max_parallelism": max((len(w) for w in waves), default=0),
        "waves": waves,
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="factory_graph.py",
        description="Compute unit dependency waves for LARGE-tier parallel codegen.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_compute = sub.add_parser("compute", help="compute waves from unit-decomposer output")
    p_compute.add_argument("run_id")
    p_compute.add_argument("--apply", action="store_true",
                           help="write waves to manifest.unit_waves")
    p_compute.set_defaults(func=cmd_compute)

    p_show = sub.add_parser("show", help="print current manifest.unit_waves")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_show)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
