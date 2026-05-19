#!/usr/bin/env python3
"""factory_telemetry.py — refactor-baseline telemetry for the AIDLC Orchestrator.

Subcommands
-----------
    hot-path <markdown-file> [--json PATH]
        Static analysis of a markdown file. Emits per-H2 section bytes/lines,
        reach (always|hot|cold), redundancy score, and audit-protocol phrase hits.
        Fence-aware: H2 lines inside ``` or ~~~ blocks are not section boundaries.

    count-tokens <run-id> [--repo-root PATH] [--out CSV]
        Reads <repo-root>/.aidlc-orchestrator/runs/<run-id>/timeline.jsonl and
        emits per-stage CSV. Works on PARTIAL runs (only emitted spawn_end
        events appear; running stages are omitted). --repo-root defaults to
        AIDLC_ROOT or the script's parent dir.

    discover [--root PATH ...] [--scan-siblings] [--json PATH]
        Walks one or more repo roots for `.aidlc-orchestrator/runs/*/manifest.yaml`
        and emits an inventory of every discovered run (repo_root, run_id, tier,
        status, completed_stages, total_tokens). With --scan-siblings, also
        scans the parent dir of the primary root for adjacent AIDLC projects.

    aggregate [--run PATH ...] [--auto-discover] [--root PATH ...] [--json PATH]
        Aggregates per-stage tokens across N runs, grouped by complexity tier.
        Emits {tier: {stage: {mean, min, max, stddev, n}}}. --auto-discover
        runs `discover` internally and uses every run it finds.

    report [--baseline PATH] [--auto-discover] [--scan-siblings] [--json PATH]
        High-level: runs hot-path + discover + aggregate and writes a markdown
        baseline report to --baseline (default: aidlc-docs/refactor/baseline-<date>.md).
        Re-runnable; safe to invoke after each refactor phase to generate deltas.

This script is read-only. It does not mutate runs, manifests, or audit logs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Repo-root resolution: defaults to AIDLC_ROOT but overridable per-command.
# ---------------------------------------------------------------------------


DEFAULT_REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))


def runs_root(repo_root: Path) -> Path:
    return repo_root / ".aidlc-orchestrator" / "runs"


def orchestrator_md(repo_root: Path) -> Path:
    candidates = [
        repo_root / ".claude" / "agents" / "orchestrator.md",
        repo_root / ".opencode" / "agents" / "orchestrator.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def stage_agents_dir(repo_root: Path) -> Path:
    candidates = [
        repo_root / ".claude" / "agents" / "stage",
        repo_root / ".opencode" / "agents" / "stage",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


# ---------------------------------------------------------------------------
# hot-path: static markdown analysis
# ---------------------------------------------------------------------------


BOILERPLATE_PHRASES = [
    "shared-primitives Step 8",
    "substep 6",
    "canonical sequence",
    "Wall-clocking",
    "wall-clocking",
    "Emit FIRST",
    "emit FIRST",
    "factory_run.py emit",
    "Capture the returned `ts`",
    "Capture `ts_",
    "Only then proceed",
    "Only AFTER",
    "non-spawn audit",
]

POINTER_PHRASES = [
    "audit-block.protocol.md",
    "runtime/index.md",
    "runtime/spawn-loop.md",
    "runtime/fast-path.md",
    "runtime/recovery.md",
    "runtime/replay-adopt.md",
    "runtime/project-profile.md",
    "runtime/cmd-factory-spec.md",
    "runtime/cmd-factory-plan.md",
    "runtime/cmd-factory-build.md",
    "runtime/cmd-factory-review.md",
    "runtime/cmd-factory-ship.md",
    "runtime/validation.md",
    "runtime/compaction.md",
    "runtime/skill-protocol.md",
    "runtime/audit-lifecycle.md",
    "runtime/extension-loading.md",
    "runtime/run-manager.md",
    "runtime/conflict-resolver.md",
    "runtime/knowledge-agent.md",
    "runtime/cost-governor.md",
    "runtime/custom-subagents.md",
]

COLD_HINTS = [
    "FAST_PATH",
    "Failed→skipped",
    "Failed->skipped",
    "Legacy adoption",
    "Replay protocol",
    "Resume protocol",
    "TINY tier",
]

ALWAYS_HINTS = [
    "shared",
    "Hard rules",
    "Manifest.yaml shape",
    "Reference",
]


def _classify_reach(title: str) -> str:
    t = title.lower()
    for hint in COLD_HINTS:
        if hint.lower() in t:
            return "cold"
    for hint in ALWAYS_HINTS:
        if hint.lower() in t:
            return "always"
    return "hot"


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"^(```|~~~)", re.MULTILINE)


def _h2_matches_outside_code_fences(text: str):
    inside = False
    fence_lines: set[int] = set()
    for i, line in enumerate(text.split("\n")):
        if _FENCE_RE.match(line):
            inside = not inside
            fence_lines.add(i)
            continue
        if inside:
            fence_lines.add(i)
    out = []
    for m in _H2_RE.finditer(text):
        line_idx = text.count("\n", 0, m.start())
        if line_idx not in fence_lines:
            out.append(m)
    return out


def parse_h2_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    matches = _h2_matches_outside_code_fences(text)
    if not matches:
        return [{"title": "PREAMBLE", "body": text, "start": 0, "end": len(text)}]
    if matches[0].start() > 0:
        sections.append({"title": "PREAMBLE", "body": text[: matches[0].start()],
                         "start": 0, "end": matches[0].start()})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({"title": m.group(1).strip(), "body": text[m.start():end],
                         "start": m.start(), "end": end})
    return sections


def _count_phrase_hits(body: str) -> dict[str, int]:
    hits = {}
    for p in BOILERPLATE_PHRASES:
        c = body.count(p)
        if c:
            hits[p] = c
    for p in POINTER_PHRASES:
        c = body.count(p)
        if c:
            hits[p] = c
    return hits


def _boilerplate_total(body: str) -> int:
    return sum(body.count(p) for p in BOILERPLATE_PHRASES)


def _pointer_total(body: str) -> int:
    return sum(body.count(p) for p in POINTER_PHRASES)


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")


def _ngrams(body: str, n: int = 6):
    words = _WORD_RE.findall(body)
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def _redundancy_score(sections: list[dict], n: int = 6) -> dict[str, float]:
    per = {s["title"]: _ngrams(s["body"], n) for s in sections}
    counts: Counter = Counter()
    for grams in per.values():
        counts.update(set(grams))
    scores: dict[str, float] = {}
    for title, grams in per.items():
        if not grams:
            scores[title] = 0.0
            continue
        shared = sum(1 for g in grams if counts[g] >= 2)
        scores[title] = round(shared / len(grams), 3)
    return scores


def hot_path_report(md_path: Path) -> dict:
    text = md_path.read_text()
    sections = parse_h2_sections(text)
    redundancy = _redundancy_score(sections)
    rows = []
    for s in sections:
        body = s["body"]
        hits = _count_phrase_hits(body)
        rows.append({
            "title": s["title"],
            "bytes": len(body.encode("utf-8")),
            "lines": body.count("\n"),
            "reach": _classify_reach(s["title"]),
            "redundancy": redundancy[s["title"]],
            "audit_phrase_hits": hits,
            "audit_phrase_hit_total": sum(hits.values()),
            "boilerplate_hit_total": _boilerplate_total(body),
            "pointer_hit_total": _pointer_total(body),
        })
    return {
        "source": str(md_path),
        "total_bytes": len(text.encode("utf-8")),
        "total_lines": text.count("\n"),
        "section_count": len(rows),
        "sections": rows,
    }


def _format_hot_path(report: dict) -> str:
    out = io.StringIO()
    out.write(f"HOT-PATH REPORT: {report['source']}\n")
    out.write(f"total: {report['total_bytes']:,} bytes / {report['total_lines']:,} lines / "
              f"{report['section_count']} H2 sections\n")
    out.write("─" * 100 + "\n")
    out.write(f"{'reach':<7} {'bytes':>7} {'lines':>5} {'redun':>5} {'boiler':>6} {'ptrs':>5}  title\n")
    out.write("─" * 100 + "\n")
    for r in sorted(report["sections"], key=lambda r: r["bytes"], reverse=True):
        out.write(f"{r['reach']:<7} {r['bytes']:>7,} {r['lines']:>5,} "
                  f"{r['redundancy']:>5.2f} {r['boilerplate_hit_total']:>6} {r['pointer_hit_total']:>5}  {r['title'][:55]}\n")
    out.write("─" * 100 + "\n")

    boiler_total = sum(r["boilerplate_hit_total"] for r in report["sections"])
    pointer_total = sum(r["pointer_hit_total"] for r in report["sections"])
    out.write(f"\nBOILERPLATE HITS (target=0): {boiler_total}\n")
    if boiler_total:
        phrase_totals: Counter = Counter()
        for r in report["sections"]:
            for p, n in r["audit_phrase_hits"].items():
                if p in BOILERPLATE_PHRASES:
                    phrase_totals[p] += n
        for phrase, n in phrase_totals.most_common():
            out.write(f"  {n:>3}  {phrase}\n")
    out.write(f"POINTER REFERENCES (target=N): {pointer_total}\n")
    if pointer_total:
        ptr_totals: Counter = Counter()
        for r in report["sections"]:
            for p, n in r["audit_phrase_hits"].items():
                if p in POINTER_PHRASES:
                    ptr_totals[p] += n
        for phrase, n in ptr_totals.most_common():
            out.write(f"  {n:>3}  {phrase}\n")
    cold = sum(r["bytes"] for r in report["sections"] if r["reach"] == "cold")
    hot = sum(r["bytes"] for r in report["sections"] if r["reach"] == "hot")
    always = sum(r["bytes"] for r in report["sections"] if r["reach"] == "always")
    total = cold + hot + always
    if total:
        out.write("\nREACH BREAKDOWN:\n")
        out.write(f"  always: {always:>7,} bytes ({always / total * 100:>5.1f}%)\n")
        out.write(f"  hot:    {hot:>7,} bytes ({hot   / total * 100:>5.1f}%)\n")
        out.write(f"  cold:   {cold:>7,} bytes ({cold  / total * 100:>5.1f}%)  ← Phase 3 target\n")
    return out.getvalue()


def cmd_hot_path(args: argparse.Namespace) -> None:
    md_path = Path(args.file).expanduser()
    if not md_path.is_absolute():
        md_path = (DEFAULT_REPO_ROOT / md_path).resolve()
    if not md_path.exists():
        print(f"file not found: {md_path}", file=sys.stderr)
        sys.exit(2)
    report = hot_path_report(md_path)
    print(_format_hot_path(report))
    if args.json:
        out_path = Path(args.json).expanduser()
        if not out_path.is_absolute():
            out_path = (DEFAULT_REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\nJSON report written to: {out_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# count-tokens: per-run CSV (now multi-repo aware)
# ---------------------------------------------------------------------------


_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        print(f"invalid run_id: {run_id!r}", file=sys.stderr)
        sys.exit(2)


def _read_timeline(timeline_path: Path) -> list[dict]:
    if not timeline_path.exists():
        return []
    events: list[dict] = []
    for line in timeline_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _stage_costs_from_timeline(events: list[dict]) -> dict[str, dict]:
    per_stage: dict[str, dict] = {}
    starts: dict[str, str] = {}
    from datetime import datetime as _dt
    for e in events:
        stage = e.get("stage")
        if not stage:
            continue
        evt = e.get("evt")
        if evt == "spawn_start":
            starts[stage] = e.get("ts", "")
        elif evt == "spawn_end":
            entry = per_stage.setdefault(stage, {
                "tokens_in": 0, "tokens_out": 0, "wall_min": 0.0, "spawn_count": 0,
            })
            entry["spawn_count"] += 1
            tin = e.get("tokens_in")
            tout = e.get("tokens_out")
            tcombined = e.get("tokens")
            if isinstance(tin, (int, float)):
                entry["tokens_in"] += int(tin)
            if isinstance(tout, (int, float)):
                entry["tokens_out"] += int(tout)
            if tin is None and tout is None and isinstance(tcombined, (int, float)):
                entry["tokens_out"] += int(tcombined)
            wall = e.get("wall_min")
            if isinstance(wall, (int, float)):
                entry["wall_min"] += float(wall)
            elif starts.get(stage) and e.get("ts"):
                try:
                    dur = (_dt.fromisoformat(e["ts"]) - _dt.fromisoformat(starts[stage])).total_seconds() / 60.0
                    entry["wall_min"] += round(dur, 1)
                except (ValueError, TypeError):
                    pass
    return per_stage


def _handoff_bytes(repo_root: Path, run_id: str, stage: str) -> int:
    handoffs = runs_root(repo_root) / run_id / "handoffs"
    if not handoffs.exists():
        return 0
    total = 0
    for p in handoffs.glob(f"{stage}*.input.*"):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def _prompt_bytes(repo_root: Path, stage: str) -> int:
    p = stage_agents_dir(repo_root) / f"{stage}.md"
    return p.stat().st_size if p.exists() else 0


def count_tokens_rows(repo_root: Path, run_id: str) -> list[dict]:
    _validate_run_id(run_id)
    run_path = runs_root(repo_root) / run_id
    if not run_path.exists():
        print(f"run not found: {run_path}", file=sys.stderr)
        sys.exit(2)
    kernel_bytes = orchestrator_md(repo_root).stat().st_size if orchestrator_md(repo_root).exists() else 0
    events = _read_timeline(run_path / "timeline.jsonl")
    stages = _stage_costs_from_timeline(events)
    rows: list[dict] = []
    for stage in sorted(stages):
        c = stages[stage]
        rows.append({
            "stage": stage,
            "tokens_in": c["tokens_in"],
            "tokens_out": c["tokens_out"],
            "wall_min": round(c["wall_min"], 1),
            "kernel_bytes": kernel_bytes,
            "handoff_bytes": _handoff_bytes(repo_root, run_id, stage),
            "prompt_bytes": _prompt_bytes(repo_root, stage),
        })
    return rows


def cmd_count_tokens(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else DEFAULT_REPO_ROOT
    rows = count_tokens_rows(repo_root, args.run_id)
    fieldnames = ["stage", "tokens_in", "tokens_out", "wall_min",
                  "kernel_bytes", "handoff_bytes", "prompt_bytes"]
    if args.out:
        out_path = Path(args.out).expanduser()
        if not out_path.is_absolute():
            out_path = (DEFAULT_REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {out_path}", file=sys.stderr)
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# discover: walk repo roots for runs
# ---------------------------------------------------------------------------


def _derive_tier(manifest: dict) -> str:
    """Best-effort tier from manifest. Order:
       1. explicit `complexity_tier`
       2. heuristics on skip_stages / units
       3. 'unknown'
    """
    tier = manifest.get("complexity_tier")
    if isinstance(tier, str) and tier.upper() in {"TINY", "SMALL", "MEDIUM", "LARGE"}:
        return tier.upper()
    skipped = set(manifest.get("skip_stages") or [])
    skipped |= set(manifest.get("skipped_stages") or [])
    units = manifest.get("units") or []
    if "unit-decomposer" in skipped and "story-writer" in skipped:
        return "SMALL"
    if "story-writer" in skipped and len(units) <= 1:
        return "SMALL"
    if len(units) >= 3:
        return "LARGE"
    if len(units) >= 1:
        return "MEDIUM"
    return "UNKNOWN"


def _run_status(manifest: dict, has_timeline: bool) -> str:
    completed = manifest.get("completed_stages") or []
    failed = manifest.get("failed_stages") or []
    if failed:
        return "failed"
    if "ship-agent" in completed:
        return "complete"
    if not has_timeline:
        return "no-timeline"
    current = manifest.get("current_stage")
    if current and current not in completed:
        return f"running:{current}"
    return "partial"


def _discover_one_root(repo_root: Path) -> list[dict]:
    rr = runs_root(repo_root)
    if not rr.exists():
        return []
    out: list[dict] = []
    for manifest_path in sorted(rr.glob("*/manifest.yaml")):
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            continue
        run_dir = manifest_path.parent
        timeline_path = run_dir / "timeline.jsonl"
        events = _read_timeline(timeline_path)
        stages = _stage_costs_from_timeline(events)
        total_tokens = sum(s["tokens_in"] + s["tokens_out"] for s in stages.values())
        out.append({
            "repo_root": str(repo_root),
            "run_path": str(run_dir),
            "run_id": str(manifest.get("run_id") or run_dir.name),
            "project_slug": str(manifest.get("project_slug") or repo_root.name),
            "tier": _derive_tier(manifest),
            "status": _run_status(manifest, timeline_path.exists()),
            "completed_stages": [str(s) for s in (manifest.get("completed_stages") or [])],
            "skipped_stages": [str(s) for s in ((manifest.get("skipped_stages") or []) + (manifest.get("skip_stages") or []))],
            "current_stage": str(manifest.get("current_stage")) if manifest.get("current_stage") else None,
            "started_at": str(manifest.get("started_at")) if manifest.get("started_at") else None,
            "stage_token_count": len(stages),
            "total_tokens": total_tokens,
            "event_count": len(events),
        })
    return out


def _sibling_roots(primary: Path) -> list[Path]:
    """Find adjacent dirs (siblings of `primary`) that contain `.aidlc-orchestrator/`."""
    parent = primary.parent
    out: list[Path] = []
    if not parent.exists() or not parent.is_dir():
        return out
    for child in sorted(parent.iterdir()):
        try:
            if child.is_dir() and child.resolve() != primary.resolve():
                if (child / ".aidlc-orchestrator").is_dir():
                    out.append(child)
        except OSError:
            continue
    return out


def discover_runs(roots: list[Path], scan_siblings: bool = False) -> list[dict]:
    expanded: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        r = r.expanduser().resolve()
        if str(r) not in seen:
            expanded.append(r)
            seen.add(str(r))
        if scan_siblings:
            for s in _sibling_roots(r):
                if str(s) not in seen:
                    expanded.append(s)
                    seen.add(str(s))
    out: list[dict] = []
    for root in expanded:
        out.extend(_discover_one_root(root))
    return out


def cmd_discover(args: argparse.Namespace) -> None:
    roots = [Path(r) for r in (args.root or [str(DEFAULT_REPO_ROOT)])]
    runs = discover_runs(roots, scan_siblings=args.scan_siblings)
    if args.json:
        out_path = Path(args.json).expanduser()
        if not out_path.is_absolute():
            out_path = (DEFAULT_REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(runs, indent=2))
        print(f"wrote {len(runs)} runs to {out_path}", file=sys.stderr)
    # Human table
    print(f"DISCOVERED {len(runs)} run(s) across {len(set(r['repo_root'] for r in runs))} repo root(s):")
    print("─" * 110)
    print(f"{'tier':<8} {'status':<22} {'tokens':>9} {'stages':>6} {'evts':>5}  {'run_id':<35}  project")
    print("─" * 110)
    for r in runs:
        print(f"{r['tier']:<8} {r['status']:<22} {r['total_tokens']:>9,} "
              f"{len(r['completed_stages']):>6} {r['event_count']:>5}  "
              f"{r['run_id'][:35]:<35}  {r['project_slug']}")
    print("─" * 110)


# ---------------------------------------------------------------------------
# aggregate: per-tier per-stage stats
# ---------------------------------------------------------------------------


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return round(math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)), 1)


def aggregate_runs(run_records: list[dict]) -> dict:
    """Given discover records, aggregate per-stage stats grouped by tier.

    Output shape:
      { tier: {
          run_count: int,
          total_tokens: {mean, min, max, stddev, n},
          per_stage: { stage: {tokens: {mean,min,max,stddev,n}, wall_min: {...}} }
      }}
    """
    per_tier_runs: dict[str, list[dict]] = defaultdict(list)
    for r in run_records:
        per_tier_runs[r["tier"]].append(r)

    out: dict = {}
    for tier, runs in per_tier_runs.items():
        per_stage_tokens: dict[str, list[float]] = defaultdict(list)
        per_stage_wall: dict[str, list[float]] = defaultdict(list)
        total_tokens_per_run: list[float] = []
        for r in runs:
            events = _read_timeline(Path(r["run_path"]) / "timeline.jsonl")
            stages = _stage_costs_from_timeline(events)
            run_total = 0.0
            for stage, c in stages.items():
                t = c["tokens_in"] + c["tokens_out"]
                per_stage_tokens[stage].append(t)
                per_stage_wall[stage].append(c["wall_min"])
                run_total += t
            total_tokens_per_run.append(run_total)

        def stats(values: list[float]) -> dict:
            if not values:
                return {"mean": 0, "min": 0, "max": 0, "stddev": 0.0, "n": 0}
            return {
                "mean": round(sum(values) / len(values), 1),
                "min": min(values),
                "max": max(values),
                "stddev": _stddev(values),
                "n": len(values),
            }

        out[tier] = {
            "run_count": len(runs),
            "total_tokens": stats(total_tokens_per_run),
            "per_stage": {
                stage: {
                    "tokens": stats(per_stage_tokens[stage]),
                    "wall_min": stats(per_stage_wall[stage]),
                }
                for stage in sorted(per_stage_tokens)
            },
        }
    return out


def cmd_aggregate(args: argparse.Namespace) -> None:
    if args.auto_discover:
        roots = [Path(r) for r in (args.root or [str(DEFAULT_REPO_ROOT)])]
        records = discover_runs(roots, scan_siblings=args.scan_siblings)
    elif args.run:
        records = []
        for p in args.run:
            path = Path(p).expanduser().resolve()
            mp = path / "manifest.yaml"
            if not mp.exists():
                print(f"skipping: no manifest.yaml at {path}", file=sys.stderr)
                continue
            try:
                manifest = yaml.safe_load(mp.read_text()) or {}
            except (yaml.YAMLError, OSError):
                continue
            events = _read_timeline(path / "timeline.jsonl")
            stages = _stage_costs_from_timeline(events)
            records.append({
                "run_path": str(path),
                "tier": _derive_tier(manifest),
                "run_id": manifest.get("run_id") or path.name,
                "total_tokens": sum(s["tokens_in"] + s["tokens_out"] for s in stages.values()),
                "completed_stages": manifest.get("completed_stages") or [],
            })
    else:
        print("either --auto-discover or --run is required", file=sys.stderr)
        sys.exit(2)

    agg = aggregate_runs(records)
    if args.json:
        out_path = Path(args.json).expanduser()
        if not out_path.is_absolute():
            out_path = (DEFAULT_REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(agg, indent=2))
        print(f"wrote aggregate to {out_path}", file=sys.stderr)
    # Human table
    print(f"AGGREGATE across {sum(t['run_count'] for t in agg.values())} run(s), {len(agg)} tier(s):")
    print("─" * 100)
    for tier in sorted(agg):
        data = agg[tier]
        print(f"\nTier {tier} — {data['run_count']} run(s)")
        tt = data["total_tokens"]
        print(f"  total tokens/run: mean={tt['mean']:,} min={tt['min']:,} max={tt['max']:,} σ={tt['stddev']:,}")
        print(f"  {'stage':<28} {'mean':>9} {'min':>9} {'max':>9} {'σ':>8} {'wall_min(avg)':>14}  n")
        for stage, s in data["per_stage"].items():
            t, w = s["tokens"], s["wall_min"]
            print(f"  {stage:<28} {t['mean']:>9,.0f} {t['min']:>9,.0f} {t['max']:>9,.0f} "
                  f"{t['stddev']:>8,.1f} {w['mean']:>14,.1f}  {t['n']}")
    print("\n" + "─" * 100)


# ---------------------------------------------------------------------------
# report: end-to-end markdown baseline doc
# ---------------------------------------------------------------------------


def _bytes_to_tokens(n: int) -> int:
    """Rough estimate: 4 bytes per token, +5% BPE overhead. Good enough for relative compare."""
    return int(round(n / 4 * 1.05))


def render_baseline_md(repo_root: Path,
                       hot_path: dict,
                       runs: list[dict],
                       aggregate: dict,
                       generated_at: str) -> str:
    out = io.StringIO()
    out.write("# AIDLC Orchestrator — Refactor Baseline\n\n")
    out.write(f"**Generated:** {generated_at}\n")
    out.write(f"**Primary repo:** `{repo_root}`\n")
    out.write(f"**Tool:** `aidlc-scripts/factory_telemetry.py report`\n\n")
    out.write("This document is re-generated by the harness. Re-run after each refactor\n")
    out.write("phase to capture deltas. The baseline is sourced from REAL runs on disk\n")
    out.write("(across multiple sibling AIDLC repos when `--scan-siblings` is used) so\n")
    out.write("no session needs to spawn three live `/factory-spec` invocations.\n\n")
    out.write("---\n\n")

    out.write("## 1. Hot-path inventory (static)\n\n")
    out.write(f"Source: `{hot_path['source']}`\n\n")
    out.write(f"- **Total:** {hot_path['total_bytes']:,} bytes / {hot_path['total_lines']:,} lines / "
              f"{hot_path['section_count']} H2 sections\n")
    out.write(f"- **Heuristic kernel-token load** (≈4B/token + 5% BPE): "
              f"**{_bytes_to_tokens(hot_path['total_bytes']):,} tokens**\n\n")

    out.write("**Top sections by size:**\n\n")
    out.write("| Reach | Bytes | Lines | Redundancy | Boilerplate | Pointers | Title |\n")
    out.write("|---|---:|---:|---:|---:|---:|---|\n")
    for r in sorted(hot_path["sections"], key=lambda r: r["bytes"], reverse=True)[:10]:
        out.write(f"| {r['reach']} | {r['bytes']:,} | {r['lines']:,} | {r['redundancy']:.2f} | "
                  f"{r['boilerplate_hit_total']} | {r['pointer_hit_total']} | {r['title']} |\n")

    boiler_total = sum(r["boilerplate_hit_total"] for r in hot_path["sections"])
    pointer_total = sum(r["pointer_hit_total"] for r in hot_path["sections"])
    out.write("\n**Boilerplate phrase occurrences** (target=0):\n\n")
    if boiler_total:
        bp_totals: Counter = Counter()
        for r in hot_path["sections"]:
            for p, n in r["audit_phrase_hits"].items():
                if p in BOILERPLATE_PHRASES:
                    bp_totals[p] += n
        out.write("| Hits | Phrase |\n|---:|---|\n")
        for phrase, n in bp_totals.most_common():
            rendered = f"<code>{phrase}</code>" if "`" in phrase else f"`{phrase}`"
            out.write(f"| {n} | {rendered} |\n")
    else:
        out.write("_None — all boilerplate eliminated._\n")
    out.write(f"\n**Pointer references** (target=N): {pointer_total}\n")
    if pointer_total:
        ptr_totals: Counter = Counter()
        for r in hot_path["sections"]:
            for p, n in r["audit_phrase_hits"].items():
                if p in POINTER_PHRASES:
                    ptr_totals[p] += n
        out.write("| Hits | Phrase |\n|---:|---|\n")
        for phrase, n in ptr_totals.most_common():
            out.write(f"| {n} | `{phrase}` |\n")

    out.write(f"\n**Total boilerplate+pointer hits:** {boiler_total + pointer_total}\n\n")

    cold = sum(r["bytes"] for r in hot_path["sections"] if r["reach"] == "cold")
    hot = sum(r["bytes"] for r in hot_path["sections"] if r["reach"] == "hot")
    always = sum(r["bytes"] for r in hot_path["sections"] if r["reach"] == "always")
    out.write("**Reach breakdown:**\n\n")
    out.write(f"- always: {always:,} bytes\n")
    out.write(f"- hot:    {hot:,} bytes\n")
    out.write(f"- cold:   {cold:,} bytes  ← TODO Phase 3 target\n\n")

    out.write("---\n\n## 2. Discovered runs (real telemetry on disk)\n\n")
    out.write(f"**Total runs discovered:** {len(runs)}  across "
              f"{len(set(r['repo_root'] for r in runs))} repo root(s).\n\n")
    out.write("> **Tier legend:** `UNKNOWN` means the manifest has no `complexity_tier`\n"
              "> field and the heuristic (skip-stages + unit count) couldn't classify the\n"
              "> run — normal for runs that crashed before the Complexity Routing Gate.\n"
              "> The token data is still usable as a baseline.\n\n")
    out.write("| Tier | Status | Tokens | Stages | Events | Run ID | Project |\n")
    out.write("|---|---|---:|---:|---:|---|---|\n")
    for r in runs:
        out.write(f"| {r['tier']} | {r['status']} | {r['total_tokens']:,} | "
                  f"{len(r['completed_stages'])} | {r['event_count']} | "
                  f"`{r['run_id']}` | {r['project_slug']} |\n")

    out.write("\n---\n\n## 3. Aggregated per-tier baselines\n\n")
    if not aggregate:
        out.write("_No runs discovered. Re-run with `--scan-siblings` or pass `--root`._\n\n")
    for tier in sorted(aggregate):
        data = aggregate[tier]
        out.write(f"### Tier {tier} — {data['run_count']} run(s)\n\n")
        tt = data["total_tokens"]
        out.write(f"- **Total tokens/run:** mean={tt['mean']:,.0f}  "
                  f"min={tt['min']:,.0f}  max={tt['max']:,.0f}  σ={tt['stddev']:,.0f}  n={tt['n']}\n\n")
        out.write("| Stage | Mean tokens | Min | Max | σ | Wall min (avg) | n |\n")
        out.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for stage, s in data["per_stage"].items():
            t, w = s["tokens"], s["wall_min"]
            out.write(f"| {stage} | {t['mean']:,.0f} | {t['min']:,.0f} | {t['max']:,.0f} | "
                      f"{t['stddev']:,.1f} | {w['mean']:.1f} | {t['n']} |\n")
        out.write("\n")

    out.write("---\n\n## 4. Baseline numbers locked for refactor comparison\n\n")
    out.write("These are the headline numbers that every post-refactor re-run MUST diff against:\n\n")
    out.write(f"- `BASELINE_KERNEL_BYTES` = **{hot_path['total_bytes']:,}**\n")
    out.write(f"- `BASELINE_KERNEL_TOKENS_EST` = **{_bytes_to_tokens(hot_path['total_bytes']):,}**\n")
    out.write(f"- `BASELINE_BOILERPLATE_HITS` = **{boiler_total}**\n")
    out.write(f"- `BASELINE_COLD_PATH_BYTES` = **{cold:,}**\n")
    for tier in ("SMALL", "MEDIUM", "LARGE", "UNKNOWN"):
        if tier in aggregate:
            mean = aggregate[tier]["total_tokens"]["mean"]
            out.write(f"- `BASELINE_{tier}_TOKENS_MEAN` = **{mean:,.0f}** (n={aggregate[tier]['run_count']})\n")

    out.write("\n---\n\n## 5. How to re-generate this report\n\n")
    out.write("```bash\n")
    out.write("python3 aidlc-scripts/factory_telemetry.py report \\\n")
    out.write("    --scan-siblings --auto-discover \\\n")
    out.write("    --baseline aidlc-docs/refactor/baseline-<date>.md\n")
    out.write("```\n\n")
    out.write("Run after each refactor phase. Commit each generated file so deltas\n")
    out.write("are reviewable in git history. The harness is idempotent and safe to\n")
    out.write("re-run; it never mutates run state.\n")
    return out.getvalue()


def cmd_report(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else DEFAULT_REPO_ROOT
    md_path = orchestrator_md(repo_root)
    if not md_path.exists():
        print(f"no orchestrator.md at {md_path}", file=sys.stderr)
        sys.exit(2)
    hp = hot_path_report(md_path)

    roots = [Path(r) for r in (args.root or [str(repo_root)])]
    runs = discover_runs(roots, scan_siblings=args.scan_siblings) if args.auto_discover else []
    agg = aggregate_runs(runs) if runs else {}

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    md = render_baseline_md(repo_root, hp, runs, agg, generated_at)

    if args.baseline:
        out_path = Path(args.baseline).expanduser()
    else:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = repo_root / "aidlc-docs" / "refactor" / f"baseline-{date}.md"
    if not out_path.is_absolute():
        out_path = (repo_root / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)
    print(f"baseline report written to: {out_path}")

    if args.json:
        json_path = Path(args.json).expanduser()
        if not json_path.is_absolute():
            json_path = (repo_root / json_path).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({
            "generated_at": generated_at,
            "repo_root": str(repo_root),
            "hot_path": hp,
            "discovered_runs": runs,
            "aggregate": agg,
        }, indent=2))
        print(f"JSON snapshot written to: {json_path}")


# ---------------------------------------------------------------------------
# argparse plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory_telemetry.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    hp = sub.add_parser("hot-path", help="static markdown hot-path inventory")
    hp.add_argument("file")
    hp.add_argument("--json", default=None)
    hp.set_defaults(func=cmd_hot_path)

    ct = sub.add_parser("count-tokens", help="per-stage CSV from a run's timeline")
    ct.add_argument("run_id")
    ct.add_argument("--repo-root", default=None,
                    help="path to repo root containing .aidlc-orchestrator/runs/ (default: AIDLC_ROOT)")
    ct.add_argument("--out", default=None)
    ct.set_defaults(func=cmd_count_tokens)

    ds = sub.add_parser("discover", help="walk repo roots for runs")
    ds.add_argument("--root", action="append", default=None,
                    help="repo root to scan; repeatable. Default: AIDLC_ROOT")
    ds.add_argument("--scan-siblings", action="store_true",
                    help="also scan adjacent dirs at parent level for .aidlc-orchestrator/")
    ds.add_argument("--json", default=None)
    ds.set_defaults(func=cmd_discover)

    ag = sub.add_parser("aggregate", help="per-tier per-stage stats across runs")
    ag.add_argument("--run", action="append", default=None,
                    help="path to a run directory (containing manifest.yaml); repeatable")
    ag.add_argument("--auto-discover", action="store_true",
                    help="auto-discover runs from --root (default: AIDLC_ROOT)")
    ag.add_argument("--root", action="append", default=None)
    ag.add_argument("--scan-siblings", action="store_true")
    ag.add_argument("--json", default=None)
    ag.set_defaults(func=cmd_aggregate)

    rp = sub.add_parser("report", help="generate full markdown baseline report")
    rp.add_argument("--repo-root", default=None)
    rp.add_argument("--root", action="append", default=None)
    rp.add_argument("--scan-siblings", action="store_true")
    rp.add_argument("--auto-discover", action="store_true")
    rp.add_argument("--baseline", default=None,
                    help="output markdown path (default: aidlc-docs/refactor/baseline-<date>.md)")
    rp.add_argument("--json", default=None,
                    help="also dump combined hot-path + runs + aggregate as JSON")
    rp.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
