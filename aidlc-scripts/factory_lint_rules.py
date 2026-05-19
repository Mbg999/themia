#!/usr/bin/env python3
"""factory_lint_rules.py — Cross-link CI for AIDLC stage agents ↔ contracts ↔ rule files.

Drift between three sources of truth causes silent workflow violations:

1. `.claude/agents/stage/<name>.md` — declares the skill list for the stage.
2. `.aidlc-orchestrator/contracts/<name>.output.v1.json` — enforces
   `skill_compliance.minItems` and the description mentioning required skills.
3. `aidlc-rules/aws-aidlc-rule-details/{inception,construction}/<rule>.md` —
   the "Agent Skills" block the stage agent claims to follow.

This linter catches when any of the three diverge.

Usage:
    python3 aidlc-scripts/factory_lint_rules.py [--repo-root <path>]

Exit codes:
    0  no drift detected
    1  drift detected (details on stderr)
    2  usage error / missing files
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

# Heuristic mapping from stage-agent name to rule-file basename.
# Stages without a rule file are intentional (reviewer-*, unit-decomposer, etc.).
STAGE_TO_RULE_FILE = {
    "workspace-scout": ("inception", "workspace-detection.md"),
    "requirements-analyst": ("inception", "requirements-analysis.md"),
    "reverse-engineer": ("inception", "reverse-engineering.md"),
    "story-writer": ("inception", "user-stories.md"),
    "workflow-planner": ("inception", "workflow-planning.md"),
    "code-generator": ("construction", "code-generation.md"),
    "build-test-agent": ("construction", "build-and-test.md"),
    "ship-agent": ("operations", "shipping.md"),
}

# Captures every backtick-quoted skill-like identifier and whether it's conditional.
# Examples:
#   `skill-name`             → ("skill-name", False)
#   `skill-name*`            → ("skill-name", True)
#   `skill-name/SKILL.md`    → ("skill-name", False)
#   `skill-name/SKILL.md*`   → ("skill-name", True)
SKILL_TOKEN_RE = re.compile(
    r"`([a-z][a-z0-9_-]*?)(/SKILL\.md)?(\*)?`"
)

# Block headers used by stage agents to declare skills (inline OR bulleted)
STAGE_SKILL_BLOCK_HEADER_RE = re.compile(
    r"\*\*Skills(?:\s+required\s+for\s+this\s+stage)?:\*\*", re.IGNORECASE
)

# Block headers used by rule files to declare skills
RULE_SKILL_BLOCK_HEADER_RE = re.compile(r"##\s+Agent\s+Skills\b", re.IGNORECASE)

# Identifiers that look like skill names but should be excluded
# (not real skill names — referenced incidentally in skill block bodies).
NON_SKILL_IDENTIFIERS = {
    "skill-name", "name", "see", "etc",
}


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_lint_rules: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _extract_block(text: str, header_re: re.Pattern[str]) -> str | None:
    """Extract the block of bullets following a matching header.

    The block runs from the header to the next blank-line-followed-by-non-bullet
    or the next top-level header.
    """
    m = header_re.search(text)
    if not m:
        return None
    start = m.end()
    # Walk forward until we hit the next ## header OR the end of file
    rest = text[start:]
    end_match = re.search(r"\n##\s+\w", rest)
    end = start + end_match.start() if end_match else len(text)
    return text[start:end]


def _extract_skills(block_text: str) -> list[tuple[str, bool]]:
    """Extract (skill_name, is_conditional) pairs from a skills declaration block.

    Handles three styles found across the repo:
      1. Bulleted:   - `idea-refine` — description
      2. Bulleted+SKILL.md:   - `idea-refine/SKILL.md` — description
      3. Inline comma-separated:  `using-agent-skills`, `incremental-implementation*`, ...

    Trailing `*` in the original token marks a skill as conditional (runs only
    when its trigger fires). Conditional skills don't count toward
    `skill_compliance.minItems`.

    Filters out NON_SKILL_IDENTIFIERS. Dedupes preserving order.
    """
    skills: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for m in SKILL_TOKEN_RE.finditer(block_text):
        name = m.group(1)
        is_conditional = bool(m.group(3))  # asterisk capture group
        if name in NON_SKILL_IDENTIFIERS:
            continue
        if name in seen:
            continue
        seen.add(name)
        skills.append((name, is_conditional))
    return skills


def _stage_files(repo_root: Path) -> list[Path]:
    d = repo_root / ".claude" / "agents" / "stage"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.md"))


def _contract_path(repo_root: Path, stage_name: str) -> Path | None:
    p = repo_root / ".aidlc-orchestrator" / "contracts" / f"{stage_name}.output.v1.json"
    return p if p.exists() else None


def _rule_file_path(repo_root: Path, stage_name: str) -> Path | None:
    mapping = STAGE_TO_RULE_FILE.get(stage_name)
    if not mapping:
        return None
    phase, fname = mapping
    p = (
        repo_root
        / "aidlc-rules"
        / "aws-aidlc-rule-details"
        / phase
        / fname
    )
    return p if p.exists() else None


def lint(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    stage_files = _stage_files(repo_root)
    if not stage_files:
        return ([f"no stage agents found under {repo_root}/.claude/agents/stage/"], [])

    for stage_path in stage_files:
        stage_name = stage_path.stem
        text = stage_path.read_text(encoding="utf-8")

        stage_block = _extract_block(text, STAGE_SKILL_BLOCK_HEADER_RE)
        if stage_block is None:
            # Some stages (reviewers) declare skills inline via the Skill Execution Protocol.
            # That's OK — only complain if we can't find ANY skill mention.
            if not SKILL_TOKEN_RE.search(text):
                warnings.append(
                    f"{stage_name}: no 'Skills required for this stage' block "
                    f"AND no skill bullets in body — manual review recommended"
                )
            continue

        stage_skills = _extract_skills(stage_block)
        if not stage_skills:
            warnings.append(f"{stage_name}: skills block present but empty")
            continue

        unique_stage_skills = [name for name, _ in stage_skills]
        unconditional_skills = [name for name, cond in stage_skills if not cond]

        # ---- Contract cross-check ----
        contract_path = _contract_path(repo_root, stage_name)
        if contract_path is None:
            warnings.append(
                f"{stage_name}: no output contract at "
                f".aidlc-orchestrator/contracts/{stage_name}.output.v1.json"
            )
        else:
            try:
                schema = json.loads(contract_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{stage_name}: contract is not valid JSON: {exc}")
                continue

            skill_comp = schema.get("properties", {}).get("skill_compliance", {})
            min_items = skill_comp.get("minItems")
            description = skill_comp.get("description", "")

            if min_items is None:
                warnings.append(
                    f"{stage_name}: contract has no skill_compliance.minItems"
                )
            elif min_items < len(unconditional_skills):
                errors.append(
                    f"{stage_name}: contract skill_compliance.minItems={min_items} "
                    f"but stage agent declares {len(unconditional_skills)} unconditional "
                    f"skills ({', '.join(unconditional_skills)}). Bump minItems."
                )

            # Description should mention each skill (warning only — descriptions may
            # paraphrase or roll up cross-cutting skills).
            if description:
                missing_in_desc = [
                    s for s in unique_stage_skills if s not in description
                ]
                if missing_in_desc:
                    warnings.append(
                        f"{stage_name}: contract skill_compliance.description does not "
                        f"mention: {', '.join(missing_in_desc)}"
                    )

        # ---- Rule file cross-check ----
        rule_path = _rule_file_path(repo_root, stage_name)
        if rule_path is not None:
            rule_text = rule_path.read_text(encoding="utf-8")
            rule_block = _extract_block(rule_text, RULE_SKILL_BLOCK_HEADER_RE)
            if rule_block is None:
                warnings.append(
                    f"{stage_name}: rule file {rule_path.name} has no "
                    f"'## Agent Skills' block — stage agent declares skills "
                    f"that the rule file does not list"
                )
            else:
                rule_skills = _extract_skills(rule_block)
                unique_rule_skills = [name for name, _ in rule_skills]
                # Skills declared in stage agent but missing in rule file are drift.
                # (using-agent-skills is meta and may be omitted from rule files.)
                # UNCONDITIONAL skills missing → error.
                # CONDITIONAL skills missing → warning (they're context-gated).
                meta = {"using-agent-skills"}
                missing_unconditional = [
                    name for name, cond in stage_skills
                    if not cond and name not in meta and name not in unique_rule_skills
                ]
                missing_conditional = [
                    name for name, cond in stage_skills
                    if cond and name not in meta and name not in unique_rule_skills
                ]
                if missing_unconditional:
                    errors.append(
                        f"{stage_name}: unconditional skills declared in stage agent "
                        f"but absent from rule file {rule_path.relative_to(repo_root)}: "
                        f"{', '.join(missing_unconditional)}"
                    )
                if missing_conditional:
                    warnings.append(
                        f"{stage_name}: conditional skills not mentioned in rule file "
                        f"{rule_path.relative_to(repo_root)}: "
                        f"{', '.join(missing_conditional)} (this is OK for context-gated skills)"
                    )

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_lint_rules.py",
        description="Cross-link CI for stage agents ↔ contracts ↔ rule files.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repo root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress success output (warnings still print)",
    )
    args = parser.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    if not (repo_root / ".aidlc-orchestrator").is_dir():
        _die(f"not an AIDLC repo (missing .aidlc-orchestrator): {repo_root}")

    errors, warnings = lint(repo_root)

    if warnings:
        print("Warnings:", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠  {w}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} drift error(s) detected:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"factory_lint_rules: clean ({len(warnings)} warning(s))")


if __name__ == "__main__":
    main()
