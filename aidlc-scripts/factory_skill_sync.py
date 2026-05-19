#!/usr/bin/env python3
"""factory_skill_sync.py — Sync skills from autoskills across all workspace dirs.

Two subcommands:

  sync   Run `npx autoskills --yes` in every workspace directory, then
         consolidate all installed skills to <repo-root>/.agents/skills/.
         Deduplicates by skill name (first seen wins). Idempotent — skips
         files whose SHA-256 already matches.

  select List all skills currently installed across all tiers and output
         their paths for use in stage input handoffs (skill_paths_resolved[]).

Usage:
    python3 aidlc-scripts/factory_skill_sync.py sync [--repo-root PATH] [--dry-run]
    python3 aidlc-scripts/factory_skill_sync.py select [--repo-root PATH] [--output json|text]

Exit codes:
    0  success (or graceful degradation — Node.js missing, network error)
    1  hard error (file-system write failure)
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
REPO_ROOT_DEFAULT = _SCRIPT_DIR.parent

sys.path.insert(0, str(_SCRIPT_DIR))
from skill_utils import discover_skills, find_workspace_dirs, sha256_file


# ── Node.js prerequisite check ────────────────────────────────────────────────

def _check_node() -> bool:
    """Return True if Node.js >= 22.6.0 is available, False otherwise (non-fatal)."""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        raw = result.stdout.strip().lstrip("v")
        major = int(raw.split(".")[0]) if raw else 0
        if major < 22:
            print(
                f"WARNING: autoskills requires Node.js >= 22.6.0 "
                f"(found {result.stdout.strip()}). Skill sync skipped.",
                file=sys.stderr,
            )
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        print("WARNING: Node.js not found. Skill sync skipped.", file=sys.stderr)
        return False


# ── autoskills runner ─────────────────────────────────────────────────────────

def _run_autoskills(workspace_dir: Path, dry_run: bool = False) -> list[Path]:
    """Run `npx --yes autoskills --yes` in workspace_dir.

    Returns the list of skill directories created/updated by autoskills.
    """
    label = str(workspace_dir.name) or "."
    print(f"  → {label}/ ", end="", flush=True)

    if dry_run:
        print("[dry-run]")
        return []

    try:
        result = subprocess.run(
            ["npx", "--yes", "autoskills", "--yes"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        print(f"    WARNING: autoskills timed out in {workspace_dir}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("SKIP (npx not found)")
        return []

    if result.returncode != 0:
        print(f"WARN (exit {result.returncode})")
        for line in result.stderr.strip().splitlines()[:5]:
            print(f"    {line}", file=sys.stderr)
        return []

    print("done")

    # Surface security warnings from autoskills stdout/stderr
    for line in (result.stdout + result.stderr).splitlines():
        lower = line.lower()
        if any(kw in lower for kw in ("flagged", "⚠", "no skill", "warning:")):
            print(f"    ⚠  {line.strip()}")

    # Collect installed skill directories
    installed: list[Path] = []
    skills_dir = workspace_dir / ".agents" / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                installed.append(skill_dir)

    return installed


# ── consolidation helpers ─────────────────────────────────────────────────────

def _copy_skill(src: Path, dest: Path) -> None:
    """Copy all files from src skill dir to dest, preserving sub-structure.

    Follows symlinks so that symlinked skill dirs created by autoskills CLI
    are read through to their real content.
    """
    real_src = src.resolve() if src.is_symlink() else src
    dest.mkdir(parents=True, exist_ok=True)
    for file in real_src.rglob("*"):
        if file.is_file():
            rel = file.relative_to(real_src)
            dest_file = dest / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest_file)


def _remove(path: Path) -> None:
    """Remove a path whether it is a directory, a symlink, or a symlink-to-dir.

    shutil.rmtree() raises NotADirectoryError on symlinks in Python 3.12+,
    which is silently swallowed by ignore_errors=True — leaving the symlink
    in place. This helper handles both cases explicitly.
    """
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _skill_is_current(src: Path, dest: Path) -> bool:
    """True if dest/SKILL.md already has the same SHA-256 as src/SKILL.md."""
    src_md = src / "SKILL.md"
    dest_md = dest / "SKILL.md"
    return (
        src_md.exists()
        and dest_md.exists()
        and sha256_file(src_md) == sha256_file(dest_md)
    )


def _consolidate(
    all_found: dict[str, Path],
    root_skills_dir: Path,
    repo_root: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Move/copy skills into root .agents/skills/. Returns (installed, skipped)."""
    installed = skipped = 0

    for name, src in all_found.items():
        dest = root_skills_dir / name

        if src.resolve() == dest.resolve():
            # autoskills ran in root workspace — already in the right place
            skipped += 1
            continue

        if _skill_is_current(src, dest):
            print(f"    · {name} [skipped — up-to-date]")
            skipped += 1
            if not dry_run:
                _remove(src)
            continue

        if dry_run:
            print(f"    ○ {name} [would install → .agents/skills/{name}/]")
            installed += 1
            continue

        _copy_skill(src, dest)
        _remove(src)
        print(f"    ✓ {name}")
        installed += 1

    return installed, skipped


