#!/usr/bin/env python3
"""factory_run.py — Run Manager for AIDLC Orchestrator (Phase 6).

Owns the per-run manifest.yaml (state machine source of truth) and the
timeline.jsonl (append-only event log). Provides resume/replay/legacy-adopt
flows so a crashed orchestration run can be picked up at the last completed
stage.

Subcommands
-----------
    init <run-id> --user-request <text> [--project-slug <slug>] [--force]
        Initialize manifest.yaml and timeline.jsonl for a new run.

    set <run-id> [--field key=value]...
        Set arbitrary top-level manifest fields. JSON-decoded if possible.

    complete-stage <run-id> <stage> [--next-stage <next>]
        Mark a stage complete in manifest.completed_stages[]; update
        last_checkpoint_at; emit a `stage_complete` event. Idempotent.

    fail-stage <run-id> <stage> [--reason <text>]
        Mark a stage failed. Useful for crash recovery records.

    emit <run-id> --evt <name> [--stage <s>] [--field key=value]...
        Append a single event to timeline.jsonl. Used by the orchestrator
        to record arbitrary lifecycle events (spawn_start, spawn_end,
        cost_govern_skip, etc.).

    status <run-id> [--json]
        Print the current manifest.

    resume <run-id>
        Compute the next stage to spawn from manifest.completed_stages[].
        Print a JSON object with: completed_count, current_stage,
        next_stage_suggestion, partial_outputs (any stale handoff files).
        Emit a `resume_requested` event.

    replay <run-id> --from <stage>
        Roll the manifest back: truncate completed_stages[] before <stage>;
        archive output handoffs for rolled-back stages with a .replay-<ts>
        suffix; set current_stage = <stage>. Emit a `replay_requested` event.

    tail <run-id> [--follow] [--json]
        Print timeline events. With --follow, polls every 0.5s like `tail -f`.

Atomicity
---------
manifest.yaml writes use write-tmp-then-rename for atomic updates.
timeline.jsonl is append-only with a single line written per call (atomic
for line-sized writes on POSIX local filesystems).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))
RUNS_ROOT = REPO_ROOT / ".aidlc-orchestrator" / "runs"
AIDLC_DOCS = REPO_ROOT / "aidlc-docs"
SCRIPTS_VERSION = REPO_ROOT / "aidlc-scripts" / "VERSION"

PHASE_ORDER = [
    "workspace-scout",
    "reverse-engineer",
    "requirements-analyst",
    "story-writer",
    "workflow-planner",
    "unit-decomposer",
    "code-generator",
    "build-test-agent",
    "reviewer-code",
    "reviewer-security",
    "reviewer-performance",
    "reviewer-simplifier",
    "ship-agent",
]


_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        _die(f"invalid run_id: {run_id!r}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def run_dir(run_id: str, must_exist: bool = True) -> Path:
    validate_run_id(run_id)
    p = RUNS_ROOT / run_id
    if must_exist and not p.exists():
        _die(f"run not found: {p}")
    return p


def manifest_path(run_id: str) -> Path:
    validate_run_id(run_id)
    return RUNS_ROOT / run_id / "manifest.yaml"


def timeline_path(run_id: str) -> Path:
    validate_run_id(run_id)
    return RUNS_ROOT / run_id / "timeline.jsonl"


def load_manifest(run_id: str) -> dict:
    p = manifest_path(run_id)
    if not p.exists():
        _die(f"manifest not found: {p}")
    return yaml.safe_load(p.read_text()) or {}


def save_manifest_atomic(run_id: str, data: dict) -> None:
    p = manifest_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    tmp.replace(p)


def append_event(run_id: str, event: dict) -> None:
    p = timeline_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _parse_field(kv: str):
    k, _, v = kv.partition("=")
    if not k:
        _die(f"invalid --field: {kv}")
    try:
        return k, json.loads(v)
    except json.JSONDecodeError:
        return k, v


def _set_dotted(obj: dict, dotted_key: str, value) -> None:
    """Set obj[a][b][c] = value given dotted_key 'a.b.c'.

    Intermediate keys missing or non-dict are replaced with empty dicts.
    Single-key (no dot) sets obj[key] = value as before.
    """
    parts = dotted_key.split(".")
    cur = obj
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


# ---------------------------------------------------------------------------
# emit_audit_block — atomic "timeline event + audit.md append" helper.
#
# This compiles the substep-6 canonical sequence from orchestrator.md
# (Step 8 of shared primitives) into one call. The orchestrator used to
# inline the full procedure at every approval gate; that boilerplate now
# lives in `.aidlc-orchestrator/contracts/audit-block.protocol.md` and is
# enforced here.
#
# Canonical evt vocabulary (matches orchestrator.md spec):
#   user_answers_received  — requires --stage
#   user_decision          — requires --stage + --field decision=<approve|reject|amend|cancel>
#   stage_skipped          — requires --stage + --field reason=<text>
#   orchestrator_note      — requires --field summary=<text>
#
# Header format (locked, do not deviate):
#   ## <ts> <PHASE> - <LABEL>
#   - bullet1
#   - bullet2
# ---------------------------------------------------------------------------


AUDIT_BLOCK_EVT_VOCABULARY = {
    "user_answers_received": {"required_stage": True, "required_fields": ()},
    "user_decision":         {"required_stage": True, "required_fields": ("decision",)},
    "stage_skipped":         {"required_stage": True, "required_fields": ("reason",)},
    "orchestrator_note":     {"required_stage": False, "required_fields": ("summary",)},
}

VALID_PHASES = ("INCEPTION", "CONSTRUCTION", "OPERATIONS")


def audit_md_path() -> Path:
    return AIDLC_DOCS / "audit.md"


def _read_last_h2(audit_path: Path) -> tuple[str, str] | None:
    """Return (ts, '<PHASE> - <LABEL>') for the last H2 in audit.md, or None."""
    if not audit_path.exists():
        return None
    last = None
    for line in audit_path.read_text().splitlines():
        if line.startswith("## "):
            last = line
    if not last:
        return None
    # Format: "## <ts> <PHASE> - <LABEL>"
    body = last[3:].strip()
    parts = body.split(None, 1)
    if len(parts) < 2:
        return None
    ts, rest = parts[0], parts[1]
    return (ts, rest)


def _flock(path: Path):
    """Context manager for POSIX advisory exclusive lock on `path`.

    Uses a separate lockfile (path + '.lock') so writers can read+write the
    target safely. Returns a no-op CM on platforms without fcntl (Windows).
    """
    import contextlib

    @contextlib.contextmanager
    def cm():
        try:
            import fcntl
        except ImportError:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        lockfile = path.with_suffix(path.suffix + ".lock")
        with lockfile.open("a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return cm()


def _append_audit_block(ts: str, phase: str, label: str, bullets: list[str]) -> bool:
    """Append a block under flock with a dedupe guard. Returns True if appended,
    False if dedupe'd."""
    audit = audit_md_path()
    with _flock(audit):
        if not audit.exists():
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text("# Audit Log\n\n")

        last = _read_last_h2(audit)
        new_rest = f"{phase} - {label}"
        if last and last[0] == ts and last[1] == new_rest:
            return False  # dedupe

        # Chronology check: never write a header with ts < the last header's ts.
        if last:
            try:
                from datetime import datetime as _dt
                if _dt.fromisoformat(ts) < _dt.fromisoformat(last[0]):
                    _die(f"chronology violation: ts {ts} < last audit ts {last[0]}")
            except (ValueError, TypeError):
                pass  # unparseable — let it through rather than blocking

        # Build the block. Always separate from preceding content by a blank line.
        prior = audit.read_text()
        sep = "" if prior.endswith("\n\n") else ("\n" if prior.endswith("\n") else "\n\n")
        block = f"{sep}## {ts} {new_rest}\n"
        for b in bullets:
            block += f"- {b}\n"
        block += "\n"
        with audit.open("a") as f:
            f.write(block)
    return True


