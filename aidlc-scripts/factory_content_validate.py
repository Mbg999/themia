#!/usr/bin/env python3
"""factory_content_validate.py — Semantic content validators for AIDLC stage artifacts.

Where `factory_validate.py` checks the YAML/JSON envelope, this script checks
the artifact *content* itself.

Subcommands:
    requirements <handoff>  Validate requirements-analyst artifacts (Phase 1.1).
    plan         <handoff>  Validate workflow-planner artifact (Mermaid + task tree).
    code         <handoff>  Validate code-generator artifacts (source files + tests).
    tests        <handoff>  Validate build-test-agent artifacts (build + test summary).
    ship         <handoff>  Validate ship-agent artifacts (release notes + ADRs).

Modes:
    --mode warn    Print issues, always exit 0 (default — soft launch).
    --mode strict  Print issues, exit non-zero on any failure.

Exit codes:
    0  PASS (no issues, or warn mode)
    1  FAIL (strict mode and ≥1 issue)
    2  usage error / missing files / malformed input
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

ORCHESTRATOR_VERSION = "0.2.0"

# Axes required at each depth, mirroring
# .agents/custom-skills/requirements-intelligence/coverage-map.md §"Depth → axis matrix"
REQUIRED_AXES_BY_DEPTH: dict[str, list[str]] = {
    "minimal": ["Purpose", "Needs", "Expectations", "Acceptance"],
    "standard": ["Purpose", "Needs", "Limits", "Expectations", "Context", "Acceptance"],
    "comprehensive": [
        "Purpose", "Needs", "Limits", "Expectations",
        "Context", "Risks", "Acceptance", "Unknowns",
    ],
}

ALL_AXES = REQUIRED_AXES_BY_DEPTH["comprehensive"]

# `<!-- axis: Purpose -->` or `<!-- axis: Purpose, Needs -->` immediately before a Question header
AXIS_TAG_RE = re.compile(
    r"<!--\s*axis:\s*(?P<axes>[A-Za-z][A-Za-z ,]*?)\s*-->",
    re.IGNORECASE,
)

# `## Question N` or `## Question` — the MCQ header
QUESTION_HEADER_RE = re.compile(r"^##\s+Question\b", re.MULTILINE)

# `[Answer]:` — every question must contain this tag
ANSWER_TAG_RE = re.compile(r"\[Answer\]:", re.MULTILINE)

# `X) Other` or `F) Other` etc — every MCQ must have an Other option
OTHER_OPTION_RE = re.compile(r"^[A-Z]\)\s+Other\b", re.MULTILINE)

# `[CoverageMap]` audit entry markdown table row referring to an axis,
# e.g.  `| Purpose | all | Q1 | covered |`
COVERAGE_MAP_ROW_RE = re.compile(
    r"^\|\s*(?P<axis>[A-Za-z]+)\s*\|"
    r"\s*[^|]+\s*\|"
    r"\s*(?P<question_ids>[^|]*?)\s*\|"
    r"\s*(?P<status>covered|inferred-from-request|skipped)\s*\|",
    re.IGNORECASE | re.MULTILINE,
)


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_content_validate: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}", file=sys.stderr)


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _load_handoff_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _die(f"could not parse {path}: {exc}")


def _resolve_artifact(repo_root: Path, artifact_path: str) -> Path:
    """Artifact paths in handoffs are repo-relative."""
    p = Path(artifact_path)
    return p if p.is_absolute() else (repo_root / p)


def _find_questions_file(handoff: dict, repo_root: Path) -> Path | None:
    # First try explicit `questions_artifact_path`
    qp = handoff.get("questions_artifact_path")
    if qp:
        return _resolve_artifact(repo_root, qp)
    # Fall back to artifacts[] entry with kind == 'questions'
    for art in handoff.get("artifacts", []) or []:
        if art.get("kind") == "questions":
            return _resolve_artifact(repo_root, art["path"])
    return None


def _find_requirements_file(handoff: dict, repo_root: Path) -> Path | None:
    for art in handoff.get("artifacts", []) or []:
        if art.get("kind") == "spec":
            return _resolve_artifact(repo_root, art["path"])
    return None


def _parse_axis_tags(questions_text: str) -> dict[str, list[int]]:
    """Return {axis_name: [question_index, ...]} from `<!-- axis: X -->` tags.

    Indexing: question index is the ordinal of the next `## Question` header
    after the axis tag. Multi-axis tags (`<!-- axis: Limits, Context -->`)
    contribute the same question index to each named axis.
    """
    # Map each axis tag position → next question header position
    coverage: dict[str, list[int]] = {a: [] for a in ALL_AXES}
    # Find all question headers and their positions
    question_positions = [m.start() for m in QUESTION_HEADER_RE.finditer(questions_text)]
    if not question_positions:
        return coverage

    def _which_question(pos: int) -> int | None:
        """Return 1-based index of the next question header at-or-after pos."""
        for i, qp in enumerate(question_positions, start=1):
            if qp >= pos:
                return i
        return None

    for m in AXIS_TAG_RE.finditer(questions_text):
        idx = _which_question(m.start())
        if idx is None:
            continue
        axes_str = m.group("axes")
        for raw in axes_str.split(","):
            axis = raw.strip().title()
            if axis in coverage:
                coverage[axis].append(idx)
    return coverage


def _parse_coverage_map_claims(audit_entries: Iterable[str]) -> dict[str, str]:
    """Return {axis: status} from `[CoverageMap]` audit entries.

    Audit entries are strings — may be a single string with embedded newlines
    (the markdown table) or one string per row. We scan all of them.
    """
    claims: dict[str, str] = {}
    joined = "\n".join(str(e) for e in audit_entries)
    if "[CoverageMap]" not in joined:
        return claims
    for m in COVERAGE_MAP_ROW_RE.finditer(joined):
        axis = m.group("axis").title()
        status = m.group("status").lower()
        if axis in ALL_AXES:
            claims[axis] = status
    return claims


def _validate_question_format(questions_text: str) -> list[str]:
    """Return list of format violations: questions without [Answer]: or X) Other."""
    issues: list[str] = []
    # Split text into per-question blocks by the `## Question` header
    blocks = re.split(r"^##\s+Question.*$", questions_text, flags=re.MULTILINE)[1:]
    for i, block in enumerate(blocks, start=1):
        if not ANSWER_TAG_RE.search(block):
            issues.append(f"Question {i}: missing [Answer]: tag")
        if not OTHER_OPTION_RE.search(block):
            issues.append(f"Question {i}: missing 'X) Other' option")
    return issues


def cmd_requirements(args: argparse.Namespace) -> int:
    """Validate requirements-analyst output."""
    handoff_path = Path(args.output_handoff).resolve()
    if not handoff_path.exists():
        _die(f"output handoff not found: {handoff_path}")

    repo_root = handoff_path
    # walk up until we find a marker — .aidlc-orchestrator dir is the canonical anchor
    while repo_root != repo_root.parent:
        if (repo_root / ".aidlc-orchestrator").is_dir():
            break
        repo_root = repo_root.parent
    else:
        repo_root = handoff_path.parent

    handoff = _load_handoff_yaml(handoff_path)
    depth = handoff.get("depth", "standard")
    if depth not in REQUIRED_AXES_BY_DEPTH:
        _warn(f"unrecognized depth '{depth}' — defaulting to 'standard'")
        depth = "standard"

    required = REQUIRED_AXES_BY_DEPTH[depth]
    print(f"factory_content_validate: requirements (depth={depth}, mode={args.mode})")
    print(f"  required axes: {', '.join(required)}")

    issues: list[str] = []

    # PASS 1 OR PASS 2? Determine from status.
    status = handoff.get("status", "")
    is_pass1 = status == "needs_human" or handoff.get("needs_user_input", False)

    # --- Questions file checks (Pass 1) ---
    questions_path = _find_questions_file(handoff, repo_root)

    # Trivial-clear-singlefile escape path: explicit skip recorded
    classification = handoff.get("request_classification", {}) or {}
    trivial_skip = (
        classification.get("clarity") == "Clear"
        and classification.get("complexity") == "Trivial"
        and classification.get("scope") == "Single File"
        and questions_path is None
    )

    if questions_path is None and not trivial_skip:
        issues.append(
            "no questions artifact found — expected kind:questions or questions_artifact_path"
        )
    elif trivial_skip:
        _ok("questions skip path: Trivial + Clear + Single File")
    else:
        if not questions_path.exists():
            issues.append(f"questions file referenced but missing: {questions_path}")
        else:
            qtext = questions_path.read_text(encoding="utf-8")
            # Format checks
            fmt_issues = _validate_question_format(qtext)
            issues.extend(fmt_issues)

            # Axis-tag coverage
            tagged_axes = _parse_axis_tags(qtext)
            covered_axes = {axis for axis, qs in tagged_axes.items() if qs}
            missing_required = [a for a in required if a not in covered_axes]

            if missing_required:
                issues.append(
                    "axes required at depth '%s' have no `<!-- axis: %s -->` tag in questions file: %s"
                    % (depth, "{X}", ", ".join(missing_required))
                )
            else:
                _ok(f"all {len(required)} required axes are tagged in questions file")

            # Cross-check audit-entry claims vs actual tags
            audit = handoff.get("audit_entries", []) or []
            claims = _parse_coverage_map_claims(audit)
            for axis, status_claim in claims.items():
                if status_claim == "covered" and not tagged_axes.get(axis):
                    issues.append(
                        f"[CoverageMap] claims '{axis}: covered' but no questions are tagged "
                        f"`<!-- axis: {axis} -->`"
                    )

            if claims:
                _ok(f"[CoverageMap] audit claims parsed: {len(claims)} axis assertions")
            elif not is_pass1:
                # Pass 2 may or may not re-emit; not strictly required
                pass
            else:
                issues.append("Pass 1: no [CoverageMap] audit entry found")

    # --- Requirements doc checks (Pass 2) ---
    if not is_pass1:
        req_path = _find_requirements_file(handoff, repo_root)
        if req_path is None:
            issues.append("Pass 2: no requirements artifact (kind:spec) found")
        elif not req_path.exists():
            issues.append(f"Pass 2: requirements file referenced but missing: {req_path}")
        else:
            rtext = req_path.read_text(encoding="utf-8")
            if len(rtext.strip()) < 200:
                issues.append(
                    f"Pass 2: requirements.md is suspiciously short "
                    f"({len(rtext.strip())} chars) — likely empty spec"
                )
            else:
                _ok(f"requirements.md present ({len(rtext)} chars)")

    # --- Verdict ---
    if not issues:
        print("PASS")
        return 0

    print(f"\n{len(issues)} issue(s) found:")
    for i in issues:
        _fail(i)

    if args.mode == "strict":
        print("\nFAIL (strict mode)", file=sys.stderr)
        return 1
    else:
        print("\nWARN (warn mode — non-blocking; flip to --mode strict to enforce)")
        return 0


# ---------- Phase 1 expansion — additional stage validators ----------


MERMAID_FENCE_RE = re.compile(r"```mermaid\b[\s\S]+?```", re.MULTILINE)
TASK_CHECKBOX_RE = re.compile(r"^\s*-\s+\[[ x]\]\s+", re.MULTILINE)
ACCEPTANCE_LINE_RE = re.compile(
    r"^\s*(?:-\s+)?(?:Acceptance|AC|Acceptance criteria|acceptance_criteria):",
    re.IGNORECASE | re.MULTILINE,
)
ADR_PATH_RE = re.compile(r"aidlc-docs/operations/adrs/[^\s\"']+\.md")


def _find_artifact(handoff: dict, repo_root: Path, kind: str) -> Path | None:
    for art in handoff.get("artifacts", []) or []:
        if art.get("kind") == kind:
            return _resolve_artifact(repo_root, art["path"])
    return None


def _all_artifacts(handoff: dict, repo_root: Path, kind: str) -> list[Path]:
    return [
        _resolve_artifact(repo_root, a["path"])
        for a in (handoff.get("artifacts", []) or [])
        if a.get("kind") == kind
    ]


def _resolve_repo_root(handoff_path: Path) -> Path:
    p = handoff_path.parent
    while p != p.parent:
        if (p / ".aidlc-orchestrator").is_dir():
            return p
        p = p.parent
    return handoff_path.parent


def _verdict(issues: list[str], mode: str) -> int:
    if not issues:
        print("PASS")
        return 0
    print(f"\n{len(issues)} issue(s) found:")
    for i in issues:
        _fail(i)
    if mode == "strict":
        print("\nFAIL (strict mode)", file=sys.stderr)
        return 1
    print("\nWARN (warn mode — non-blocking; flip to --mode strict to enforce)")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Validate workflow-planner output."""
    handoff_path = Path(args.output_handoff).resolve()
    if not handoff_path.exists():
        _die(f"output handoff not found: {handoff_path}")

    repo_root = _resolve_repo_root(handoff_path)
    handoff = _load_handoff_yaml(handoff_path)

    print(f"factory_content_validate: plan (mode={args.mode})")
    issues: list[str] = []

    plan_path = _find_artifact(handoff, repo_root, "plan")
    if plan_path is None:
        issues.append("no plan artifact (kind:plan) found")
        return _verdict(issues, args.mode)
    if not plan_path.exists():
        issues.append(f"plan artifact referenced but missing: {plan_path}")
        return _verdict(issues, args.mode)

    text = plan_path.read_text(encoding="utf-8")

    if len(text.strip()) < 200:
        issues.append(
            f"plan is suspiciously short ({len(text.strip())} chars) — likely empty"
        )

    # Mermaid diagram
    if not MERMAID_FENCE_RE.search(text):
        issues.append("plan has no ```mermaid ``` fence — Mermaid diagram missing")
    else:
        _ok("Mermaid fence present")

    # Task tree
    task_count = len(TASK_CHECKBOX_RE.findall(text))
    if task_count == 0:
        issues.append("plan has no `- [ ]` or `- [x]` task checkboxes")
    else:
        _ok(f"task checkboxes present: {task_count}")

    # Acceptance coverage — heuristic: each task should be close to an acceptance line
    ac_count = len(ACCEPTANCE_LINE_RE.findall(text))
    if ac_count == 0:
        issues.append("plan has no Acceptance/AC line — every leaf task needs ≥1")
    elif ac_count < task_count // 2:
        issues.append(
            f"plan has {ac_count} acceptance line(s) for {task_count} task(s) — coverage seems thin"
        )

    # Units list coherence
    units = handoff.get("units") or []
    declared_unit_names = {u.get("name") for u in units if isinstance(u, dict)}
    if not declared_unit_names:
        issues.append("handoff `units[]` is empty — workflow-planner must declare units")
    else:
        # Each declared unit should be referenced in the plan text
        unreferenced = [
            u for u in declared_unit_names if u and u not in text
        ]
        if unreferenced:
            issues.append(
                f"units declared in handoff but not referenced in plan: {', '.join(unreferenced)}"
            )

    # Mermaid validation flag
    if handoff.get("mermaid_validated") is False:
        issues.append("handoff says mermaid_validated=false — diagram not validated")

    return _verdict(issues, args.mode)


