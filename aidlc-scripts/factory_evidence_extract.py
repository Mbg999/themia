#!/usr/bin/env python3
"""factory_evidence_extract.py — Extract structured evidence rows from audit.md.

The AIDLC orchestrator and stage agents append prefixed evidence to
`aidlc-docs/audit.md`:

    ## 2026-05-13T09:54:02+00:00 INCEPTION - WORKSPACE SCOUT START
    - [Orchestrator] spawned with tokens_max=50000
    - [WorkspaceScout] [Depth] Determined 'standard' depth — ...
    - [Skill] Executed: using-agent-skills — PASS

This script parses those entries into JSONL rows suitable for downstream
telemetry, Phase 3 SPC dashboards, and cross-run pattern mining.

Each row:
    {
      "run_id":     "<from --run-id flag or auto-detected from path>",
      "phase":      "INCEPTION" | "CONSTRUCTION" | "OPERATIONS",
      "stage":      "workspace-scout",      // section header derived
      "state":      "START" | "COMPLETE" | "...",
      "timestamp":  "2026-05-13T09:54:02+00:00",
      "prefix":     "Orchestrator",         // first bracket on the line
      "tags":       ["Orchestrator", "Depth"],   // all brackets in order
      "payload":    "spawned with tokens_max=50000",
      "line_no":    12
    }

Usage:
    python3 aidlc-scripts/factory_evidence_extract.py <audit.md> [--run-id <id>] [--out <file>]
    python3 aidlc-scripts/factory_evidence_extract.py --run-dir <run-dir>

Exit codes:
    0  successful extraction (emitted ≥0 rows)
    1  parse error / no recognizable section headers
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

# Section header pattern: `## <ISO8601-ish timestamp> <PHASE> - <STAGE> <STATE>`
SECTION_HEADER_RE = re.compile(
    r"^##\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)"
    r"\s+"
    r"(?P<phase>[A-Z][A-Z ]+?)"
    r"\s*-\s*"
    r"(?P<rest>[A-Z][A-Za-z0-9 ()_-]+?)"
    r"\s*$",
    re.MULTILINE,
)

# `STAGE_NAME STATE` — strip the state suffix to get the stage
KNOWN_STATES = {"START", "COMPLETE", "PASS", "PASS 1", "PASS 2", "STARTED", "FINISHED",
                "FAILED", "BLOCKED", "RESUMED", "RETRY", "(PASS 1)", "(PASS 2)",
                "(START)", "(COMPLETE)"}

# Bullet line with bracketed prefix(es): `- [Foo] [Bar] payload text`
EVIDENCE_LINE_RE = re.compile(
    r"^-\s+(?P<brackets>(?:\[[^\]]+\]\s*)+)(?P<payload>.*)$"
)
BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_evidence_extract: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _split_stage_state(rest: str) -> tuple[str, str]:
    """Split `WORKSPACE SCOUT START` → ('workspace-scout', 'START').

    Handles trailing parenthesized variant tags too:
        `REQUIREMENTS ANALYST START (PASS 1)` → ('requirements-analyst', 'START (PASS 1)')
    """
    rest = rest.strip()
    if not rest:
        return ("", "")

    # Capture an optional trailing `(...)` variant tag (PASS 1, retry, etc.)
    paren_suffix = ""
    pm = re.search(r"\s*\((?P<v>[^)]+)\)\s*$", rest)
    if pm:
        paren_suffix = pm.group(0).strip()
        rest = rest[: pm.start()].strip()

    tokens = rest.split()
    if not tokens:
        return ("", paren_suffix)

    # Trailing known state word (always 1 token here since we stripped parens)
    if tokens[-1].upper() in KNOWN_STATES:
        state = tokens[-1].upper()
        if paren_suffix:
            state = f"{state} {paren_suffix}"
        stage_tokens = tokens[:-1]
        return (_to_kebab(" ".join(stage_tokens)), state)

    # No known state — treat all as stage name
    return (_to_kebab(rest), paren_suffix)


def _to_kebab(s: str) -> str:
    s = re.sub(r"\s+", "-", s.strip().lower())
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


def parse_audit(text: str, run_id: str) -> list[dict]:
    """Parse audit.md text into evidence rows."""
    lines = text.splitlines()
    rows: list[dict] = []

    # Build a list of (line_index, header_match) pairs
    header_positions: list[tuple[int, re.Match[str]]] = []
    for i, line in enumerate(lines):
        m = SECTION_HEADER_RE.match(line)
        if m:
            header_positions.append((i, m))

    if not header_positions:
        return rows

    # Add sentinel so the last section is bounded
    header_positions.append((len(lines), None))  # type: ignore[arg-type]

    for idx in range(len(header_positions) - 1):
        line_idx, hm = header_positions[idx]
        next_line_idx, _ = header_positions[idx + 1]

        timestamp = hm.group("timestamp")
        phase = hm.group("phase").strip()
        stage, state = _split_stage_state(hm.group("rest"))

        # Walk lines until next header
        for i in range(line_idx + 1, next_line_idx):
            line = lines[i]
            em = EVIDENCE_LINE_RE.match(line)
            if not em:
                continue
            brackets_str = em.group("brackets")
            payload = em.group("payload").strip()
            tags = [b.group(1) for b in BRACKET_RE.finditer(brackets_str)]
            if not tags:
                continue
            rows.append({
                "run_id": run_id,
                "phase": phase,
                "stage": stage,
                "state": state,
                "timestamp": timestamp,
                "prefix": tags[0],
                "tags": tags,
                "payload": payload,
                "line_no": i + 1,
            })

    return rows


def _auto_run_id_from_path(audit_path: Path) -> str:
    """Infer run_id from path: <repo>/aidlc-docs/audit.md → repo basename or
    <repo>/.aidlc-orchestrator/runs/<run-id>/audit.md → that run-id."""
    parts = audit_path.resolve().parts
    if "runs" in parts:
        i = parts.index("runs")
        if i + 1 < len(parts):
            return parts[i + 1]
    # Fall back to the parent-of-parent directory name
    return audit_path.resolve().parent.parent.name


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_evidence_extract.py",
        description="Extract structured evidence rows from audit.md.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("audit", nargs="?", help="path to audit.md")
    src.add_argument("--run-dir", help="path to a run directory (looks for aidlc-docs/audit.md)")
    parser.add_argument("--run-id", default=None,
                        help="run_id to embed in each row (default: auto-detect from path)")
    parser.add_argument("--out", "-o", default=None,
                        help="output JSONL file (default: stdout)")
    parser.add_argument("--pretty", action="store_true",
                        help="pretty-print JSON instead of JSONL (one object per line)")
    args = parser.parse_args()

    if args.run_dir:
        audit_path = Path(args.run_dir).resolve() / "aidlc-docs" / "audit.md"
    else:
        audit_path = Path(args.audit).resolve()

    if not audit_path.exists():
        _die(f"audit file not found: {audit_path}")

    run_id = args.run_id or _auto_run_id_from_path(audit_path)
    text = audit_path.read_text(encoding="utf-8")
    rows = parse_audit(text, run_id)

    if not rows:
        print("factory_evidence_extract: no section headers found — empty extraction",
              file=sys.stderr)
        sys.exit(1)

    out_stream = sys.stdout
    if args.out:
        out_stream = open(args.out, "w", encoding="utf-8")

    try:
        for row in rows:
            if args.pretty:
                json.dump(row, out_stream, indent=2)
                out_stream.write("\n")
            else:
                out_stream.write(json.dumps(row) + "\n")
    finally:
        if args.out:
            out_stream.close()

    print(f"factory_evidence_extract: extracted {len(rows)} row(s) "
          f"from {audit_path.name}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
