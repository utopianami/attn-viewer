"""Reversible repair for duplicate JSONL rows and unreferenced temp artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.repair_runtime_data import repair  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    storage = tmp_path / "storage"
    raw = storage / "rag" / "memory_sector" / "news_raw" / "2026-09.jsonl"
    metric = storage / "rag" / "memory_sector" / "metrics" / "token_price.jsonl"
    _write_jsonl(raw, [
        {"id": "first", "title": "preserve"},
        {"id": "dup", "title": "first payload"},
        {"id": "dup", "title": "later payload"},
    ])
    _write_jsonl(metric, [
        {"metric": "token_price", "ts": "2026-09-03", "value": 1,
         "meta": {"model": "same"}, "ingested_at": "first"},
        {"metric": "token_price", "ts": "2026-09-03", "value": 2,
         "meta": {"model": "same"}, "ingested_at": "later"},
    ])

    blog = storage / "users" / "u" / "corpus" / "naver" / "blog"
    (blog / "raw").mkdir(parents=True)
    (blog / "articles").mkdir()
    (blog / "metadata").mkdir()
    referenced = blog / "raw" / "naver-blog-1.html"
    orphan = blog / "raw" / "naver-blog-2.html"
    referenced.write_text("kept", encoding="utf-8")
    orphan.write_text("quarantine", encoding="utf-8")
    (blog / "articles" / "naver-blog-1.md").write_text("# kept", encoding="utf-8")
    (blog / "metadata" / "naver-blog-1.json").write_text(
        json.dumps({"id": "naver-blog-1", "rawHtmlPath": "raw/naver-blog-1.html"}),
        encoding="utf-8",
    )
    _write_jsonl(blog / "index.jsonl", [{"id": "naver-blog-1"}])

    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "blog-summary-leaked.txt").write_text("leaked", encoding="utf-8")
    return storage, temp_dir, orphan, referenced


def test_dry_run_reports_duplicates_without_mutating(tmp_path):
    storage, temp_dir, orphan, referenced = _fixture(tmp_path)
    raw = storage / "rag" / "memory_sector" / "news_raw" / "2026-09.jsonl"
    metric = storage / "rag" / "memory_sector" / "metrics" / "token_price.jsonl"
    before = {raw: raw.read_bytes(), metric: metric.read_bytes()}

    report = repair(storage, apply=False, backup_root=None, tmp_dir=temp_dir)

    assert report["duplicate_rows"] == 2
    assert report["duplicate_rows_removed"] == 0
    assert report["orphan_raw_files"] == 1
    assert report["summary_temp_files"] == 1
    assert all(path.read_bytes() == content for path, content in before.items())
    assert orphan.exists() and referenced.exists()
    assert (temp_dir / "blog-summary-leaked.txt").exists()


def test_apply_backs_up_dedupes_and_quarantines(tmp_path):
    storage, temp_dir, orphan, referenced = _fixture(tmp_path)
    backup = tmp_path / "unused-backup"

    report = repair(storage, apply=True, backup_root=backup, tmp_dir=temp_dir)

    assert report["duplicate_rows_removed"] == 2
    assert (backup / "original" / "rag" / "memory_sector" / "news_raw" / "2026-09.jsonl").exists()
    assert (backup / "original" / "rag" / "memory_sector" / "metrics" / "token_price.jsonl").exists()
    assert (backup / "quarantine" / "storage" / orphan.relative_to(storage)).exists()
    assert (backup / "quarantine" / "tmp" / "blog-summary-leaked.txt").exists()
    assert not orphan.exists()
    assert referenced.exists()
    assert not (temp_dir / "blog-summary-leaked.txt").exists()

    raw_rows = (storage / "rag" / "memory_sector" / "news_raw" / "2026-09.jsonl").read_text().splitlines()
    metric_rows = (storage / "rag" / "memory_sector" / "metrics" / "token_price.jsonl").read_text().splitlines()
    assert len(raw_rows) == 2
    assert json.loads(raw_rows[1])["title"] == "first payload"
    assert len(metric_rows) == 1
    assert json.loads(metric_rows[0])["value"] == 1


def test_apply_refuses_existing_or_missing_backup_root(tmp_path):
    storage, temp_dir, _orphan, _referenced = _fixture(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        repair(storage, apply=True, backup_root=existing, tmp_dir=temp_dir)
    with pytest.raises(ValueError, match="required"):
        repair(storage, apply=True, backup_root=None, tmp_dir=temp_dir)
