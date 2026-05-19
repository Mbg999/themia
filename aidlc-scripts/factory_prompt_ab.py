#!/usr/bin/env python3
"""factory_prompt_ab.py — Prompt A/B variant harness for stage agents.

Three subcommands:

    discover <stage-name>
        List variant prompts for a stage. Variants live at
        `.claude/agents/stage/<stage-name>.experiment/<variant>.md`.

    activate <stage-name> <variant>
        Swap the active stage agent to a variant by writing the variant body to
        `.claude/agents/stage/<stage-name>.md`. The original is preserved at
        `.claude/agents/stage/<stage-name>.baseline.md` (first activation only).
        Run your `/factory-<command>` flow after activation; the next spawn uses
        the variant.

    restore <stage-name>
        Restore the baseline stage agent from `.baseline.md`.

    compare <stage-name> <run-dir-a> <run-dir-b>
        Compute side-by-side metrics for the same stage across two completed
        runs. Uses cost blocks and audit_entries from each run's handoff
        files. No new spawns are performed.

This tool is honest about what it can do: Python cannot invoke Claude Code's
Task() spawn mechanism directly. The harness handles variant management +
post-hoc comparison; the user runs each variant via the regular `/factory-*`
commands.

Usage:
    python3 aidlc-scripts/factory_prompt_ab.py discover requirements-analyst
    python3 aidlc-scripts/factory_prompt_ab.py activate requirements-analyst v2-socratic-first
    python3 aidlc-scripts/factory_prompt_ab.py compare requirements-analyst \\
        .aidlc-orchestrator/runs/baseline-run \\
        .aidlc-orchestrator/runs/variant-run

Exit codes:
    0  success
    1  variant has unfavorable metrics (compare subcommand only)
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_prompt_ab: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_yaml(p: Path) -> dict:
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _stage_path(repo_root: Path, stage: str) -> Path:
    return repo_root / ".claude" / "agents" / "stage" / f"{stage}.md"


def _baseline_path(repo_root: Path, stage: str) -> Path:
    return repo_root / ".claude" / "agents" / "stage" / f"{stage}.baseline.md"


def _experiment_dir(repo_root: Path, stage: str) -> Path:
    return repo_root / ".claude" / "agents" / "stage" / f"{stage}.experiment"


def cmd_discover(args, repo_root: Path) -> int:
    exp_dir = _experiment_dir(repo_root, args.stage)
    if not exp_dir.is_dir():
        print(
            f"No experiment dir for stage '{args.stage}'.\n"
            f"To add a variant, create: {exp_dir}/<variant-name>.md"
        )
        return 0
    variants = sorted(exp_dir.glob("*.md"))
    if not variants:
        print(f"experiment dir exists but is empty: {exp_dir}")
        return 0
    baseline = _baseline_path(repo_root, args.stage)
    active = _stage_path(repo_root, args.stage)
    active_label = "(baseline)" if baseline.exists() and active.read_text(encoding="utf-8") == baseline.read_text(encoding="utf-8") else "(variant active)"
    print(f"Stage: {args.stage}  {active_label}")
    print(f"  baseline: {'preserved' if baseline.exists() else 'not yet swapped'}")
    print(f"  variants ({len(variants)}):")
    for v in variants:
        size = v.stat().st_size
        print(f"    - {v.stem}  ({size} bytes)")
    return 0


def cmd_activate(args, repo_root: Path) -> int:
    stage_p = _stage_path(repo_root, args.stage)
    baseline_p = _baseline_path(repo_root, args.stage)
    variant_p = _experiment_dir(repo_root, args.stage) / f"{args.variant}.md"

    if not variant_p.exists():
        _die(f"variant not found: {variant_p}")
    if not stage_p.exists():
        _die(f"stage agent not found: {stage_p}")

    # Preserve baseline on first activation
    if not baseline_p.exists():
        shutil.copy2(stage_p, baseline_p)
        print(f"baseline preserved: {baseline_p.relative_to(repo_root)}")

    shutil.copy2(variant_p, stage_p)
    print(f"activated variant '{args.variant}' for {args.stage}")
    print(f"  source: {variant_p.relative_to(repo_root)}")
    print(f"  active: {stage_p.relative_to(repo_root)}")
    print(f"\nRun your /factory-<cmd> flow now; next spawn will use the variant.")
    print(f"Restore with: factory_prompt_ab.py restore {args.stage}")
    return 0


def cmd_restore(args, repo_root: Path) -> int:
    stage_p = _stage_path(repo_root, args.stage)
    baseline_p = _baseline_path(repo_root, args.stage)
    if not baseline_p.exists():
        _die(f"no baseline preserved for {args.stage} — nothing to restore")
    shutil.copy2(baseline_p, stage_p)
    baseline_p.unlink()
    print(f"restored baseline for {args.stage}")
    return 0


def _stage_metrics(run_dir: Path, stage: str) -> dict:
    """Aggregate handoff metrics for one stage in one run."""
    hd = run_dir / "handoffs"
    files = sorted(hd.glob(f"{stage}.output*.yaml")) if hd.is_dir() else []
    files = [f for f in files if ".cancelled-" not in f.name and ".replay-" not in f.name]

    tokens_in = tokens_out = retries = 0
    wall_min = 0.0
    statuses: list[str] = []
    audit_lines: list[str] = []

    for f in files:
        h = _load_yaml(f)
        c = h.get("cost") or {}
        tokens_in += int(c.get("tokens_in") or 0)
        tokens_out += int(c.get("tokens_out") or 0)
        wall_min += float(c.get("wall_clock_min") or 0)
        retries += int(c.get("retries_used") or 0)
        statuses.append(h.get("status", ""))
        audit_lines.extend(str(e) for e in (h.get("audit_entries") or []))

    audit_joined = "\n".join(audit_lines)
    return {
        "handoff_count": len(files),
        "tokens_total": tokens_in + tokens_out,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "wall_min": round(wall_min, 1),
        "retries": retries,
        "statuses": statuses,
        "final_status": statuses[-1] if statuses else "missing",
        "has_redflag": "[RedFlag]" in audit_joined,
        "has_content_fail": "[ContentValidator]" in audit_joined and "FAIL" in audit_joined,
        "rationalization_count": audit_joined.count("[Rationalization-rejected]"),
    }


def cmd_compare(args, repo_root: Path) -> int:
    a = Path(args.run_dir_a).resolve()
    b = Path(args.run_dir_b).resolve()
    if not (a / "handoffs").is_dir():
        _die(f"run dir A has no handoffs/: {a}")
    if not (b / "handoffs").is_dir():
        _die(f"run dir B has no handoffs/: {b}")

    m_a = _stage_metrics(a, args.stage)
    m_b = _stage_metrics(b, args.stage)

    def _delta(field: str, lower_is_better: bool = True) -> str:
        va, vb = m_a[field], m_b[field]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if va == 0:
                return "n/a"
            pct = (vb - va) / va * 100
            sign = "+" if pct >= 0 else ""
            mark = ""
            if lower_is_better:
                mark = "  ⬇" if pct < -5 else ("  ⬆" if pct > 5 else "")
            else:
                mark = "  ⬆" if pct > 5 else ("  ⬇" if pct < -5 else "")
            return f"{sign}{pct:.1f}%{mark}"
        return ""

    if args.json:
        print(json.dumps({"A": m_a, "B": m_b, "stage": args.stage}, indent=2))
        return 0

    print(f"## A/B compare — stage: {args.stage}")
    print(f"  A: {a.name}")
    print(f"  B: {b.name}\n")
    print(f"  {'metric':28} {'A':>14} {'B':>14}   Δ (B vs A)")
    print(f"  {'-'*28} {'-'*14:>14} {'-'*14:>14}   {'-'*15}")
    for label, field, lower in [
        ("tokens_total",          "tokens_total",          True),
        ("tokens_in",             "tokens_in",             True),
        ("tokens_out",            "tokens_out",            True),
        ("wall_min",              "wall_min",              True),
        ("retries",               "retries",               True),
        ("rationalization_count", "rationalization_count", False),  # more rejections = more rigor
    ]:
        va, vb = m_a[field], m_b[field]
        print(f"  {label:28} {va:>14} {vb:>14}   {_delta(field, lower)}")
    print(f"  {'final_status':28} {str(m_a['final_status']):>14} {str(m_b['final_status']):>14}")
    print(f"  {'has_redflag':28} {str(m_a['has_redflag']):>14} {str(m_b['has_redflag']):>14}")
    print(f"  {'has_content_fail':28} {str(m_a['has_content_fail']):>14} {str(m_b['has_content_fail']):>14}")

    # Verdict: B is unfavorable if it grew tokens significantly without quality gain
    if (m_a["tokens_total"] > 0
            and m_b["tokens_total"] > m_a["tokens_total"] * 1.20
            and m_b["rationalization_count"] <= m_a["rationalization_count"]):
        print("\n  ⚠ variant B uses >20% more tokens without producing more rigor "
              "(rationalization_count did not increase). Consider reverting.")
        return 1
    if m_b["has_content_fail"] and not m_a["has_content_fail"]:
        print("\n  ⚠ variant B introduced a [ContentValidator] FAIL not present in baseline.")
        return 1

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_prompt_ab.py",
        description="Prompt A/B variant harness for AIDLC stage agents.",
    )
    parser.add_argument("--repo-root", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("discover")
    pd.add_argument("stage")
    pd.set_defaults(func=cmd_discover)

    pa = sub.add_parser("activate")
    pa.add_argument("stage")
    pa.add_argument("variant")
    pa.set_defaults(func=cmd_activate)

    pr = sub.add_parser("restore")
    pr.add_argument("stage")
    pr.set_defaults(func=cmd_restore)

    pc = sub.add_parser("compare")
    pc.add_argument("stage")
    pc.add_argument("run_dir_a")
    pc.add_argument("run_dir_b")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parent.parent

    sys.exit(args.func(args, repo_root))


if __name__ == "__main__":
    main()
