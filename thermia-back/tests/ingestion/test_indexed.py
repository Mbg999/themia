"""Unit tests for the .indexed helpers in scripts/ingest.py."""

from __future__ import annotations

from pathlib import Path


def test_read_and_append_indexed(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    from scripts.ingest import _read_indexed, _append_indexed

    assert _read_indexed(repo_dir) == set()

    _append_indexed(repo_dir, "es/foo.md")

    idx = repo_dir / ".indexed"
    assert idx.exists()
    lines = [l.strip() for l in idx.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines == ["es/foo.md"]
    assert _read_indexed(repo_dir) == {"es/foo.md"}


def test_append_is_idempotent(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    from scripts.ingest import _read_indexed, _append_indexed

    _append_indexed(repo_dir, "es/foo.md")
    _append_indexed(repo_dir, "es/foo.md")

    idx = repo_dir / ".indexed"
    lines = [l.strip() for l in idx.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines == ["es/foo.md"]
    assert _read_indexed(repo_dir) == {"es/foo.md"}


def test_scan_and_filter_skips_indexed(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    (repo_dir / "es").mkdir(parents=True)
    a = repo_dir / "es" / "a.md"
    b = repo_dir / "es" / "b.md"
    a.write_text("# A")
    b.write_text("# B")

    from scripts.ingest import _scan_md_files, _read_indexed

    md_files = _scan_md_files(repo_dir)
    assert set(p.name for p in md_files) == {"a.md", "b.md"}

    # create .indexed with a.md
    (repo_dir / ".indexed").write_text("es/a.md\n")

    indexed = _read_indexed(repo_dir)
    filtered = [p for p in md_files if str(p.relative_to(repo_dir)) not in indexed]
    assert len(filtered) == 1
    assert filtered[0].name == "b.md"
