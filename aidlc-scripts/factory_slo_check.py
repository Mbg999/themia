#!/usr/bin/env python3
"""factory_slo_check.py — Check quality SLOs against the latest report.

Reads:
    aidlc-docs/quality/slos.md       — SLO definitions (yaml block)
    <quality-report>                  — output of factory_quality_report.py --json
    aidlc-docs/quality/slo-acks.md   — acknowledged breaches (optional)

Compares every metric against its SLO. Emits a markdown summary. Exit code
reflects the worst unacknowledged breach severity:
    0  all SLOs met OR all breaches acknowledged
    1  ≥1 `warn` breach unacknowledged
    2  ≥1 `block` breach unacknowledged  (gates the next spawn)
    3  usage error / missing files

Usage:
    python3 aidlc-scripts/factory_slo_check.py [--quality-report <path>]
    python3 aidlc-scripts/factory_slo_check.py --auto  # runs quality_report internally

When `features.slo_blocking=true`, the orchestrator's stage spawn step should
invoke this and refuse to proceed on exit 2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

YAML_FENCE_RE = re.compile(r"```ya?ml\b\s*\n(?P<body>[\s\S]+?)```", re.MULTILINE)


def _die(msg: str, code: int = 3) -> None:
    print(f"factory_slo_check: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_yaml_blocks(path: Path) -> list[dict]:
    """Extract every ```yaml fenced block from a markdown file."""
    if not path.exists():
        return []
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    text = path.read_text(encoding="utf-8")
    blocks: list[dict] = []
    for m in YAML_FENCE_RE.finditer(text):
        try:
            d = yaml.safe_load(m.group("body"))
        except Exception:
            continue
        if isinstance(d, dict):
            blocks.append(d)
    return blocks


def _load_slos(slos_path: Path) -> list[dict]:
    blocks = _load_yaml_blocks(slos_path)
    out: list[dict] = []
    for b in blocks:
        out.extend(b.get("slos", []) or [])
    return out


def _load_acks(acks_path: Path) -> list[dict]:
    if not acks_path.exists():
        return []
    blocks = _load_yaml_blocks(acks_path)
    out: list[dict] = []
    for b in blocks:
        out.extend(b.get("acks", []) or [])
    return out


def _ack_active(ack: dict, today: dt.date) -> bool:
    exp = ack.get("expires_at")
    if not exp:
        return True
    try:
        if isinstance(exp, dt.date):
            return today <= exp
        return today <= dt.date.fromisoformat(str(exp))
    except Exception:
        return False


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == "<": return value < threshold
    if op == "<=": return value <= threshold
    if op == ">": return value > threshold
    if op == ">=": return value >= threshold
    if op == "==": return value == threshold
    raise ValueError(f"unknown comparator: {op}")


def evaluate(agg: dict, slos: list[dict], acks: list[dict]) -> list[dict]:
    today = dt.date.today()
    breaches: list[dict] = []
    active_acks = [a for a in acks if _ack_active(a, today)]

    stages = agg.get("stages", {})
    if not stages:
        return breaches

    for slo in slos:
        stage_pat = slo["stage"]
        metric = slo["metric"]
        op = slo["comparator"]
        thr = float(slo["threshold"])
        sev = slo.get("severity", "warn")

        target_stages = list(stages) if stage_pat == "*" else [stage_pat]
        for st in target_stages:
            if st not in stages:
                continue
            metrics = stages[st]
            if metric not in metrics:
                continue
            v = float(metrics[metric])
            if _compare(v, op, thr):
                continue  # within SLO
            # Breached. Check for ack.
            acked = any(
                a.get("stage") == st and a.get("metric") == metric
                for a in active_acks
            )
            breaches.append({
                "stage": st,
                "metric": metric,
                "observed": v,
                "threshold": thr,
                "comparator": op,
                "severity": sev,
                "acknowledged": acked,
            })
    return breaches


def _ensure_quality_report(repo_root: Path) -> dict:
    """Run factory_quality_report.py and return its JSON output."""
    qr = repo_root / "aidlc-scripts" / "factory_quality_report.py"
    if not qr.exists():
        _die(f"factory_quality_report.py not found at {qr}")
    result = subprocess.run(
        [sys.executable, str(qr), "--repo-root", str(repo_root), "--json"],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        _die(f"quality_report failed: {result.stderr}")
    if not result.stdout.strip():
        return {"runs_count": 0, "stages": {}}
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(prog="factory_slo_check.py")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--quality-report", help="path to JSON output from factory_quality_report.py")
    parser.add_argument("--auto", action="store_true",
                        help="run factory_quality_report internally")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parent.parent

    slos_path = repo_root / "aidlc-docs" / "quality" / "slos.md"
    acks_path = repo_root / "aidlc-docs" / "quality" / "slo-acks.md"
    if not slos_path.exists():
        _die(f"SLO definitions missing: {slos_path}")

    slos = _load_slos(slos_path)
    if not slos:
        _die(f"no SLOs parsed from {slos_path}")
    acks = _load_acks(acks_path)

    if args.quality_report:
        agg = json.loads(Path(args.quality_report).read_text(encoding="utf-8"))
    elif args.auto:
        agg = _ensure_quality_report(repo_root)
    else:
        agg = _ensure_quality_report(repo_root)

    breaches = evaluate(agg, slos, acks)

    if args.json:
        print(json.dumps({"breaches": breaches, "slos_evaluated": len(slos),
                         "runs_count": agg.get("runs_count", 0)}, indent=2))
    else:
        print(f"# SLO check — {dt.date.today().isoformat()}")
        print(f"\nRuns analyzed: {agg.get('runs_count', 0)} · SLOs evaluated: {len(slos)}")
        if not breaches:
            print("\n✓ All SLOs within bounds.")
        else:
            unack = [b for b in breaches if not b["acknowledged"]]
            ack = [b for b in breaches if b["acknowledged"]]
            print(f"\n{len(breaches)} breach(es): {len(unack)} unacknowledged, {len(ack)} acknowledged.")
            if unack:
                print("\n## Unacknowledged breaches\n")
                for b in unack:
                    print(f"- **{b['severity'].upper()}** `{b['stage']}.{b['metric']}` "
                          f"observed {b['observed']:.3f} {b['comparator']} {b['threshold']}")
            if ack:
                print("\n## Acknowledged breaches\n")
                for b in ack:
                    print(f"- {b['stage']}.{b['metric']} = {b['observed']:.3f}")

    # Exit codes
    unack_block = any(b["severity"] == "block" and not b["acknowledged"]
                      for b in breaches)
    unack_warn = any(b["severity"] == "warn" and not b["acknowledged"]
                     for b in breaches)
    if unack_block:
        sys.exit(2)
    if unack_warn:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
