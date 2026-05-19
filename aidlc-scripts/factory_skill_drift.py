#!/usr/bin/env python3
"""factory_skill_drift.py — Detect skills whose version range no longer covers the
current stable release of the framework they target.

Reads applies_to frontmatter from every skill under .agents/skills/ and
.agents/custom-skills/, queries the appropriate package registry (npm, PyPI,
crates.io), and flags skills that are STALE (latest stable outside declared range).

Usage:
    python3 aidlc-scripts/factory_skill_drift.py            # check all skills
    python3 aidlc-scripts/factory_skill_drift.py --skill nextjs-15
    python3 aidlc-scripts/factory_skill_drift.py --report   # write drift-report.md

Exit codes:
    0  no drift detected
    1  one or more skills are stale
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
REPORT_PATH = REPO_ROOT / "aidlc-docs" / "skill-drift-report.md"

sys.path.insert(0, str(Path(__file__).parent))
from skill_utils import (
    SkillInfo,
    discover_skills,
    parse_frontmatter,
    ver_in_range as _ver_in_range,
)


# ── registry queries ──────────────────────────────────────────────────────────

def _get_url(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                    "User-Agent": "factory_skill_drift/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def _latest_npm(package: str) -> str | None:
    # URL-encode scoped packages: @scope/name → @scope%2Fname
    encoded = package.replace("/", "%2F")
    data = _get_url(f"https://registry.npmjs.org/{encoded}/latest")
    if data:
        return data.get("version")
    return None


def _latest_pypi(package: str) -> str | None:
    data = _get_url(f"https://pypi.org/pypi/{package}/json")
    if data:
        return data.get("info", {}).get("version")
    return None


def _latest_crates(package: str) -> str | None:
    data = _get_url(f"https://crates.io/api/v1/crates/{package}")
    if data:
        return data.get("crate", {}).get("newest_version")
    return None


_REGISTRY_FUNCS = {
    "npm": _latest_npm,
    "pip": _latest_pypi,
    "cargo": _latest_crates,
}

# npm packages that map to their registry name (framework → npm package)
_NPM_FRAMEWORK_MAP: dict[str, str] = {
    # frontend / fullstack
    "next": "next",
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "nuxt": "nuxt",
    "bun": "bun",
    "astro": "astro",
    "remix": "@remix-run/react",
    "vite": "vite",
    "vitest": "vitest",
    "angular": "@angular/core",
    "@angular/core": "@angular/core",
    "tailwindcss": "tailwindcss",
    "typescript": "typescript",
    # Node.js backends
    "express": "express",
    "fastify": "fastify",
    "koa": "koa",
    "hono": "hono",
    "@nestjs/core": "@nestjs/core",
}

_PYPI_FRAMEWORK_MAP: dict[str, str] = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "langchain": "langchain",
}

_CARGO_FRAMEWORK_MAP: dict[str, str] = {
    "axum": "axum",
    "tokio": "tokio",
    "serde": "serde",
    "actix-web": "actix-web",
}


def resolve_latest(framework: str) -> tuple[str, str | None]:
    """Return (ecosystem, latest_version | None) for a framework name."""
    if framework in _NPM_FRAMEWORK_MAP:
        return "npm", _latest_npm(_NPM_FRAMEWORK_MAP[framework])
    if framework in _PYPI_FRAMEWORK_MAP:
        return "pip", _latest_pypi(_PYPI_FRAMEWORK_MAP[framework])
    if framework in _CARGO_FRAMEWORK_MAP:
        return "cargo", _latest_crates(_CARGO_FRAMEWORK_MAP[framework])
    # unknown framework — skip
    return "unknown", None


# ── skill discovery ───────────────────────────────────────────────────────────
# SkillInfo, discover_skills, and parse_frontmatter are imported from skill_utils.


# ── drift check ───────────────────────────────────────────────────────────────

@dataclass
class DriftResult:
    skill: SkillInfo
    ecosystem: str = ""
    latest: str | None = None
    status: str = "ok"   # ok | stale | unknown | no-applies_to | registry-error
    detail: str = ""


def check_drift(skill: SkillInfo) -> DriftResult:
    result = DriftResult(skill=skill)

    if not skill.has_applies_to or not skill.framework:
        result.status = "no-applies_to"
        result.detail = "universal skill (no applies_to) — skip"
        return result

    if skill.framework.startswith("_"):
        result.status = "no-applies_to"
        result.detail = "placeholder framework"
        return result

    ecosystem, latest = resolve_latest(skill.framework)
    result.ecosystem = ecosystem
    result.latest = latest

    if ecosystem == "unknown":
        result.status = "unknown"
        result.detail = f"framework '{skill.framework}' not in registry map — add to _*_FRAMEWORK_MAP"
        return result

    if latest is None:
        result.status = "registry-error"
        result.detail = f"could not fetch latest from {ecosystem} registry"
        return result

    if not skill.version_range:
        result.status = "unknown"
        result.detail = "applies_to.version not declared — cannot check range"
        return result

    covered = _ver_in_range(latest, skill.version_range)
    if covered:
        result.status = "ok"
        result.detail = f"latest {latest} is within range '{skill.version_range}'"
    else:
        result.status = "stale"
        result.detail = (
            f"latest {latest} is OUTSIDE range '{skill.version_range}' — "
            f"skill needs update or range bump"
        )

    return result


# ── report ────────────────────────────────────────────────────────────────────

def _write_report(results: list[DriftResult], path: Path) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    stale = [r for r in results if r.status == "stale"]
    ok    = [r for r in results if r.status == "ok"]
    skip  = [r for r in results if r.status in ("no-applies_to", "unknown", "registry-error")]

    lines = [
        f"# Skill Drift Report — {now}\n",
        f"Checked {len(results)} skills: "
        f"**{len(ok)} OK**, **{len(stale)} stale**, {len(skip)} skipped.\n",
    ]

    if stale:
        lines += ["\n## Stale skills (action required)\n",
                  "| Skill | Framework | Range | Latest | Action |\n",
                  "|---|---|---|---|---|\n"]
        for r in stale:
            action = f"Bump range or run `factory_autoskills.py --skill {r.skill.name}`"
            lines.append(
                f"| {r.skill.name} | {r.skill.framework} ({r.ecosystem}) "
                f"| `{r.skill.version_range}` | {r.latest} | {action} |\n"
            )

    if ok:
        lines += ["\n## Up-to-date skills\n",
                  "| Skill | Framework | Range | Latest |\n",
                  "|---|---|---|---|\n"]
        for r in ok:
            lines.append(
                f"| {r.skill.name} | {r.skill.framework} | "
                f"`{r.skill.version_range}` | {r.latest} |\n"
            )

    if skip:
        lines += ["\n## Skipped (no applies_to or unknown registry)\n",
                  "| Skill | Reason |\n", "|---|---|\n"]
        for r in skip:
            lines.append(f"| {r.skill.name} | {r.detail} |\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    print(f"Report written → {path.relative_to(REPO_ROOT)}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", metavar="NAME", help="Check only this skill")
    parser.add_argument("--report", action="store_true",
                        help="Write drift-report.md to aidlc-docs/")
    args = parser.parse_args()

    skills = discover_skills(REPO_ROOT, args.skill)
    if not skills:
        print("No skills found." if args.skill is None
              else f"Skill '{args.skill}' not found.")
        sys.exit(2)

    print(f"Checking {len(skills)} skill(s) for drift…\n")
    results = []
    for skill in skills:
        sys.stdout.write(f"  {skill.name} ({skill.framework or 'universal'}) … ")
        sys.stdout.flush()
        r = check_drift(skill)
        results.append(r)
        icons = {"ok": "✓", "stale": "⚠ STALE", "unknown": "?",
                 "no-applies_to": "·", "registry-error": "✗"}
        print(icons.get(r.status, r.status))
        if r.detail and r.status not in ("ok", "no-applies_to"):
            print(f"    {r.detail}")

    stale = [r for r in results if r.status == "stale"]
    print(f"\n{len(results) - len(stale)} OK, {len(stale)} stale.")

    if args.report:
        _write_report(results, REPORT_PATH)

    if stale:
        print("\nStale skills:", ", ".join(r.skill.name for r in stale), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
