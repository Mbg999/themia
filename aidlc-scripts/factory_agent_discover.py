#!/usr/bin/env python3
"""factory_agent_discover.py — List available subagents for the orchestrator.

Scans agent directories and returns metadata about each agent:
name, description, model, and whether it's a built-in or custom agent.

Usage
-----
    factory_agent_discover.py [--custom-only] [--json]
    factory_agent_discover.py show <agent-name> [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parent.parent))

# Agent search paths in priority order
AGENT_PATHS = [
    REPO_ROOT / ".opencode" / "agents",
    REPO_ROOT / ".claude" / "agents",
]


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter fields from a markdown file."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    try:
        import yaml as _yaml
        parsed = _yaml.safe_load(m.group(1))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def discover(custom_only: bool = False) -> list[dict]:
    """Scan agent directories and return agent metadata."""
    agents: list[dict] = []
    seen_names: set[str] = set()

    for agents_dir in AGENT_PATHS:
        if not agents_dir.exists():
            continue
        for f in sorted(agents_dir.rglob("*.md")):
            name = f.stem
            if name in seen_names:
                continue

            # Determine if custom (not in stage/ or cross-cutting/ or root orchestrator)
            rel = f.relative_to(agents_dir)
            parts = rel.parts
            is_custom = len(parts) > 1 and parts[0] not in ("stage", "cross-cutting")

            if custom_only and not is_custom:
                continue

            meta = _parse_frontmatter(f.read_text())
            agents.append({
                "name": name,
                "description": meta.get("description", "(no description)"),
                "model": meta.get("model", "default"),
                "mode": meta.get("mode", "subagent"),
                "path": str(f.relative_to(REPO_ROOT)),
                "custom": is_custom,
            })
            seen_names.add(name)

    return agents


def cmd_list(args: argparse.Namespace) -> None:
    agents = discover(args.custom_only)
    if not agents:
        print("no agents found")
        sys.exit(0)

    if args.json:
        print(json.dumps(agents, indent=2))
        return

    # Table output
    custom_tag = " [CUSTOM]" if not args.custom_only else ""
    print(f"{'Name':25s} {'Mode':12s} {'Model':12s} Description")
    print("-" * 80)
    for a in agents:
        tag = " [CUSTOM]" if a["custom"] else ""
        print(f"{a['name']:25s} {a['mode']:12s} {a['model']:12s} {a['description'][:50]}{tag}")
    print(f"\n{len(agents)} agent(s) found")


def cmd_show(args: argparse.Namespace) -> None:
    agents = discover()
    matches = [a for a in agents if a["name"] == args.agent_name]
    if not matches:
        print(f"agent '{args.agent_name}' not found", file=sys.stderr)
        sys.exit(1)

    a = matches[0]
    if args.json:
        print(json.dumps(a, indent=2))
        return

    print(f"Name:        {a['name']}")
    print(f"Description: {a['description']}")
    print(f"Model:       {a['model']}")
    print(f"Mode:        {a['mode']}")
    print(f"Path:        {a['path']}")
    print(f"Custom:      {'yes' if a['custom'] else 'no'}")


def main() -> None:
    p = argparse.ArgumentParser(description="AIDLC — Agent Discovery")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list available agents")
    p_list.add_argument("--custom-only", action="store_true",
                        help="show only custom (user-defined) agents")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show agent details")
    p_show.add_argument("agent_name")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