def cmd_emit_audit_block(args: argparse.Namespace) -> None:
    # Validate evt.
    if args.evt not in AUDIT_BLOCK_EVT_VOCABULARY:
        valid = ", ".join(sorted(AUDIT_BLOCK_EVT_VOCABULARY))
        _die(f"unknown evt: {args.evt!r}. Valid evt vocabulary: {valid}")
    rules = AUDIT_BLOCK_EVT_VOCABULARY[args.evt]

    # Validate phase.
    if args.phase not in VALID_PHASES:
        _die(f"invalid phase: {args.phase!r}. Valid phases: {', '.join(VALID_PHASES)}")

    # Validate stage if required.
    if rules["required_stage"] and not args.stage:
        _die(f"evt {args.evt!r} requires --stage")

    # Validate at least one bullet.
    if not args.bullet:
        _die(f"at least one --bullet is required")

    # Validate required fields and parse them.
    fields: dict = {}
    for kv in args.field or []:
        k, v = _parse_field(kv)
        fields[k] = v
    for required in rules["required_fields"]:
        if required not in fields:
            _die(f"evt {args.evt!r} requires --field {required}=<value>")

    # Validate run exists (unless --ts is provided — retry semantics).
    if not args.ts:
        run_dir(args.run_id, must_exist=True)  # _die's if not found

    # Validate label.
    if not args.label:
        _die("--label is required")

    # Determine ts: either explicit (retry) or fresh emit.
    if args.ts:
        ts = args.ts
        # Don't emit a duplicate timeline event on retry; just attempt audit append.
    else:
        ts = now_iso()
        event = {"ts": ts, "evt": args.evt, "run_id": args.run_id, **fields}
        if args.stage:
            event["stage"] = args.stage
        append_event(args.run_id, event)

    appended = _append_audit_block(ts, args.phase, args.label, args.bullet)
    if appended:
        print(ts)
    else:
        print(f"{ts} (dedupe skipped — identical block already present)")


