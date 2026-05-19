#!/usr/bin/env python3
"""factory_conflict.py — Conflict Resolver for AIDLC Orchestrator (Phase 5 + 5.5).

Detects and arbitrates conflicts between parallel stage agents:
    - File-glob lock registry (path-based collision detection)
    - Python AST symbol diff (interface drift detection)
    - TS/JS AST symbol diff via tree-sitter (Phase 5.5)
      Extracts top-level `export function/class/interface/type/enum` and
      `export const x = (...) => ...` signatures from .ts/.tsx/.js/.jsx files.

Subcommands
-----------
    acquire <run-id> <holder> [--mode write|read] <glob>...
        Try to acquire write or read locks on the given globs.
        Exit codes:
            0  all granted
            1  conflict; conflict record written under runs/<run>/conflicts/

    release <run-id> <holder>
        Release ALL locks held by <holder>. Idempotent.

    list <run-id> [--json]
        Print active locks (sorted by holder).

    snapshot <run-id> <holder> <file>...
        Pre-spawn: capture baseline AST symbol map for each .py file.
        Used as the diff baseline by `check-symbols` post-spawn.

    check-symbols <run-id> <holder> <file>...
        Post-spawn: parse each .py file, diff exported symbols against the
        baseline written by `snapshot`. If drift is detected AND there are
        other active holders, write an `interface_drift` conflict record
        and exit 1. If drift but no other holders, exit 0 with a notice.

    conflicts <run-id> [--json]
        List open conflict records for the run.

Storage
-------
    .aidlc-orchestrator/runs/<run-id>/locks/<holder>.yaml
    .aidlc-orchestrator/runs/<run-id>/symbol-baseline/<holder>.yaml
    .aidlc-orchestrator/runs/<run-id>/conflicts/<id>.yaml

Phase 5 limitations
-------------------
- Auto-merge resolution is NOT implemented. Conflicts always escalate
  (human resolution). The plan §6.2 documents auto-merge as a future feature.
- Glob overlap is heuristic: position-by-position component match with **
  wildcards. False positives (over-detecting overlap) are safe; false
  negatives would be unsafe (missed conflict). The heuristic biases toward
  false positives.
- AST diff covers Python (stdlib `ast`) and TS/JS (tree-sitter, optional).
- Deep TS type-system drift (generics narrowing, conditional types) is out
  of scope; that needs `tsc --noEmit` or LSP integration (Phase 7+).
- TS/JS extraction is signature-level only: param/return text, interface
  member text, type alias RHS text. Whitespace-normalized to avoid spurious
  drift on reformat.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print(f"missing dependency: {sys.executable} -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)

try:
    import tree_sitter as _ts  # type: ignore
    import tree_sitter_typescript as _tsts  # type: ignore
    import tree_sitter_javascript as _tsjs  # type: ignore
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False
    _ts = None  # type: ignore
    _tsts = None  # type: ignore
    _tsjs = None  # type: ignore


REPO_ROOT = Path(os.environ.get("AIDLC_ROOT", Path(__file__).resolve().parents[1]))
RUNS_ROOT = REPO_ROOT / ".aidlc-orchestrator" / "runs"

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_HOLDER_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")


def validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.match(run_id):
        _die(f"invalid run_id: {run_id!r}")


def validate_holder(holder: str) -> None:
    if not _HOLDER_RE.match(holder):
        _die(f"invalid holder: {holder!r}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def run_dir(run_id: str) -> Path:
    validate_run_id(run_id)
    p = RUNS_ROOT / run_id
    if not p.exists():
        _die(f"run not found: {p}")
    return p


def patterns_overlap(a: str, b: str) -> bool:
    """Return True if globs `a` and `b` could match any common file.

    Heuristic component-wise match, with `**` matching any depth. Biased
    toward false positives — over-detecting overlap is safe; under-detecting
    would let conflicts through.
    """
    parts_a = a.split("/")
    parts_b = b.split("/")
    n = min(len(parts_a), len(parts_b))
    for i in range(n):
        x, y = parts_a[i], parts_b[i]
        if x == "**" or y == "**":
            return True
        if not (fnmatch.fnmatchcase(x, y) or fnmatch.fnmatchcase(y, x)):
            return False
    if len(parts_a) > n and parts_a[n] == "**":
        return True
    if len(parts_b) > n and parts_b[n] == "**":
        return True
    return len(parts_a) == len(parts_b)


def _list_locks(rd: Path) -> list[dict]:
    locks_dir = rd / "locks"
    if not locks_dir.exists():
        return []
    locks = []
    for f in sorted(locks_dir.glob("*.yaml")):
        locks.append(yaml.safe_load(f.read_text()))
    return locks


def _is_stale(lock: dict, older_than_min: float | None = None) -> bool:
    """Check if a lock has exceeded its TTL (stale).

    If no ttl_minutes set, lock never expires.
    If older_than_min provided, check if acquired_at is older than that.
    """
    ttl = lock.get("ttl_minutes")
    if ttl is None:
        return False
    acquired = lock.get("acquired_at")
    if not acquired:
        return False
    try:
        acquired_dt = datetime.fromisoformat(acquired)
    except (ValueError, TypeError):
        return False
    elapsed = (datetime.now(timezone.utc) - acquired_dt).total_seconds() / 60.0
    if older_than_min is not None:
        return elapsed > older_than_min
    return elapsed > ttl


def cmd_acquire(args: argparse.Namespace) -> None:
    validate_holder(args.holder)
    rd = run_dir(args.run_id)
    locks_dir = rd / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    # Serialize acquire with a per-run lock file to prevent TOCTOU races
    _acquire_lock = rd / ".acquire.lock"
    try:
        import fcntl
        with _acquire_lock.open("a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            _do_acquire(args, rd, locks_dir)
    except (ImportError, OSError):
        # Fall back to non-locked path on platforms without fcntl (Windows)
        _do_acquire(args, rd, locks_dir)


def _do_acquire(args: argparse.Namespace, rd: Path, locks_dir: Path) -> None:
    existing = _list_locks(rd)
    conflicts: list[dict] = []
    for lock in existing:
        if lock["holder"] == args.holder:
            continue
        # Skip stale locks — treat as auto-released
        if _is_stale(lock):
            continue
        for new_glob in args.globs:
            for existing_glob in lock["globs"]:
                if not patterns_overlap(new_glob, existing_glob):
                    continue
                if args.mode == "read" and lock.get("mode") == "read":
                    continue
                conflicts.append({
                    "with_holder": lock["holder"],
                    "new_glob": new_glob,
                    "existing_glob": existing_glob,
                    "existing_mode": lock.get("mode", "write"),
                })

    if conflicts:
        conflicts_dir = rd / "conflicts"
        conflicts_dir.mkdir(parents=True, exist_ok=True)
        ts = now_iso().replace(":", "").replace("-", "")
        cid = f"path-{args.holder}-{ts}"
        record = {
            "id": cid,
            "detected_at": now_iso(),
            "kind": "path_collision",
            "requesting_holder": args.holder,
            "requested_mode": args.mode,
            "requested_globs": list(args.globs),
            "conflicts": conflicts,
            "resolution": None,
            "resolved_by": None,
        }
        (conflicts_dir / f"{cid}.yaml").write_text(
            yaml.safe_dump(record, sort_keys=False)
        )
        print(json.dumps({
            "granted": False,
            "conflicts": conflicts,
            "conflict_id": cid,
        }))
        for c in conflicts:
            print(
                f"CONFLICT: {args.holder} wants {c['new_glob']} but "
                f"{c['with_holder']} holds {c['existing_glob']} "
                f"({c['existing_mode']})",
                file=sys.stderr,
            )
        sys.exit(1)

    lock_file = locks_dir / f"{args.holder}.yaml"
    # Merge globs if holder already holds locks (Bug 10 fix)
    merged_globs = list(args.globs)
    if lock_file.exists():
        existing = yaml.safe_load(lock_file.read_text()) or {}
        existing_globs = existing.get("globs", [])
        existing_mode = existing.get("mode", "write")
        if existing_mode != args.mode:
            _die(f"{args.holder} already holds lock in mode {existing_mode}, "
                 f"cannot acquire {args.mode} — release first")
        merged_globs = list(dict.fromkeys(existing_globs + merged_globs))
    lock_data = {
        "holder": args.holder,
        "acquired_at": now_iso(),
        "globs": merged_globs,
        "mode": args.mode,
    }
    if args.ttl_minutes is not None:
        lock_data["ttl_minutes"] = args.ttl_minutes
    lock_file.write_text(yaml.safe_dump(lock_data, sort_keys=False))
    print(json.dumps({
        "granted": True,
        "holder": args.holder,
        "globs": list(args.globs),
    }))
    print(
        f"GRANTED: {args.holder} → {len(args.globs)} glob(s) ({args.mode})",
        file=sys.stderr,
    )


def cmd_release(args: argparse.Namespace) -> None:
    rd = run_dir(args.run_id)
    locks_dir = rd / "locks"
    if not locks_dir.exists():
        print("no locks directory (idempotent)")
        return
    if args.stale:
        cleaned = 0
        for f in sorted(locks_dir.glob("*.yaml")):
            lock = yaml.safe_load(f.read_text()) or {}
            if _is_stale(lock, older_than_min=args.older_than):
                f.unlink()
                cleaned += 1
        print(f"CLEANED {cleaned} stale lock(s) (older than {args.older_than}m)")
        return
    if not args.holder:
        _die("holder is required unless --stale is set")
    validate_holder(args.holder)
    lock_file = locks_dir / f"{args.holder}.yaml"
    if lock_file.exists():
        lock_file.unlink()
        print(f"RELEASED: {args.holder}")
    else:
        print(f"no locks held by {args.holder} (idempotent)")


def cmd_list(args: argparse.Namespace) -> None:
    rd = run_dir(args.run_id)
    locks = _list_locks(rd)
    if args.json:
        print(json.dumps(locks, indent=2))
        return
    if not locks:
        print("no active locks")
        return
    for lock in locks:
        ttl = lock.get("ttl_minutes")
        ttl_str = f" ttl={ttl}m" if ttl is not None else ""
        stale = " STALE" if _is_stale(lock) else ""
        print(
            f"{lock['holder']:30s} "
            f"{lock.get('mode','write'):6s} "
            f"{','.join(lock['globs'])}{ttl_str}{stale}"
        )


# ----------------------------------------------------------------------------
# TS/JS extractor (Phase 5.5) — tree-sitter based
# ----------------------------------------------------------------------------

# Lazy-init: parsing tree-sitter Languages allocates C objects; do it once.
_TS_LANG_CACHE: dict[str, object] | None = None

# File extension → tree-sitter language. Per Phase 5.5 plan note in
# ORCHESTRATOR-PLAN.md §687.
_TS_EXT_MAP = {
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",  # tree-sitter-javascript handles JSX
}


def _ts_languages() -> dict[str, object]:
    """Return {language_name: Language} once tree-sitter is loaded."""
    global _TS_LANG_CACHE
    if _TS_LANG_CACHE is not None:
        return _TS_LANG_CACHE
    if not _TS_AVAILABLE:
        _TS_LANG_CACHE = {}
        return _TS_LANG_CACHE
    _TS_LANG_CACHE = {
        "typescript": _ts.Language(_tsts.language_typescript()),
        "tsx": _ts.Language(_tsts.language_tsx()),
        "javascript": _ts.Language(_tsjs.language()),
    }
    return _TS_LANG_CACHE


def _normalize(s: str | None) -> str | None:
    """Collapse whitespace to single spaces — avoids spurious drift on reformat."""
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()


def _node_text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _strip_leading_colon(s: str) -> str:
    s = s.strip()
    if len(s) <= 1:
        return s
    return s[1:].strip() if s.startswith(":") else s


def _extract_function_sig(decl_node, src: bytes, *, is_default: bool, name_override: str | None = None) -> tuple[str | None, dict]:
    """Build a function signature dict from function_declaration or arrow_function."""
    name = name_override
    params: list[str] = []
    returns: str | None = None
    is_async = any(c.type == "async" for c in decl_node.children)
    for child in decl_node.named_children:
        if child.type == "identifier" and name is None:
            name = _node_text(child, src)
        elif child.type == "formal_parameters":
            for p in child.named_children:
                params.append(_normalize(_node_text(p, src)) or "")
        elif child.type == "type_annotation":
            returns = _normalize(_strip_leading_colon(_node_text(child, src)))
    return name, {
        "kind": "function",
        "params": params,
        "returns": returns,
        "async": is_async,
        "default": is_default,
    }


def _extract_class_sig(class_node, src: bytes) -> tuple[str | None, dict]:
    name: str | None = None
    methods: dict[str, dict] = {}
    for child in class_node.named_children:
        if child.type == "type_identifier":
            name = _node_text(child, src)
        elif child.type == "class_body":
            for m in child.named_children:
                if m.type != "method_definition":
                    continue
                m_name: str | None = None
                m_params: list[str] = []
                m_returns: str | None = None
                m_async = any(c.type == "async" for c in m.children)
                for sub in m.named_children:
                    if sub.type == "property_identifier":
                        m_name = _node_text(sub, src)
                    elif sub.type == "formal_parameters":
                        for p in sub.named_children:
                            m_params.append(_normalize(_node_text(p, src)) or "")
                    elif sub.type == "type_annotation":
                        m_returns = _normalize(_strip_leading_colon(_node_text(sub, src)))
                if m_name:
                    methods[m_name] = {"params": m_params, "returns": m_returns, "async": m_async}
    return name, {"kind": "class", "methods": methods}


def _extract_interface_sig(iface_node, src: bytes) -> tuple[str | None, dict]:
    name: str | None = None
    members: dict[str, str] = {}
    for child in iface_node.named_children:
        if child.type == "type_identifier":
            name = _node_text(child, src)
        elif child.type == "interface_body":
            for m in child.named_children:
                if m.type == "property_signature":
                    m_name = None
                    m_sig = ""
                    for sub in m.named_children:
                        if sub.type == "property_identifier":
                            m_name = _node_text(sub, src)
                        elif sub.type == "type_annotation":
                            m_sig = _normalize(_node_text(sub, src)) or ""
                    if m_name:
                        members[m_name] = m_sig
                elif m.type == "method_signature":
                    m_name = None
                    full = _normalize(_node_text(m, src)) or ""
                    for sub in m.named_children:
                        if sub.type == "property_identifier":
                            m_name = _node_text(sub, src)
                            break
                    if m_name:
                        sig = full[len(m_name):] if full.startswith(m_name) else full
                        members[m_name] = sig.strip()
    return name, {"kind": "interface", "members": members}


def _extract_type_alias_sig(ta_node, src: bytes) -> tuple[str | None, dict]:
    name: str | None = None
    type_params: list[str] = []
    value: str | None = None
    for child in ta_node.named_children:
        if child.type == "type_identifier" and name is None:
            name = _node_text(child, src)
        elif child.type == "type_parameters":
            for p in child.named_children:
                type_params.append(_normalize(_node_text(p, src)) or "")
        elif value is None:
            value = _normalize(_node_text(child, src))
    return name, {"kind": "type_alias", "type_params": type_params, "value": value}


def _extract_enum_sig(enum_node, src: bytes) -> tuple[str | None, dict]:
    name: str | None = None
    members: list[str] = []
    for child in enum_node.named_children:
        if child.type == "identifier":
            name = _node_text(child, src)
        elif child.type == "enum_body":
            for m in child.named_children:
                if m.type in ("property_identifier", "enum_assignment"):
                    members.append(_normalize(_node_text(m, src)) or "")
    return name, {"kind": "enum", "members": members}


def _handle_decl(node, src: bytes, symbols: dict, *, is_default: bool) -> None:
    t = node.type
    if t == "function_declaration":
        name, sig = _extract_function_sig(node, src, is_default=is_default)
        if not name and is_default:
            name = "<default>"
        if name:
            symbols[name] = sig
    elif t == "class_declaration":
        name, sig = _extract_class_sig(node, src)
        if not name and is_default:
            name = "<default>"
        if name:
            symbols[name] = sig
    elif t == "interface_declaration":
        name, sig = _extract_interface_sig(node, src)
        if name:
            symbols[name] = sig
    elif t == "type_alias_declaration":
        name, sig = _extract_type_alias_sig(node, src)
        if name:
            symbols[name] = sig
    elif t == "enum_declaration":
        name, sig = _extract_enum_sig(node, src)
        if name:
            symbols[name] = sig
    elif t == "lexical_declaration":
        # `export const x = (...) => ...` — track arrow-function exports only.
        # Plain const/let value exports rarely cause API drift surface area
        # worth the parsing complexity at this phase.
        for vd in node.named_children:
            if vd.type != "variable_declarator":
                continue
            vd_name = None
            arrow = None
            for sub in vd.named_children:
                if sub.type == "identifier" and vd_name is None:
                    vd_name = _node_text(sub, src)
                elif sub.type == "arrow_function":
                    arrow = sub
            if vd_name and arrow is not None:
                _, sig = _extract_function_sig(arrow, src, is_default=is_default, name_override=vd_name)
                sig["via"] = "arrow"
                symbols[vd_name] = sig


def extract_symbols_ts(src: bytes, language_name: str) -> dict:
    """Extract exported top-level symbols from TS/JS source.

    Covered: export function|class|interface|type|enum, and
    export const NAME = (...) => ... (arrow-function exports).
    Not covered: re-exports (`export * from`, `export { foo } from`),
    namespace exports, ambient declarations.
    """
    if not _TS_AVAILABLE:
        return {}
    langs = _ts_languages()
    lang = langs.get(language_name)
    if lang is None:
        return {}
    parser = _ts.Parser(lang)
    tree = parser.parse(src)
    symbols: dict[str, dict] = {}
    for top in tree.root_node.named_children:
        if top.type != "export_statement":
            continue
        is_default = any(c.type == "default" for c in top.children)
        for child in top.named_children:
            _handle_decl(child, src, symbols, is_default=is_default)
    return symbols


# ----------------------------------------------------------------------------
# Python extractor
# ----------------------------------------------------------------------------


def extract_symbols(src: str) -> dict:
    """Extract top-level function and class signatures from Python source."""
    tree = ast.parse(src)
    symbols: dict[str, dict] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            symbols[node.name] = {
                "kind": "function",
                "args": args,
                "returns": ast.unparse(node.returns) if node.returns else None,
            }
        elif isinstance(node, ast.ClassDef):
            methods: dict[str, dict] = {}
            for sub in ast.iter_child_nodes(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    margs = [a.arg for a in sub.args.args]
                    methods[sub.name] = {
                        "args": margs,
                        "returns": ast.unparse(sub.returns) if sub.returns else None,
                    }
            symbols[node.name] = {"kind": "class", "methods": methods}
    return symbols


def _snapshot_one(path: Path) -> dict:
    """Extract symbols for a single file. Returns the per-file snapshot entry."""
    if not path.exists():
        return {"missing": True}
    suffix = path.suffix
    if suffix == ".py":
        try:
            return {"symbols": extract_symbols(path.read_text()), "lang": "python", "captured_at": now_iso()}
        except SyntaxError as e:
            return {"syntax_error": str(e), "lang": "python"}
    ts_lang = _TS_EXT_MAP.get(suffix)
    if ts_lang is not None:
        if not _TS_AVAILABLE:
            return {"tree_sitter_unavailable": True, "lang": ts_lang}
        try:
            return {
                "symbols": extract_symbols_ts(path.read_bytes(), ts_lang),
                "lang": ts_lang,
                "captured_at": now_iso(),
            }
        except Exception as e:
            return {"parse_error": str(e), "lang": ts_lang}
    return {"unsupported_extension": suffix}


def cmd_snapshot(args: argparse.Namespace) -> None:
    validate_holder(args.holder)
    rd = run_dir(args.run_id)
    snap_dir = rd / "symbol-baseline"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, dict] = {}
    for f in args.files:
        snapshot[f] = _snapshot_one(REPO_ROOT / f)
    (snap_dir / f"{args.holder}.yaml").write_text(
        yaml.safe_dump(snapshot, sort_keys=False)
    )
    parseable = sum(1 for v in snapshot.values() if "symbols" in v)
    by_lang: dict[str, int] = {}
    for v in snapshot.values():
        if "symbols" in v:
            by_lang[v.get("lang", "unknown")] = by_lang.get(v.get("lang", "unknown"), 0) + 1
    detail = ", ".join(f"{k}: {n}" for k, n in sorted(by_lang.items())) or "none"
    print(f"snapshotted {len(snapshot)} file(s) ({parseable} parseable; {detail}) for {args.holder}")


def cmd_check_symbols(args: argparse.Namespace) -> None:
    validate_holder(args.holder)
    rd = run_dir(args.run_id)
    snap_file = rd / "symbol-baseline" / f"{args.holder}.yaml"
    if not snap_file.exists():
        _die(
            f"no baseline snapshot for {args.holder}; call `snapshot` first",
            code=2,
        )
    baseline = yaml.safe_load(snap_file.read_text()) or {}

    drifts: list[dict] = []
    for f in args.files:
        if f not in baseline or "symbols" not in baseline[f]:
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        suffix = path.suffix
        baseline_lang = baseline[f].get("lang", "python")
        try:
            if suffix == ".py":
                current = extract_symbols(path.read_text())
            elif suffix in _TS_EXT_MAP:
                if not _TS_AVAILABLE:
                    drifts.append({"file": f, "kind": "tree_sitter_unavailable"})
                    continue
                current = extract_symbols_ts(path.read_bytes(), _TS_EXT_MAP[suffix])
            else:
                continue
        except SyntaxError as e:
            drifts.append({"file": f, "kind": "syntax_error", "detail": str(e)})
            continue
        except Exception as e:
            drifts.append({"file": f, "kind": "parse_error", "detail": str(e)})
            continue
        old = baseline[f]["symbols"]
        for name, sig in old.items():
            if name not in current:
                drifts.append({"file": f, "symbol": name, "kind": "removed", "lang": baseline_lang, "old": sig})
            elif sig != current[name]:
                drifts.append({
                    "file": f,
                    "symbol": name,
                    "kind": "changed",
                    "lang": baseline_lang,
                    "old": sig,
                    "new": current[name],
                })
        for name in current:
            if name not in old:
                drifts.append({"file": f, "symbol": name, "kind": "added", "lang": baseline_lang, "new": current[name]})

    if not drifts:
        print(json.dumps({"drift": False}))
        return

    others = [l for l in _list_locks(rd) if l["holder"] != args.holder]
    if not others:
        print(json.dumps({"drift": True, "conflict": False, "drifts": drifts}))
        print(
            f"DRIFT detected ({len(drifts)} item(s)) but no other active "
            f"holders — not a conflict",
            file=sys.stderr,
        )
        return

    conflicts_dir = rd / "conflicts"
    conflicts_dir.mkdir(parents=True, exist_ok=True)
    ts = now_iso().replace(":", "").replace("-", "")
    cid = f"drift-{args.holder}-{ts}"
    record = {
        "id": cid,
        "detected_at": now_iso(),
        "kind": "interface_drift",
        "holder": args.holder,
        "drifts": drifts,
        "active_other_holders": [l["holder"] for l in others],
        "resolution": None,
        "resolved_by": None,
    }
    (conflicts_dir / f"{cid}.yaml").write_text(yaml.safe_dump(record, sort_keys=False))
    print(json.dumps({
        "drift": True,
        "conflict": True,
        "conflict_id": cid,
        "drifts": drifts,
    }))
    print(
        f"CONFLICT (interface drift): {args.holder} changed {len(drifts)} "
        f"symbol(s); other active holders: {[l['holder'] for l in others]}",
        file=sys.stderr,
    )
    sys.exit(1)


def cmd_check_wave(args: argparse.Namespace) -> None:
    """Pre-flight check for a parallel wave of code-generator spawns.

    Reads the units in manifest.unit_waves[<wave-idx>], pulls each unit's
    locks_required[] from its code-generator.<unit>.input.yaml handoff, and
    reports pairwise glob collisions using patterns_overlap().

    Output (stdout JSON):
        {
          "safe": bool,
          "wave_idx": int,
          "units": [..unit names..],
          "collisions": [
            {"unit_a": str, "unit_b": str,
             "glob_a": str, "glob_b": str}
          ]
        }

    Always exits 0 — informational. The orchestrator decides what to do.
    """
    rd = run_dir(args.run_id)
    manifest_path = rd / "manifest.yaml"
    if not manifest_path.exists():
        _die(f"manifest not found: {manifest_path}")
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    waves = manifest.get("unit_waves") or []
    if args.wave_idx < 0 or args.wave_idx >= len(waves):
        _die(
            f"wave-idx {args.wave_idx} out of range; "
            f"manifest has {len(waves)} wave(s)"
        )
    wave_units = list(waves[args.wave_idx])

    unit_locks: dict[str, list[str]] = {}
    missing: list[str] = []
    for unit in wave_units:
        input_path = rd / "handoffs" / f"code-generator.{unit}.input.yaml"
        if not input_path.exists():
            missing.append(unit)
            unit_locks[unit] = []
            continue
        doc = yaml.safe_load(input_path.read_text()) or {}
        unit_locks[unit] = list(doc.get("locks_required") or [])

    collisions: list[dict] = []
    for i in range(len(wave_units)):
        for j in range(i + 1, len(wave_units)):
            a, b = wave_units[i], wave_units[j]
            for ga in unit_locks[a]:
                for gb in unit_locks[b]:
                    if patterns_overlap(ga, gb):
                        collisions.append({
                            "unit_a": a, "unit_b": b,
                            "glob_a": ga, "glob_b": gb,
                        })

    result = {
        "safe": not collisions,
        "wave_idx": args.wave_idx,
        "units": wave_units,
        "collisions": collisions,
    }
    if missing:
        result["missing_inputs"] = missing
    print(json.dumps(result, indent=2))
    if collisions:
        print(
            f"COLLISIONS: wave {args.wave_idx} has {len(collisions)} lock overlap(s); "
            f"orchestrator should defer at least one unit to a later wave",
            file=sys.stderr,
        )
    else:
        print(
            f"SAFE: wave {args.wave_idx} ({len(wave_units)} unit(s)) has no lock collisions",
            file=sys.stderr,
        )


def cmd_conflicts(args: argparse.Namespace) -> None:
    rd = run_dir(args.run_id)
    conflicts_dir = rd / "conflicts"
    if not conflicts_dir.exists():
        if args.json:
            print("[]")
        else:
            print("no conflicts")
        return
    records = []
    for f in sorted(conflicts_dir.glob("*.yaml")):
        records.append(yaml.safe_load(f.read_text()))
    if args.json:
        print(json.dumps(records, indent=2))
        return
    if not records:
        print("no conflicts")
        return
    for r in records:
        status = r.get("resolution") or "OPEN"
        print(f"{r['id']:50s} {r['kind']:18s} {status}")


def main() -> None:
    p = argparse.ArgumentParser(description="AIDLC Orchestrator Conflict Resolver")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_acq = sub.add_parser("acquire", help="acquire write or read locks")
    p_acq.add_argument("run_id")
    p_acq.add_argument("holder")
    p_acq.add_argument("--mode", choices=["write", "read"], default="write")
    p_acq.add_argument("--ttl-minutes", type=float, default=None,
                       help="lock auto-expires after N minutes (default: never)")
    p_acq.add_argument("globs", nargs="+")
    p_acq.set_defaults(func=cmd_acquire)

    p_rel = sub.add_parser("release", help="release all locks held by holder")
    p_rel.add_argument("run_id")
    p_rel.add_argument("holder", nargs="?", default=None,
                       help="holder name (ignored if --stale is set)")
    p_rel.add_argument("--stale", action="store_true",
                       help="release all stale locks (by TTL expiry)")
    p_rel.add_argument("--older-than", type=float, default=120.0,
                       help="minutes since acquired to consider stale (default: 120)")
    p_rel.set_defaults(func=cmd_release)

    p_list = sub.add_parser("list", help="list active locks")
    p_list.add_argument("run_id")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_snap = sub.add_parser("snapshot", help="capture baseline AST symbol map")
    p_snap.add_argument("run_id")
    p_snap.add_argument("holder")
    p_snap.add_argument("files", nargs="+")
    p_snap.set_defaults(func=cmd_snapshot)

    p_chk = sub.add_parser("check-symbols", help="diff against baseline; flag drift")
    p_chk.add_argument("run_id")
    p_chk.add_argument("holder")
    p_chk.add_argument("files", nargs="+")
    p_chk.set_defaults(func=cmd_check_symbols)

    p_cf = sub.add_parser("conflicts", help="list open conflict records")
    p_cf.add_argument("run_id")
    p_cf.add_argument("--json", action="store_true")
    p_cf.set_defaults(func=cmd_conflicts)

    p_cw = sub.add_parser(
        "check-wave",
        help="pre-flight pairwise lock collision check for a parallel wave",
    )
    p_cw.add_argument("run_id")
    p_cw.add_argument("--wave-idx", type=int, required=True,
                      help="index into manifest.unit_waves[] to check")
    p_cw.set_defaults(func=cmd_check_wave)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
