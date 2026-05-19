#!/usr/bin/env python3
"""skill_utils.py — Shared utilities for AIDLC skill management scripts.

Used by: factory_skill_sync.py, factory_skill_drift.py, factory_autoskills.py
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


# ── Skill tier search order (highest priority first) ─────────────────────────

def skill_tiers(repo_root: Path) -> list[Path]:
    return [
        repo_root / ".agents" / "custom-skills",
        repo_root / ".agents" / "skills",
        Path.home() / ".agents" / "skills",
    ]


# ── SHA-256 ───────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Frontmatter parser ────────────────────────────────────────────────────────

def parse_frontmatter(skill_md: Path) -> dict:
    """Extract YAML frontmatter from a SKILL.md file (minimal parser)."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    fm_text = text[3:end].strip()
    result: dict = {}
    current_key: str | None = None
    nested: dict | None = None

    for line in fm_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not stripped or stripped.startswith("#"):
            continue

        if indent == 0:
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip("\"'")
                if val:
                    result[key] = val
                    current_key = None
                    nested = None
                else:
                    current_key = key
                    nested = {}
                    result[key] = nested
        elif indent >= 2 and nested is not None:
            key, _, val = stripped.partition(":")
            nested[key.strip()] = val.strip().strip("\"'")

    return result


# ── Semver range checker ──────────────────────────────────────────────────────

_VER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse_ver(v: str) -> tuple[int, int, int] | None:
    m = _VER_RE.search(v)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def ver_in_range(version: str, semver_range: str) -> bool:
    """Rudimentary semver range check covering >=X.Y.Z <A.B.C patterns."""
    ver = _parse_ver(version)
    if ver is None:
        return False

    for clause in semver_range.strip().split():
        m = re.match(r"([><=!^~]+)([\d.]+)", clause)
        if not m:
            continue
        op, bound_str = m.group(1), m.group(2)
        bound = _parse_ver(bound_str)
        if bound is None:
            continue
        if op == ">=" and ver < bound:
            return False
        elif op == ">" and ver <= bound:
            return False
        elif op == "<" and ver >= bound:
            return False
        elif op == "<=" and ver > bound:
            return False
        elif op in ("==", "=") and ver != bound:
            return False
        elif op == "^":
            if ver[0] != bound[0] or ver < bound:
                return False
        elif op == "~":
            if ver[:2] != bound[:2] or ver < bound:
                return False
    return True


# ── Skill dataclass ───────────────────────────────────────────────────────────

@dataclass
class SkillInfo:
    name: str
    path: Path
    framework: str = ""
    version_range: str = ""
    has_applies_to: bool = False


# ── Skill discovery ───────────────────────────────────────────────────────────

def discover_skills(repo_root: Path, only: str | None = None) -> list[SkillInfo]:
    """Walk all skill tiers and return a deduplicated list.

    Priority: custom-skills > skills > ~/.agents/skills.
    First tier that provides a given skill name wins.
    """
    seen: set[str] = set()
    result: list[SkillInfo] = []

    for base in skill_tiers(repo_root):
        if not base.exists():
            continue
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            name = skill_dir.name
            if only and name != only:
                continue
            if name in seen:
                continue

            fm = parse_frontmatter(skill_md)
            applies_to = fm.get("applies_to", {})
            if not isinstance(applies_to, dict):
                applies_to = {}

            result.append(SkillInfo(
                name=fm.get("name", name),
                path=skill_md,
                framework=applies_to.get("framework", ""),
                version_range=applies_to.get("version", ""),
                has_applies_to=bool(applies_to),
            ))
            seen.add(name)

    return result


# ── Workspace discovery ───────────────────────────────────────────────────────

_MANIFEST_FILES = frozenset({
    "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
    "requirements.txt", "Gemfile", "composer.json",
})

_EXCLUDE_DIRS = frozenset({
    "node_modules", ".git", "dist", "build", ".venv", "venv", "target",
    "__pycache__", ".next", ".nuxt", "vendor", ".cache",
    ".turbo", ".nx", "coverage", ".tox", ".aidlc-orchestrator",
    "aidlc-docs", ".agents", ".claude",
})


def find_workspace_dirs(repo_root: Path, max_depth: int = 4) -> list[Path]:
    """Find all directories containing a manifest file up to max_depth.

    Returns repo_root first (always included), then sorted sub-dirs.
    Excludes common noise directories.
    """
    found: set[Path] = set()

    def _scan(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        for manifest in _MANIFEST_FILES:
            if (directory / manifest).exists():
                found.add(directory)
                break
        try:
            for child in sorted(directory.iterdir()):
                if child.is_dir() and child.name not in _EXCLUDE_DIRS:
                    _scan(child, depth + 1)
        except PermissionError:
            pass

    _scan(repo_root, 0)

    result = [repo_root]
    result += sorted(p for p in found if p != repo_root)
    return result
