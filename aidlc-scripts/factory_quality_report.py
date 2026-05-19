#!/usr/bin/env python3
"""factory_quality_report.py — Aggregate run-quality telemetry across all runs.

Walks every run under `.aidlc-orchestrator/runs/<run-id>/`, reads its audit
log (via factory_evidence_extract) and cost data (from handoff YAMLs), and
emits a markdown report of per-stage health metrics over time.

Metrics computed per stage:
    needs_human_rate     fraction of runs where the stage emitted status:needs_human
    blocked_rate         fraction of runs where the stage emitted status:blocked
    failed_rate          fraction of runs where the stage emitted status:failed
    evidence_fail_rate   fraction with [ContentValidator] FAIL audit entry
    rationalization_rate fraction with ≥1 [Rationalization-rejected] entry
    redflag_rate         fraction with ≥1 [RedFlag] entry
    token_p50, token_p95
    wall_min_p50, wall_min_p95
    retry_p50, retry_p95

Output:
    Markdown to stdout or `aidlc-docs/quality/<YYYY-MM>-stage-metrics.md`.

Usage:
    python3 aidlc-scripts/factory_quality_report.py
    python3 aidlc-scripts/factory_quality_report.py --out aidlc-docs/quality/2026-05-stage-metrics.md
    python3 aidlc-scripts/factory_quality_report.py --json

Exit codes:
    0  report produced
    1  no runs found
    2  usage error
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_quality_report: error: {msg}", file=sys.stderr)
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


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return float(sorted_v[f])
    d0 = sorted_v[f] * (c - k)
    d1 = sorted_v[c] * (k - f)
    return float(d0 + d1)


def _scan_run(run_dir: Path) -> dict:
    """Collect per-stage stats from one run."""
    handoff_dir = run_dir / "handoffs"
    stats: dict[str, dict] = {}
    if not handoff_dir.is_dir():
        return stats

    for hf in sorted(handoff_dir.glob("*.output*.yaml")):
        # Skip cancelled/quarantined sub-handoffs
        if ".cancelled-" in hf.name or ".replay-" in hf.name:
            continue
        stage = hf.stem.split(".", 1)[0]
        h = _load_yaml(hf)
        if not h:
            continue
        cost = h.get("cost") or {}
        tokens = (cost.get("tokens_in") or 0) + (cost.get("tokens_out") or 0)
        wall = float(cost.get("wall_clock_min") or 0)
        retries = int(cost.get("retries_used") or 0)
        status = h.get("status", "complete")

        audit = h.get("audit_entries") or []
        audit_joined = "\n".join(str(e) for e in audit)
        has_rationalization = "[Rationalization-rejected]" in audit_joined
        has_redflag = "[RedFlag]" in audit_joined
        has_content_fail = "[ContentValidator]" in audit_joined and "FAIL" in audit_joined

        # Aggregate by stage (later passes overwrite earlier — last write wins
        # which usually means Pass 2 supersedes Pass 1 for requirements-analyst)
        if stage not in stats:
            stats[stage] = {
                "status_counts": {},
                "tokens": [],
                "wall_min": [],
                "retries": [],
                "rationalizations": 0,
                "redflags": 0,
                "content_fails": 0,
                "samples": 0,
            }
        s = stats[stage]
        s["status_counts"][status] = s["status_counts"].get(status, 0) + 1
        if tokens > 0:
            s["tokens"].append(tokens)
        if wall > 0:
            s["wall_min"].append(wall)
        s["retries"].append(retries)
        if has_rationalization:
            s["rationalizations"] += 1
        if has_redflag:
            s["redflags"] += 1
        if has_content_fail:
            s["content_fails"] += 1
        s["samples"] += 1

    return stats


def aggregate(repo_root: Path) -> dict:
    runs_dir = repo_root / ".aidlc-orchestrator" / "runs"
    if not runs_dir.is_dir():
        return {"runs_count": 0, "stages": {}}

    per_stage: dict[str, dict] = {}
    runs_scanned = 0

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run_stats = _scan_run(run_dir)
        if not run_stats:
            continue
        runs_scanned += 1
        for stage, s in run_stats.items():
            if stage not in per_stage:
                per_stage[stage] = {
                    "runs": 0,
                    "status_counts": {},
                    "tokens": [],
                    "wall_min": [],
                    "retries": [],
                    "rationalizations": 0,
                    "redflags": 0,
                    "content_fails": 0,
                }
            agg = per_stage[stage]
            agg["runs"] += 1
            for k, v in s["status_counts"].items():
                agg["status_counts"][k] = agg["status_counts"].get(k, 0) + v
            agg["tokens"].extend(s["tokens"])
            agg["wall_min"].extend(s["wall_min"])
            agg["retries"].extend(s["retries"])
            agg["rationalizations"] += s["rationalizations"]
            agg["redflags"] += s["redflags"]
            agg["content_fails"] += s["content_fails"]

    # Compute final metrics
    out_stages: dict[str, dict] = {}
    for stage, s in per_stage.items():
        runs = max(s["runs"], 1)
        statuses = s["status_counts"]
        out_stages[stage] = {
            "runs": s["runs"],
            "needs_human_rate": round(statuses.get("needs_human", 0) / runs, 3),
            "blocked_rate":     round(statuses.get("blocked", 0) / runs, 3),
            "failed_rate":      round(statuses.get("failed", 0) / runs, 3),
            "complete_rate":    round(statuses.get("complete", 0) / runs, 3),
            "evidence_fail_rate":   round(s["content_fails"] / runs, 3),
            "rationalization_rate": round(s["rationalizations"] / runs, 3),
            "redflag_rate":         round(s["redflags"] / runs, 3),
            "token_p50":  int(_percentile(s["tokens"], 50)),
            "token_p95":  int(_percentile(s["tokens"], 95)),
            "wall_min_p50": round(_percentile(s["wall_min"], 50), 1),
            "wall_min_p95": round(_percentile(s["wall_min"], 95), 1),
            "retry_p50": int(_percentile(s["retries"], 50)),
            "retry_p95": int(_percentile(s["retries"], 95)),
        }

    return {"runs_count": runs_scanned, "stages": out_stages}


def render_markdown(agg: dict) -> str:
    today = dt.date.today().isoformat()
    if agg["runs_count"] == 0:
        return f"# Quality Report — {today}\n\nNo runs found.\n"

    lines = [
        f"# Quality Report — {today}",
        "",
        f"Runs analyzed: **{agg['runs_count']}**",
        "",
        "## Per-stage metrics",
        "",
        "| Stage | Runs | NeedsHuman | Blocked | Failed | EvidenceFail | RedFlag | Token p50 | Token p95 | Wall p50 | Wall p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in sorted(agg["stages"]):
        s = agg["stages"][stage]
        lines.append(
            f"| {stage} | {s['runs']} | "
            f"{s['needs_human_rate']:.0%} | "
            f"{s['blocked_rate']:.0%} | "
            f"{s['failed_rate']:.0%} | "
            f"{s['evidence_fail_rate']:.0%} | "
            f"{s['redflag_rate']:.0%} | "
            f"{s['token_p50']:,} | {s['token_p95']:,} | "
            f"{s['wall_min_p50']} | {s['wall_min_p95']} |"
        )

    # SLO breach annotations
    breaches: list[str] = []
    for stage, s in agg["stages"].items():
        if s["evidence_fail_rate"] > 0.05:
            breaches.append(
                f"- `{stage}` evidence_fail_rate={s['evidence_fail_rate']:.0%} "
                f"(> 5% default SLO)"
            )
        if s["redflag_rate"] > 0.10:
            breaches.append(
                f"- `{stage}` redflag_rate={s['redflag_rate']:.0%} "
                f"(> 10% default SLO)"
            )

    if breaches:
        lines += ["", "## SLO breach signals", ""] + breaches

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_quality_report.py",
        description="Aggregate run-quality telemetry across all AIDLC runs.",
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--out", help="write to file (default: stdout)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parent.parent

    if not (repo_root / ".aidlc-orchestrator").is_dir():
        _die(f"not an AIDLC repo: {repo_root}")

    agg = aggregate(repo_root)
    out_text = (
        json.dumps(agg, indent=2)
        if args.json
        else render_markdown(agg)
    )

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out_text + ("\n" if not out_text.endswith("\n") else ""),
                                  encoding="utf-8")
    else:
        print(out_text)

    if agg["runs_count"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
