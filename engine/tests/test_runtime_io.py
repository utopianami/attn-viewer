"""Process-safe runtime file primitives."""

from __future__ import annotations


def test_atomic_write_leaves_no_tmp_file(tmp_path):
    from runtime_io import atomic_write_text

    target = tmp_path / "state.json"
    atomic_write_text(target, '{"ok": true}')

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []
