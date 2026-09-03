#!/usr/bin/env python3
"""Audit and reversibly repair known duplicate and orphan runtime artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
_METRIC_META_FIELDS = (
    "model", "code", "pkg", "ecosystem", "token", "provider",
    "app", "country", "item", "title",
)


def _raw_key(row: dict) -> str | None:
    value = row.get("id")
    return str(value) if value not in (None, "") else None


def _metric_key(row: dict) -> str | None:
    if "ts" not in row:
        return None
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    parts = [str(row["ts"])] + [str(meta.get(field, "")) for field in _METRIC_META_FIELDS]
    return "|".join(parts)


def _dedupe_jsonl(path: Path, key_fn: Callable[[dict], str | None]) -> dict:
    original = path.read_text(encoding="utf-8")
    kept: list[str] = []
    seen: dict[str, dict] = {}
    duplicate_rows = 0
    conflicting_rows = 0
    invalid_rows = 0
    for line in original.splitlines():
        if not line.strip():
            kept.append(line)
            continue
        try:
            row = json.loads(line)
        except ValueError:
            invalid_rows += 1
            kept.append(line)
            continue
        if not isinstance(row, dict):
            invalid_rows += 1
            kept.append(line)
            continue
        key = key_fn(row)
        if key is None:
            kept.append(line)
            continue
        if key in seen:
            duplicate_rows += 1
            if row != seen[key]:
                conflicting_rows += 1
            continue
        seen[key] = row
        kept.append(line)
    repaired = "\n".join(kept)
    if original.endswith("\n") and kept:
        repaired += "\n"
    return {
        "path": path,
        "original": original,
        "repaired": repaired,
        "duplicate_rows": duplicate_rows,
        "conflicting_rows": conflicting_rows,
        "invalid_rows": invalid_rows,
    }


def _atomic_write(path: Path, text: str) -> None:
    fd, raw_temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_path, path.stat().st_mode & 0o777)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _blog_orphans(storage_root: Path) -> list[Path]:
    orphans: list[Path] = []
    pattern = "users/*/corpus/naver/*/raw"
    for raw_dir in sorted(path for path in storage_root.glob(pattern) if path.is_dir()):
        blog_root = raw_dir.parent
        known_ids: set[str] = set()
        explicit_raw_paths: set[Path] = set()
        index_path = blog_root / "index.jsonl"
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    known_ids.add(str(row["id"]))
        for article in (blog_root / "articles").glob("*.md"):
            known_ids.add(article.stem)
        for metadata_path in (blog_root / "metadata").glob("*.json"):
            known_ids.add(metadata_path.stem)
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            relative = metadata.get("rawHtmlPath") if isinstance(metadata, dict) else None
            if isinstance(relative, str) and relative:
                explicit_raw_paths.add((blog_root / relative).resolve())
        for raw_path in sorted(raw_dir.glob("*.html")):
            if raw_path.stem not in known_ids and raw_path.resolve() not in explicit_raw_paths:
                orphans.append(raw_path)
    return orphans


def _backup_file(storage_root: Path, backup_root: Path, source: Path) -> Path:
    destination = backup_root / "original" / source.relative_to(storage_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _quarantine_storage_file(storage_root: Path, backup_root: Path, source: Path) -> Path:
    destination = backup_root / "quarantine" / "storage" / source.relative_to(storage_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return destination


def repair(
    storage_root: Path | str,
    *,
    apply: bool = False,
    backup_root: Path | str | None = None,
    tmp_dir: Path | str | None = None,
) -> dict:
    """Return an inventory by default; mutate only behind an unused backup root."""
    storage_root = Path(storage_root).resolve()
    tmp_dir = Path(tmp_dir or tempfile.gettempdir()).resolve()
    resolved_backup: Path | None = None
    if apply:
        if backup_root is None:
            raise ValueError("--backup-root is required with --apply")
        resolved_backup = Path(backup_root).resolve()
        if resolved_backup.exists():
            raise ValueError(f"backup root must not exist: {resolved_backup}")
        if resolved_backup == storage_root or storage_root in resolved_backup.parents:
            raise ValueError("backup root must be outside storage root")

    scans: list[dict] = []
    sector = storage_root / "rag" / "memory_sector"
    for path in sorted((sector / "news_raw").glob("*.jsonl")):
        scans.append(_dedupe_jsonl(path, _raw_key))
    for path in sorted((sector / "metrics").glob("*.jsonl")):
        scans.append(_dedupe_jsonl(path, _metric_key))

    orphan_paths = _blog_orphans(storage_root)
    summary_temp_paths = sorted(
        path for path in tmp_dir.glob("blog-summary-*") if path.is_file()
    )
    duplicate_rows = sum(item["duplicate_rows"] for item in scans)
    conflicting_rows = sum(item["conflicting_rows"] for item in scans)
    invalid_rows = sum(item["invalid_rows"] for item in scans)
    changed = [item for item in scans if item["duplicate_rows"]]
    report = {
        "mode": "apply" if apply else "dry-run",
        "storage_root": str(storage_root),
        "backup_root": str(resolved_backup) if resolved_backup else None,
        "jsonl_files_scanned": len(scans),
        "files_with_duplicates": [str(item["path"].relative_to(storage_root)) for item in changed],
        "duplicate_rows": duplicate_rows,
        "duplicate_rows_removed": 0,
        "conflicting_duplicate_rows": conflicting_rows,
        "invalid_rows_preserved": invalid_rows,
        "orphan_raw_files": len(orphan_paths),
        "summary_temp_files": len(summary_temp_paths),
        "quarantined_files": 0,
    }
    if not apply:
        return report

    assert resolved_backup is not None
    resolved_backup.mkdir(parents=True)
    for item in changed:
        _backup_file(storage_root, resolved_backup, item["path"])
        _atomic_write(item["path"], item["repaired"])
    for path in orphan_paths:
        _quarantine_storage_file(storage_root, resolved_backup, path)
    temp_quarantine = resolved_backup / "quarantine" / "tmp"
    for path in summary_temp_paths:
        temp_quarantine.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(temp_quarantine / path.name))

    report["duplicate_rows_removed"] = duplicate_rows
    report["quarantined_files"] = len(orphan_paths) + len(summary_temp_paths)
    (resolved_backup / "repair-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=ROOT / "storage")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--tmp-dir", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args(argv)
    try:
        report = repair(
            args.storage_root,
            apply=args.apply,
            backup_root=args.backup_root,
            tmp_dir=args.tmp_dir,
        )
    except ValueError as error:
        print(f"repair refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