def cmd_code(args: argparse.Namespace) -> int:
    """Validate code-generator output."""
    handoff_path = Path(args.output_handoff).resolve()
    if not handoff_path.exists():
        _die(f"output handoff not found: {handoff_path}")

    repo_root = _resolve_repo_root(handoff_path)
    handoff = _load_handoff_yaml(handoff_path)

    print(f"factory_content_validate: code (mode={args.mode})")
    issues: list[str] = []

    source_files = _all_artifacts(handoff, repo_root, "source")
    if not source_files:
        issues.append("no source artifacts (kind:source) found")
    else:
        missing = [p for p in source_files if not p.exists()]
        if missing:
            issues.append(
                f"{len(missing)} declared source file(s) missing: " +
                ", ".join(str(p.relative_to(repo_root)) for p in missing[:5])
            )
        else:
            _ok(f"all {len(source_files)} source files exist")

    test_files = _all_artifacts(handoff, repo_root, "test")
    if not test_files:
        issues.append(
            "no test artifacts (kind:test) — TDD requires generated tests alongside source"
        )
    else:
        _ok(f"{len(test_files)} test file(s) declared")

    # locks_to_release — when populated, must include each touched glob
    if handoff.get("locks_to_release") is None:
        issues.append("handoff has no locks_to_release[] — required for code stage")

    return _verdict(issues, args.mode)


