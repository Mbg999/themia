#!/usr/bin/env python3
"""factory_merge_reviews.py — merge reviewer pool outputs into <run-id>-review-report.md

Phase 4 of the AIDLC Orchestrator. After the parallel reviewer fan-out, the
orchestrator calls this script to combine the 4 (or fewer) reviewer output
handoffs into a single human-readable report.

Usage
-----
    factory_merge_reviews.py <run-id> [--output PATH] [--reviewers LIST]

Reads (one per active reviewer):
    .aidlc-orchestrator/runs/<run-id>/handoffs/reviewer-code.output.yaml
    .aidlc-orchestrator/runs/<run-id>/handoffs/reviewer-security.output.yaml
    .aidlc-orchestrator/runs/<run-id>/handoffs/reviewer-performance.output.yaml
    .aidlc-orchestrator/runs/<run-id>/handoffs/reviewer-simplifier.output.yaml

Writes (default):
    aidlc-docs/operations/<run-id>-review-report.md

Skipped reviewers (per Cost Governor exit code 2) can be excluded via
`--reviewers <list>`.

Exit codes:
    0   merge succeeded
    1   no reviewer outputs found
    2   usage error
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))
RUNS_ROOT = REPO_ROOT / ".aidlc-orchestrator" / "runs"
REVIEWER_OUTPUT_SCHEMA = (
    REPO_ROOT / ".aidlc-orchestrator" / "contracts" / "reviewer.output.v1.json"
)

REVIEWERS = ["code-quality", "security", "performance", "simplifier"]
STAGE_BY_REVIEWER = {
    "code-quality": "reviewer-code",
    "security": "reviewer-security",
    "performance": "reviewer-performance",
    "simplifier": "reviewer-simplifier",
}
SEVERITY_ORDER = ["P0", "P1", "P2", "P3"]


def _load_validator():
    """Return a jsonschema Draft7Validator for reviewer.output.v1, or None.

    Returns None if jsonschema isn't installed or the schema file is missing —
    the caller falls back to .get() defenses without contract enforcement.
    """
    if jsonschema is None or not REVIEWER_OUTPUT_SCHEMA.exists():
        return None
    import json
    schema = json.loads(REVIEWER_OUTPUT_SCHEMA.read_text())
    return jsonschema.Draft7Validator(schema)


def render_finding(reviewer: str, f: dict) -> str:
    sev = f.get("severity", "?")
    loc = f.get("file", "?")
    if "line" in f:
        loc = f"{loc}:{f['line']}"
    parts = [f"### [{sev}] {loc}", "", f.get("message", "_(no message provided)_")]
    if "recommendation" in f:
        parts += ["", f"**Recommendation:** {f['recommendation']}"]
    if reviewer == "code-quality" and "axis" in f:
        parts += ["", f"**Axis:** {f['axis']}"]
    if reviewer == "security":
        refs = []
        if "cwe" in f:
            refs.append(f["cwe"])
        if "owasp" in f:
            refs.append(f["owasp"])
        if refs:
            parts += ["", f"**Refs:** {', '.join(refs)}"]
    if reviewer == "performance":
        if "big_o" in f:
            parts += ["", f"**Complexity:** {f['big_o']}"]
        if "expected_impact" in f:
            parts += ["", f"**Expected impact:** {f['expected_impact']}"]
    if reviewer == "simplifier" and "simplification_pattern" in f:
        parts += ["", f"**Pattern:** `{f['simplification_pattern']}`"]
    return "\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description="merge reviewer pool outputs")
    p.add_argument("run_id")
    p.add_argument(
        "--output",
        default=None,
        help="output path (relative to repo root); defaults to aidlc-docs/operations/<run-id>-review-report.md",
    )
    p.add_argument(
        "--reviewers",
        nargs="+",
        default=REVIEWERS,
        choices=REVIEWERS,
        help="active reviewer set (skipped reviewers are excluded)",
    )
    args = p.parse_args()
    if args.output is None:
        args.output = f"aidlc-docs/operations/{args.run_id}-review-report.md"

    run_dir = RUNS_ROOT / args.run_id / "handoffs"
    if not run_dir.exists():
        print(f"run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    validator = _load_validator()

    outputs: dict[str, dict] = {}
    missing: list[str] = []
    invalid: list[tuple[str, list[str]]] = []
    for reviewer in args.reviewers:
        stage = STAGE_BY_REVIEWER[reviewer]
        path = run_dir / f"{stage}.output.yaml"
        if not path.exists():
            missing.append(reviewer)
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            invalid.append((reviewer, [f"YAML parse error: {e}"]))
            continue
        if not isinstance(data, dict):
            invalid.append((reviewer, ["top-level YAML is not a mapping"]))
            continue
        if validator is not None:
            errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
            if errors:
                msgs = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
                invalid.append((reviewer, msgs))
                continue
        outputs[reviewer] = data

    if missing:
        print(f"WARNING: missing outputs for: {', '.join(missing)}", file=sys.stderr)

    if invalid:
        for reviewer, errs in invalid:
            print(f"WARNING: skipping {reviewer} (schema-invalid output):", file=sys.stderr)
            for e in errs[:5]:
                print(f"  - {e}", file=sys.stderr)
            if len(errs) > 5:
                print(f"  - ... and {len(errs) - 5} more", file=sys.stderr)

    if not outputs:
        print("no reviewer outputs found", file=sys.stderr)
        sys.exit(1)

    severity_counts: dict[str, dict[str, int]] = {
        sev: defaultdict(int) for sev in SEVERITY_ORDER
    }
    for reviewer, data in outputs.items():
        for f in data.get("findings", []):
            sev = f.get("severity")
            if sev in severity_counts:
                severity_counts[sev][reviewer] += 1

    file_findings: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for reviewer, data in outputs.items():
        for f in data.get("findings", []):
            file_key = f.get("file", "?")
            file_findings[file_key][reviewer].append(f)

    md = ["# Code Review Report", ""]
    md += [f"Run: `{args.run_id}`"]
    md += [f"Reviewers: {', '.join(outputs.keys())}"]
    if missing:
        md += [f"_Skipped (no output): {', '.join(missing)}_"]
    if invalid:
        invalid_names = ", ".join(r for r, _ in invalid)
        md += [f"_Skipped (schema-invalid output): {invalid_names}_"]
    md += ["", "## Summary", ""]

    cols = list(outputs.keys())
    header_cells = ["Severity"] + cols + ["Total"]
    md += ["| " + " | ".join(header_cells) + " |"]
    md += ["|" + "|".join(["---"] * len(header_cells)) + "|"]
    grand_total = 0
    for sev in SEVERITY_ORDER:
        row_total = sum(severity_counts[sev][c] for c in cols)
        grand_total += row_total
        cells = [sev] + [str(severity_counts[sev][c]) for c in cols] + [str(row_total)]
        md += ["| " + " | ".join(cells) + " |"]
    md += [f"\n_Total findings across all reviewers:_ **{grand_total}**", ""]

    for reviewer, data in outputs.items():
        md += [f"## {reviewer.replace('-', ' ').title()}", ""]
        md += [f"Status: `{data.get('status', 'unknown')}`", ""]
        findings = list(data.get("findings", []))
        if not findings:
            md += ["_No findings._", ""]
            continue
        findings.sort(
            key=lambda f: (
                SEVERITY_ORDER.index(f.get("severity", "P2"))
                if f.get("severity") in SEVERITY_ORDER
                else len(SEVERITY_ORDER),
                f.get("file", ""),
                f.get("line") or 0,
            )
        )
        for f in findings:
            md += [render_finding(reviewer, f), ""]

    md += ["## Files with most findings", ""]
    sorted_files = sorted(
        file_findings.items(),
        key=lambda kv: -sum(len(v) for v in kv[1].values()),
    )
    if not sorted_files:
        md += ["_No findings to index._"]
    else:
        for file, by_reviewer in sorted_files[:10]:
            total = sum(len(v) for v in by_reviewer.values())
            breakdown = ", ".join(
                f"{r}: {len(v)}" for r, v in by_reviewer.items()
            )
            md += [f"- `{file}` — {total} findings ({breakdown})"]

    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(md) + "\n")
    print(f"wrote {output_path} ({grand_total} total findings)")


if __name__ == "__main__":
    main()
