#!/usr/bin/env python3
"""factory_stage_registry.py — Stage auto-discovery for AIDLC.

Scans `.claude/agents/stage/*.md` and emits a registry of every stage agent
present in the workspace. Each stage agent's YAML frontmatter MAY include an
`aidlc_stage:` block:

    ---
    name: requirements-analyst
    description: ...
    model: sonnet
    aidlc_stage:
      phase: 0
      commands: [factory-spec]
      input_contract: requirements-analyst.input.v1.json
      output_contract: requirements-analyst.output.v1.json
      execution_mode: post-execution    # or full-spawn
      requires_skills:
        - using-agent-skills
        - idea-refine
        - spec-driven-development
        - requirements-intelligence
    ---

Stages without an `aidlc_stage:` block still appear in the registry — fields
are auto-inferred from the filename and the contract folder. Adding the
explicit block is the gradual upgrade path; the registry tolerates partial
adoption.

Usage:
    python3 aidlc-scripts/factory_stage_registry.py list
    python3 aidlc-scripts/factory_stage_registry.py show <stage-name>
    python3 aidlc-scripts/factory_stage_registry.py json   # full registry as JSON

Exit codes:
    0  success
    2  usage / no stage agents found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<body>.*?)\n---\s*\n",
    re.DOTALL,
)

# Default phase mapping (used when aidlc_stage.phase is not declared).
DEFAULT_PHASE_BY_STAGE = {
    "workspace-scout": 0,
    "reverse-engineer": 0,
    "requirements-analyst": 0,
    "story-writer": 1,
    "workflow-planner": 1,
    "unit-decomposer": 1,
    "code-generator": 1,
    "build-test-agent": 1,
    "reviewer-code": 1,
    "reviewer-security": 1,
    "reviewer-performance": 1,
    "reviewer-simplifier": 1,
    "ship-agent": 1,
}

# Default command routing (used when aidlc_stage.commands is not declared).
DEFAULT_COMMANDS_BY_STAGE = {
    "workspace-scout": ["factory-spec"],
    "reverse-engineer": ["factory-spec"],
    "requirements-analyst": ["factory-spec"],
    "story-writer": ["factory-plan"],
    "workflow-planner": ["factory-plan"],
    "unit-decomposer": ["factory-plan"],
    "code-generator": ["factory-build"],
    "build-test-agent": ["factory-build"],
    "reviewer-code": ["factory-review"],
    "reviewer-security": ["factory-review"],
    "reviewer-performance": ["factory-review"],
    "reviewer-simplifier": ["factory-review"],
    "ship-agent": ["factory-ship"],
}


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_stage_registry: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        import yaml
    except ImportError:
        _die(f"pyyaml is required: {sys.executable} -m pip install pyyaml")
    try:
        return yaml.safe_load(m.group("body")) or {}
    except Exception:
        return {}


def _infer_record(stage_path: Path, repo_root: Path) -> dict:
    """Build a registry record for one stage agent."""
    fm = _parse_frontmatter(stage_path.read_text(encoding="utf-8"))
    name = fm.get("name") or stage_path.stem

    aidlc = fm.get("aidlc_stage") or {}

    # Phase
    phase = aidlc.get("phase")
    if phase is None:
        phase = DEFAULT_PHASE_BY_STAGE.get(name, None)

    # Commands
    commands = aidlc.get("commands")
    if not commands:
        commands = DEFAULT_COMMANDS_BY_STAGE.get(name, [])

    # Contract paths (verify they exist)
    contracts_dir = repo_root / ".aidlc-orchestrator" / "contracts"
    input_contract = aidlc.get("input_contract") or f"{name}.input.v1.json"
    output_contract = aidlc.get("output_contract") or f"{name}.output.v1.json"

    # Reviewer agents share a contract — special-case
    if name.startswith("reviewer-"):
        if not (contracts_dir / output_contract).exists():
            output_contract = "reviewer.output.v1.json"
        if not (contracts_dir / input_contract).exists():
            input_contract = "reviewer.input.v1.json"

    has_input = (contracts_dir / input_contract).exists()
    has_output = (contracts_dir / output_contract).exists()

    # Execution mode
    execution_mode = aidlc.get("execution_mode")
    if execution_mode is None:
        # Default: code-generator + reviewer-* use full-spawn (parallel); others post-execution
        execution_mode = (
            "full-spawn"
            if (name == "code-generator" or name.startswith("reviewer-"))
            else "post-execution"
        )

    # Skills
    skills = aidlc.get("requires_skills") or []

    return {
        "name": name,
        "stage_file": str(stage_path.relative_to(repo_root)),
        "phase": phase,
        "commands": commands,
        "execution_mode": execution_mode,
        "input_contract": input_contract,
        "output_contract": output_contract,
        "input_contract_present": has_input,
        "output_contract_present": has_output,
        "requires_skills": skills,
        "model": fm.get("model"),
        "description": fm.get("description"),
        "has_explicit_aidlc_stage_block": bool(aidlc),
    }


def discover(repo_root: Path) -> list[dict]:
    stage_dir = repo_root / ".claude" / "agents" / "stage"
    if not stage_dir.is_dir():
        return []
    return [_infer_record(p, repo_root) for p in sorted(stage_dir.glob("*.md"))]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_stage_registry.py",
        description="Stage auto-discovery for AIDLC.",
    )
    parser.add_argument("--repo-root", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="One stage per line with key metadata")
    pshow = sub.add_parser("show", help="Full record for one stage")
    pshow.add_argument("name")
    sub.add_parser("json", help="Emit full registry as JSON")

    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parent.parent

    if not (repo_root / ".aidlc-orchestrator").is_dir():
        _die(f"not an AIDLC repo: {repo_root}")

    registry = discover(repo_root)
    if not registry:
        _die("no stage agents discovered")

    if args.cmd == "list":
        for r in registry:
            mark = "✓" if r["has_explicit_aidlc_stage_block"] else "·"
            ic = "✓" if r["input_contract_present"] else "✗"
            oc = "✓" if r["output_contract_present"] else "✗"
            phase = f"P{r['phase']}" if r["phase"] is not None else "?"
            print(
                f"{mark} {r['name']:25}  {phase}  "
                f"mode={r['execution_mode']:14}  "
                f"contracts: in={ic} out={oc}  "
                f"cmds={','.join(r['commands']) or '-'}"
            )
        print(f"\n{len(registry)} stage(s) discovered. "
              f"✓ = explicit aidlc_stage block, · = inferred defaults")
        return

    if args.cmd == "show":
        match = [r for r in registry if r["name"] == args.name]
        if not match:
            _die(f"stage not found: {args.name}")
        print(json.dumps(match[0], indent=2))
        return

    if args.cmd == "json":
        print(json.dumps(registry, indent=2))
        return


if __name__ == "__main__":
    main()
