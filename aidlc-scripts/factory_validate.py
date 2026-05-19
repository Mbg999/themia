#!/usr/bin/env python3
"""Validate a YAML or JSON document against a JSON Schema.

Usage:
    python3 aidlc-scripts/factory_validate.py <schema.json> <doc.yaml|doc.json>

Exit codes:
    0  document is valid
    1  document is invalid (details on stderr)
    2  usage error or missing dependency
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


ORCHESTRATOR_VERSION = "0.2.0"
EXPECTED_SCHEMA_VERSION = 1


def _strict_check(doc: dict, doc_path: Path) -> list[str]:
    """Content-level validation beyond JSON Schema."""
    issues: list[str] = []
    status = doc.get("status")
    artifacts = doc.get("artifacts", []) or []
    findings = doc.get("findings", []) or []
    knowledge = doc.get("emitted_knowledge", []) or []

    # status: complete requires at least 1 artifact with a non-empty path
    if status == "complete":
        valid_paths = [a for a in artifacts if isinstance(a, dict) and a.get("path")]
        if not valid_paths:
            issues.append("status=complete but no artifact with a non-empty `path`")
    if status == "blocked":
        if not doc.get("block_reason"):
            issues.append("status=blocked but no `block_reason` field")

    # tests_added > 0 requires at least 1 test file in artifacts
    tests_added = doc.get("tests_added", 0)
    if isinstance(tests_added, int) and tests_added > 0:
        has_test_artifact = False
        for a in artifacts:
            path = a.get("path", "") if isinstance(a, dict) else ""
            stem = Path(path).stem
            if (
                any(p in ("test", "tests", "__tests__", "spec") for p in Path(path).parts)
                or stem.startswith("test_")
                or stem.endswith("_test")
                or stem.endswith("_spec")
            ):
                has_test_artifact = True
                break
        if not has_test_artifact:
            issues.append(f"tests_added={tests_added} but no test file found in artifacts")

    # findings with severity P0/P1 should have a recommendation
    for f in findings:
        sev = f.get("severity")
        if sev in ("P0", "P1") and not f.get("recommendation"):
            loc = f.get("file", "?")
            issues.append(f"finding [{sev}] {loc} has no `recommendation`")

    # emitted_knowledge body must be non-empty
    for i, k in enumerate(knowledge):
        if not k.get("body"):
            issues.append(f"emitted_knowledge[{i}].body is empty")

    return issues


def main() -> None:
    p = argparse.ArgumentParser(description="Validate a document against a JSON Schema")
    p.add_argument("schema", help="path to JSON Schema file")
    p.add_argument("document", help="path to YAML or JSON document")
    p.add_argument("--strict", action="store_true",
                   help="enable content-level checks beyond schema validation")
    args = p.parse_args()

    schema_path = Path(args.schema)
    doc_path = Path(args.document)

    if not schema_path.exists():
        _die(f"schema not found: {schema_path}")
    if not doc_path.exists():
        _die(f"document not found: {doc_path}")

    try:
        from jsonschema import Draft7Validator
    except ImportError:
        _die(f"missing dependency: {sys.executable} -m pip install jsonschema")

    schema = json.loads(schema_path.read_text())

    suffix = doc_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            _die(f"missing dependency: {sys.executable} -m pip install pyyaml")
        doc = yaml.safe_load(doc_path.read_text())
    elif suffix == ".json":
        doc = json.loads(doc_path.read_text())
    else:
        _die(f"unsupported document extension: {suffix} (expected .yaml/.yml/.json)")

    # Version check: schema $id should indicate expected schema version
    schema_id = schema.get("$id", "")
    schema_ver = schema.get("schema_version")
    if schema_ver is not None and schema_ver != EXPECTED_SCHEMA_VERSION:
        print(
            f"VERSION MISMATCH schema_version={schema_ver}, expected {EXPECTED_SCHEMA_VERSION} "
            f"(orchestrator v{ORCHESTRATOR_VERSION})",
            file=sys.stderr,
        )

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))

    if errors:
        print(f"INVALID {doc_path} ({len(errors)} schema error(s)):", file=sys.stderr)
        for err in errors:
            loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
            print(f"  - {loc}: {err.message}", file=sys.stderr)
        sys.exit(1)

    if args.strict:
        strict_issues = _strict_check(doc, doc_path)
        if strict_issues:
            print(f"STRICT FAIL {doc_path} ({len(strict_issues)} content issue(s)):", file=sys.stderr)
            for issue in strict_issues:
                print(f"  - {issue}", file=sys.stderr)
            sys.exit(1)

    print(f"OK {doc_path} matches {schema_path.name}")
    sys.exit(0)


if __name__ == "__main__":
    main()