def _cleanup_workspace_agents(
    workspace_dirs: list[Path], repo_root: Path, dry_run: bool
) -> None:
    """Remove empty workspace-level .agents/ dirs created by autoskills."""
    for workspace_dir in workspace_dirs:
        if workspace_dir.resolve() == repo_root.resolve():
            continue

        lock = workspace_dir / "skills-lock.json"
        if lock.exists() and not dry_run:
            lock.unlink(missing_ok=True)

        ws_agents = workspace_dir / ".agents"
        if not ws_agents.exists():
            continue

        ws_skills = ws_agents / "skills"
        if ws_skills.is_symlink():
            if not dry_run:
                ws_skills.unlink()
        elif ws_skills.exists() and not any(ws_skills.iterdir()):
            if not dry_run:
                ws_skills.rmdir()

        if ws_agents.is_symlink():
            if not dry_run:
                ws_agents.unlink()
        elif ws_agents.exists() and not any(ws_agents.iterdir()):
            if not dry_run:
                ws_agents.rmdir()


# ── sync subcommand ───────────────────────────────────────────────────────────

def cmd_sync(repo_root: Path, dry_run: bool = False) -> int:
    if not _check_node():
        return 0  # graceful degradation — universal skills still apply

    workspace_dirs = find_workspace_dirs(repo_root)
    labels = ", ".join(
        "." if d == repo_root else str(d.relative_to(repo_root))
        for d in workspace_dirs
    )
    print(f"[Sync] {len(workspace_dirs)} workspace(s): {labels}")

    # Run autoskills in each workspace; first-seen-per-name wins
    all_found: dict[str, Path] = {}
    for workspace_dir in workspace_dirs:
        for skill_dir in _run_autoskills(workspace_dir, dry_run=dry_run):
            name = skill_dir.name
            if name not in all_found:
                all_found[name] = skill_dir

    if not all_found:
        print("[Sync] autoskills installed no skills (no matching technologies detected)")
        return 0

    root_skills_dir = repo_root / ".agents" / "skills"
    if not dry_run:
        root_skills_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Sync] consolidating {len(all_found)} skill(s) → .agents/skills/")
    installed, skipped = _consolidate(all_found, root_skills_dir, repo_root, dry_run)
    _cleanup_workspace_agents(workspace_dirs, repo_root, dry_run)

    suffix = " (dry-run)" if dry_run else ""
    print(
        f"[Sync] done{suffix} — "
        f"{installed} installed/updated, {skipped} skipped (up-to-date)"
    )
    return 0


# ── select subcommand ─────────────────────────────────────────────────────────

def cmd_select(repo_root: Path, output_format: str = "json") -> int:
    """Resolve skill_paths_resolved[] for stage input handoffs.

    autoskills already performed tech-aware filtering during installation, so
    ALL skills in .agents/skills/ are relevant. Custom-skills (process skills)
    come first to match the skill-protocol load order.
    """
    skills = discover_skills(repo_root)

    custom_paths: list[str] = []
    framework_paths: list[str] = []

    for skill in skills:
        try:
            path_str = str(skill.path.relative_to(repo_root))
        except ValueError:
            path_str = str(skill.path)

        tier = skill.path.parent.parent.name  # "custom-skills" or "skills"
        if tier == "custom-skills":
            custom_paths.append(path_str)
        else:
            framework_paths.append(path_str)

    skill_paths_resolved = custom_paths + framework_paths

    result = {
        "skill_paths_resolved": skill_paths_resolved,
        "skill_count": len(skill_paths_resolved),
        "warnings": [],
    }

    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        for path in skill_paths_resolved:
            print(path)

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-root", type=Path, default=None,
        help="Repository root (default: parent of aidlc-scripts/)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Install skills via autoskills across all workspaces")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="Preview actions without writing files")

    p_select = sub.add_parser("select", help="Output skill_paths_resolved[] for stage handoffs")
    p_select.add_argument("--output", choices=["json", "text"], default="json",
                          help="Output format (default: json)")

    args = parser.parse_args()
    repo_root = args.repo_root or REPO_ROOT_DEFAULT

    if args.command == "sync":
        sys.exit(cmd_sync(repo_root, dry_run=getattr(args, "dry_run", False)))
    elif args.command == "select":
        sys.exit(cmd_select(repo_root, output_format=getattr(args, "output", "json")))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