def cmd_tests(args: argparse.Namespace) -> int:
    """Validate build-test-agent output."""
    handoff_path = Path(args.output_handoff).resolve()
    if not handoff_path.exists():
        _die(f"output handoff not found: {handoff_path}")

    repo_root = _resolve_repo_root(handoff_path)
    handoff = _load_handoff_yaml(handoff_path)

    print(f"factory_content_validate: tests (mode={args.mode})")
    issues: list[str] = []

    # Look for the canonical doc artifacts the build-test-agent emits
    docs = _all_artifacts(handoff, repo_root, "doc")
    instructions = [p for p in docs if "build-instructions" in p.name.lower()]
    summary = [p for p in docs if "build-and-test-summary" in p.name.lower()]

    if not instructions:
        issues.append("no build-instructions.md artifact (kind:doc) found")
    if not summary:
        issues.append("no build-and-test-summary.md artifact (kind:doc) found")

    # Summary should attest to a build/test result
    for p in summary:
        if not p.exists():
            issues.append(f"summary referenced but missing: {p}")
            continue
        text = p.read_text(encoding="utf-8").lower()
        if not any(tok in text for tok in ["pass", "passed", "ok", "green"]):
            issues.append(
                f"{p.name}: no 'pass'/'passed'/'ok'/'green' token — "
                f"summary should attest to a build/test outcome"
            )
        else:
            _ok(f"{p.name} attests to build/test result")

    return _verdict(issues, args.mode)