def cmd_init(args: argparse.Namespace) -> None:
    rd = run_dir(args.run_id, must_exist=False)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "handoffs").mkdir(exist_ok=True)
    if manifest_path(args.run_id).exists() and not args.force:
        _die(f"manifest already exists at {manifest_path(args.run_id)}; use --force")

    orch_version = "unknown"
    if SCRIPTS_VERSION.exists():
        orch_version = SCRIPTS_VERSION.read_text().strip()
    manifest = {
        "run_id": args.run_id,
        "started_at": now_iso(),
        "last_checkpoint_at": now_iso(),
        "user_request": args.user_request,
        "project_slug": args.project_slug or REPO_ROOT.name.lower().replace(" ", "-"),
        "current_stage": "workspace-scout",
        "completed_stages": [],
        "skipped_stages": [],
        "failed_stages": [],
        "orchestrator_version": orch_version,
        "project_profile": {"ui": False, "api": False, "has_legacy": False},
        "units": [],
        "skill_paths": {},
    }
    save_manifest_atomic(args.run_id, manifest)
    append_event(args.run_id, {
        "ts": now_iso(),
        "evt": "run_init",
        "run_id": args.run_id,
        "user_request": args.user_request,
    })
    print(f"initialized run {args.run_id} at {rd}")


def cmd_set(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    for kv in args.field or []:
        k, v = _parse_field(kv)
        _set_dotted(manifest, k, v)
    manifest["last_checkpoint_at"] = now_iso()
    save_manifest_atomic(args.run_id, manifest)
    print(f"updated {len(args.field or [])} field(s)")


def _reconcile_state(run_id: str) -> dict:
    """Check for drift between manifest, timeline, and budget.

    Returns a dict with drift info:
      completed_not_in_timeline: stages in manifest but no timeline event
      budget_calls_not_in_timeline: budget deducts with no matching event
      last_action: last known action from manifest
    """
    drift: dict = {"drift": False, "details": []}
    manifest_p = manifest_path(run_id)
    if not manifest_p.exists():
        return drift
    manifest = yaml.safe_load(manifest_p.read_text()) or {}

    timeline_p = timeline_path(run_id)
    timeline_stages: set[str] = set()
    if timeline_p.exists():
        for line in timeline_p.read_text().splitlines():
            try:
                e = json.loads(line)
                if e.get("evt") == "stage_complete" and e.get("stage"):
                    timeline_stages.add(e["stage"])
            except json.JSONDecodeError:
                continue

    completed = set(manifest.get("completed_stages", []))
    missing = completed - timeline_stages
    if missing:
        drift["drift"] = True
        drift["details"].append({
            "kind": "completed_not_in_timeline",
            "stages": sorted(missing),
        })

    last_action = manifest.get("last_action_reason")
    if last_action:
        drift["last_action"] = last_action

    return drift


def cmd_complete_stage(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    if args.stage in manifest["completed_stages"]:
        print(f"stage {args.stage} already complete (idempotent)")
        return
    manifest["completed_stages"].append(args.stage)
    manifest["last_checkpoint_at"] = now_iso()
    if args.reason:
        manifest["last_action_reason"] = args.reason
    if args.next_stage:
        manifest["current_stage"] = args.next_stage
    save_manifest_atomic(args.run_id, manifest)
    append_event(args.run_id, {
        "ts": now_iso(),
        "evt": "stage_complete",
        "run_id": args.run_id,
        "stage": args.stage,
        "next_stage": args.next_stage,
        "reason": args.reason,
    })
    print(f"marked {args.stage} complete")


def cmd_fail_stage(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    failures = manifest.setdefault("failed_stages", [])
    failures.append({"stage": args.stage, "reason": args.reason or "unspecified", "at": now_iso()})
    manifest["last_checkpoint_at"] = now_iso()
    save_manifest_atomic(args.run_id, manifest)
    append_event(args.run_id, {
        "ts": now_iso(),
        "evt": "stage_failed",
        "run_id": args.run_id,
        "stage": args.stage,
        "reason": args.reason,
    })
    print(f"marked {args.stage} failed: {args.reason or 'unspecified'}")


def cmd_emit(args: argparse.Namespace) -> None:
    fields = {}
    for kv in args.field or []:
        k, v = _parse_field(kv)
        fields[k] = v
    event = {"ts": now_iso(), "evt": args.evt, "run_id": args.run_id, **fields}
    if args.stage:
        event["stage"] = args.stage
    append_event(args.run_id, event)
    print(json.dumps(event))


def _print_latency(run_id: str, manifest: dict) -> None:
    timeline_p = timeline_path(run_id)
    if not timeline_p.exists():
        print("no timeline available")
        return
    events: list[dict] = []
    for line in timeline_p.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    ne, sp, sd = None, None, None
    for e in events:
        if e.get("evt") == "needs_human":
            ne = e.get("ts")
        elif e.get("evt") == "spawn_end":
            sp = e.get("ts")
        elif e.get("evt") == "user_decision":
            sd = e.get("ts")

    lines = [f"Approval Gate Latency: {run_id}", "─" * 60]
    if ne and sd:
        try:
            from datetime import datetime as dt
            dur = (dt.fromisoformat(sd) - dt.fromisoformat(ne)).total_seconds() / 60.0
            lines.append(f"  needs_human → user_decision:  {dur:.1f}m")
        except (ValueError, TypeError):
            lines.append("  needs_human → user_decision:  parse error")
    elif ne:
        lines.append("  needs_human → user_decision:  pending (no decision yet)")
    if sp and sd:
        try:
            from datetime import datetime as dt
            total = (dt.fromisoformat(sd) - dt.fromisoformat(sp)).total_seconds() / 60.0
            lines.append(f"  spawn_end → user_decision:   {total:.1f}m")
        except (ValueError, TypeError):
            lines.append("  spawn_end → user_decision:    parse error")

    # Per-stage latency from timeline
    stage_events: dict[str, dict] = {}
    for e in events:
        stage = e.get("stage")
        if not stage:
            continue
        if stage not in stage_events:
            stage_events[stage] = {}
        if e["evt"] in ("spawn_start", "stage_start"):
            stage_events[stage]["start"] = e["ts"]
        elif e["evt"] in ("spawn_end", "stage_complete"):
            stage_events[stage]["end"] = e["ts"]
        elif e["evt"] in ("needs_human",):
            stage_events[stage]["needs_human"] = e["ts"]
        elif e["evt"] in ("user_decision",):
            stage_events[stage]["decision"] = e["ts"]

    for stage, ts in sorted(stage_events.items()):
        if ts.get("start") and ts.get("end"):
            try:
                from datetime import datetime as dt
                dur = (dt.fromisoformat(ts["end"]) - dt.fromisoformat(ts["start"])).total_seconds() / 60.0
                lines.append(f"  {stage:30s}  {dur:.1f}m")
            except (ValueError, TypeError):
                pass
        if ts.get("needs_human") and ts.get("decision"):
            try:
                from datetime import datetime as dt
                gate = (dt.fromisoformat(ts["decision"]) - dt.fromisoformat(ts["needs_human"])).total_seconds() / 60.0
                lines.append(f"  {stage:30s}  └─ approval gate: {gate:.1f}m")
            except (ValueError, TypeError):
                pass

    lines.append("─" * 60)
    print("\n".join(lines))


def cmd_status(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    if args.latency:
        _print_latency(args.run_id, manifest)
        return
    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        print(yaml.safe_dump(manifest, default_flow_style=False, sort_keys=False), end="")


def _next_stage(manifest: dict) -> str | None:
    """Compute the next stage to spawn.

    Trust the manifest's current_stage field (set by the orchestrator via
    complete-stage --next-stage), since only the orchestrator knows the
    conditional flow (e.g. whether to skip reverse-engineer in greenfield).
    Fall back to PHASE_ORDER scan only if current_stage is missing or already
    completed. Stages in `skipped_stages[]` are passed over during the scan.
    """
    completed = set(manifest.get("completed_stages", []))
    skipped = set(manifest.get("skipped_stages", []))
    current = manifest.get("current_stage")
    if current and current not in completed and current not in skipped:
        if current in PHASE_ORDER:
            return current
    # Compute start index: after current_stage if in PHASE_ORDER,
    # otherwise after the last completed stage (handles synthetic markers)
    if current and current in PHASE_ORDER:
        start_idx = PHASE_ORDER.index(current) + 1
    else:
        last_idx = max(
            (PHASE_ORDER.index(s) for s in manifest.get("completed_stages", [])
             if s in PHASE_ORDER),
            default=-1
        )
        start_idx = last_idx + 1
    for stage in PHASE_ORDER[start_idx:]:
        if stage not in completed and stage not in skipped:
            return stage
    return None


def cmd_resume(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    completed = manifest["completed_stages"]
    nxt = _next_stage(manifest)

    result: dict = {
        "run_id": args.run_id,
        "completed_count": len(completed),
        "completed_stages": completed,
        "current_stage": manifest.get("current_stage"),
        "next_stage_suggestion": nxt,
        "last_checkpoint_at": manifest.get("last_checkpoint_at"),
    }

    handoffs = run_dir(args.run_id) / "handoffs"
    if handoffs.exists() and nxt:
        partial = sorted(handoffs.glob(f"{nxt}*.output.yaml"))
        if partial:
            result["partial_outputs"] = [str(p.relative_to(REPO_ROOT)) for p in partial]

    # Reconcile state drift
    result["reconcile"] = _reconcile_state(args.run_id)

    # Version compatibility check
    if SCRIPTS_VERSION.exists():
        current_ver = SCRIPTS_VERSION.read_text().strip()
        manifest_ver = manifest.get("orchestrator_version", "0.0.0")
        if manifest_ver != current_ver:
            result["version_warning"] = (
                f"manifest built with orchestrator v{manifest_ver}, "
                f"current scripts are v{current_ver}"
            )

    print(json.dumps(result, indent=2))
    append_event(args.run_id, {
        "ts": now_iso(),
        "evt": "resume_requested",
        "run_id": args.run_id,
        "next_stage": nxt,
    })


def cmd_replay(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.run_id)
    target = args.from_stage
    if target not in manifest["completed_stages"]:
        _die(f"cannot replay from {target}: not in completed_stages {manifest['completed_stages']}")

    idx = manifest["completed_stages"].index(target)
    rolled_back = manifest["completed_stages"][idx:]
    manifest["completed_stages"] = manifest["completed_stages"][:idx]
    manifest["current_stage"] = target
    manifest["last_checkpoint_at"] = now_iso()

    archived: list[str] = []
    handoffs = run_dir(args.run_id) / "handoffs"
    if handoffs.exists():
        ts = int(time.time())
        for stage in rolled_back:
            for f in handoffs.glob(f"{stage}*.output.yaml"):
                archived_path = f.with_name(f"{f.stem}.replay-{ts}.yaml")
                f.rename(archived_path)
                archived.append(str(archived_path.relative_to(REPO_ROOT)))

    save_manifest_atomic(args.run_id, manifest)
    append_event(args.run_id, {
        "ts": now_iso(),
        "evt": "replay_requested",
        "run_id": args.run_id,
        "from_stage": target,
        "rolled_back": rolled_back,
        "archived": archived,
    })
    print(json.dumps({
        "replayed_from": target,
        "rolled_back": rolled_back,
        "archived_outputs": archived,
    }, indent=2))




def _print_event(line: str, as_json: bool) -> None:
    if not line:
        return
    if as_json:
        print(line)
        return
    try:
        e = json.loads(line)
        ts = e.get("ts", "")
        evt = e.get("evt", "?")
        stage = e.get("stage", "")
        reserved = {"ts", "evt", "stage", "run_id"}
        details = ", ".join(f"{k}={v}" for k, v in e.items() if k not in reserved)
        print(f"{ts}  {evt:20s} {stage:30s} {details}")
    except json.JSONDecodeError:
        print(f"!malformed: {line}")


def cmd_graph(args: argparse.Namespace) -> None:
    """Print a visual timeline bar chart of a completed run."""
    manifest = load_manifest(args.run_id)
    timeline_p = timeline_path(args.run_id)
    if not timeline_p.exists():
        _die(f"no timeline at {timeline_p}")

    # Parse events
    events: list[dict] = []
    for line in timeline_p.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Build per-stage stats
    stage_stats: dict[str, dict] = {}
    stage_order: list[str] = []
    for evt in events:
        stage = evt.get("stage") or evt.get("evt", "")
        if stage not in stage_stats:
            stage_stats[stage] = {"start": None, "end": None, "evt": evt.get("evt")}
            stage_order.append(stage)
        if evt["evt"] in ("spawn_start", "run_init", "stage_start"):
            stage_stats[stage]["start"] = evt["ts"]
        elif evt["evt"] in ("stage_complete", "spawn_end"):
            stage_stats[stage]["end"] = evt["ts"]
            stage_stats[stage]["status"] = "done"
        elif evt["evt"] == "stage_failed":
            stage_stats[stage]["status"] = "failed"
        elif evt["evt"] == "cost_govern_skip":
            stage_stats[stage]["status"] = "skipped"

    completed = set(manifest.get("completed_stages", []))
    skipped = set(manifest.get("skipped_stages", []))
    failed = set(s.get("stage") for s in manifest.get("failed_stages", []))

    budget_p = RUNS_ROOT / args.run_id / "budget.yaml"
    token_max = 5_000_000
    wall_max = 240
    token_used = 0
    wall_used = 0.0
    if budget_p and budget_p.exists():
        try:
            budget_data = yaml.safe_load(budget_p.read_text()) or {}
            token_used = int(budget_data.get("used", {}).get("tokens", 0))
            wall_used = float(budget_data.get("used", {}).get("wall_clock_min", 0.0))
            token_max = int(budget_data.get("budget", {}).get("tokens_max", token_max))
            wall_max = float(budget_data.get("budget", {}).get("wall_clock_max_min", wall_max))
        except (ValueError, TypeError):
            pass

    # Only show PHASE_ORDER stages
    bar_width = 12
    lines = [f"", f"Timeline: {manifest.get('run_id', args.run_id)}", "─" * 60]
    for stage in PHASE_ORDER:
        stats = stage_stats.get(stage, {})
        status = "  "
        prefix = "  "
        if stage in completed:
            status = "✅"
        elif stage in failed:
            status = "❌"
        elif stage in skipped:
            status = "⚠️"
        elif manifest.get("current_stage") == stage:
            status = "▶️ "

        duration_str = ""
        if stats.get("start") and stats.get("end"):
            try:
                from datetime import datetime as dt
                s = dt.fromisoformat(stats["start"])
                e = dt.fromisoformat(stats["end"])
                dur = (e - s).total_seconds() / 60.0
                duration_str = f"{dur:.1f}m"
                fill = min(int(dur / 5), bar_width)
                bar = "█" * fill + "░" * (bar_width - fill)
            except (ValueError, TypeError):
                bar = "░" * bar_width
        else:
            bar = "░" * bar_width

        lines.append(f"  {stage:30s} {bar} {duration_str:8s} {status}")

    token_pct = round((token_used / token_max) * 100, 1) if token_max > 0 else 0
    wall_pct = round((wall_used / wall_max) * 100, 1) if wall_max > 0 else 0
    lines.append("─" * 60)
    lines.append(
        f"Budget: {token_used:,} / {token_max:,} tokens ({token_pct}%)  "
        f"{wall_used} / {wall_max} min ({wall_pct}%)"
    )
    lines.append("")
    print("\n".join(lines))


def cmd_tail(args: argparse.Namespace) -> None:
    p = timeline_path(args.run_id)
    if not p.exists():
        _die(f"no timeline at {p}")

    if not args.follow:
        for line in p.read_text().splitlines():
            _print_event(line, args.json)
        return

    with p.open() as f:
        for line in f:
            _print_event(line.rstrip("\n"), args.json)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            _print_event(line.rstrip("\n"), args.json)


def main() -> None:
    p = argparse.ArgumentParser(description="AIDLC Orchestrator Run Manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("run_id")
    p_init.add_argument("--user-request", required=True)
    p_init.add_argument("--project-slug")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_set = sub.add_parser("set")
    p_set.add_argument("run_id")
    p_set.add_argument("--field", action="append")
    p_set.set_defaults(func=cmd_set)

    p_cs = sub.add_parser("complete-stage")
    p_cs.add_argument("run_id")
    p_cs.add_argument("stage")
    p_cs.add_argument("--next-stage")
    p_cs.add_argument("--reason", help="reason for completion (crash resilience marker)")
    p_cs.set_defaults(func=cmd_complete_stage)

    p_fs = sub.add_parser("fail-stage")
    p_fs.add_argument("run_id")
    p_fs.add_argument("stage")
    p_fs.add_argument("--reason")
    p_fs.set_defaults(func=cmd_fail_stage)

    p_emit = sub.add_parser("emit")
    p_emit.add_argument("run_id")
    p_emit.add_argument("--evt", required=True)
    p_emit.add_argument("--stage")
    p_emit.add_argument("--field", action="append")
    p_emit.set_defaults(func=cmd_emit)

    p_eab = sub.add_parser("emit_audit_block",
        help="atomic timeline-emit + dedupe-guarded audit.md append (substep-6 helper)")
    p_eab.add_argument("run_id")
    p_eab.add_argument("--evt", required=True,
        help="one of: " + ", ".join(sorted(AUDIT_BLOCK_EVT_VOCABULARY)))
    p_eab.add_argument("--stage", help="stage_id (required for most evts)")
    p_eab.add_argument("--phase", required=True,
        help="one of: " + ", ".join(VALID_PHASES))
    p_eab.add_argument("--label", required=True,
        help="block label, e.g. 'User Decision (workflow-planner)'")
    p_eab.add_argument("--field", action="append",
        help="evt-required fields: decision=, reason=, summary= (per evt)")
    p_eab.add_argument("--bullet", action="append",
        help="audit bullet — at least one required; repeatable")
    p_eab.add_argument("--ts",
        help="override emitted ts (retry semantics; skips timeline emit)")
    p_eab.set_defaults(func=cmd_emit_audit_block)

    p_status = sub.add_parser("status")
    p_status.add_argument("run_id")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--latency", action="store_true",
                          help="print approval gate latency breakdown")
    p_status.set_defaults(func=cmd_status)

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("run_id")
    p_resume.set_defaults(func=cmd_resume)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("run_id")
    p_replay.add_argument("--from", dest="from_stage", required=True)
    p_replay.set_defaults(func=cmd_replay)

    p_graph = sub.add_parser("graph", help="visual timeline of a run")
    p_graph.add_argument("run_id")
    p_graph.set_defaults(func=cmd_graph)

    p_tail = sub.add_parser("tail")
    p_tail.add_argument("run_id")
    p_tail.add_argument("--follow", "-f", action="store_true")
    p_tail.add_argument("--json", action="store_true")
    p_tail.set_defaults(func=cmd_tail)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