def cmd_ship(args: argparse.Namespace) -> int:
    """Validate ship-agent output."""
    handoff_path = Path(args.output_handoff).resolve()
    if not handoff_path.exists():
        _die(f"output handoff not found: {handoff_path}")

    repo_root = _resolve_repo_root(handoff_path)
    handoff = _load_handoff_yaml(handoff_path)

    print(f"factory_content_validate: ship (mode={args.mode})")
    issues: list[str] = []

    docs = _all_artifacts(handoff, repo_root, "doc")
    artifact_paths_str = " ".join(str(p) for p in docs)

    if not any("release_notes" in p.name.lower() or "release-notes" in p.name.lower()
               for p in docs):
        issues.append("no RELEASE_NOTES artifact (kind:doc) — ship-agent must produce release notes")

    if not any("changelog" in p.name.lower() for p in docs):
        issues.append("no CHANGELOG artifact (kind:doc) — ship-agent must update CHANGELOG")

    if not ADR_PATH_RE.search(artifact_paths_str):
        # Don't fail on missing ADR — small ships may have no ADR-worthy decisions
        # but log a warning so reviewers notice.
        _warn(
            "no ADR file under aidlc-docs/operations/adrs/ — acceptable for trivial "
            "changes but most ships should record at least one ADR"
        )

    # version_proposed (custom field if present in ship contract)
    if handoff.get("version_proposed") is None and "version" not in str(handoff).lower():
        _warn("handoff has no version field — bump intent should be captured somewhere")

    return _verdict(issues, args.mode)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_content_validate.py",
        description="Semantic content validators for AIDLC stage artifacts.",
    )
    parser.add_argument(
        "--mode",
        choices=("warn", "strict"),
        default="warn",
        help="warn (default — print issues, exit 0) or strict (exit 1 on any issue)",
    )
    sub = parser.add_subparsers(dest="stage", required=True)

    p_req = sub.add_parser("requirements", help="Validate requirements-analyst output.")
    p_req.add_argument("output_handoff")
    p_req.set_defaults(func=cmd_requirements)

    p_plan = sub.add_parser("plan", help="Validate workflow-planner output.")
    p_plan.add_argument("output_handoff")
    p_plan.set_defaults(func=cmd_plan)

    p_code = sub.add_parser("code", help="Validate code-generator output.")
    p_code.add_argument("output_handoff")
    p_code.set_defaults(func=cmd_code)

    p_tests = sub.add_parser("tests", help="Validate build-test-agent output.")
    p_tests.add_argument("output_handoff")
    p_tests.set_defaults(func=cmd_tests)

    p_ship = sub.add_parser("ship", help="Validate ship-agent output.")
    p_ship.add_argument("output_handoff")
    p_ship.set_defaults(func=cmd_ship)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
