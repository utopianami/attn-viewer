# engine/tests/test_build_chain_cases.py
"""list·validate 서브커맨드 단위 테스트."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.build_chain_cases import cmd_list, cmd_validate
from evals.bundle import capture_bundle
from sector.contracts import SectorCard
from sector.store import SectorStore


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _card(cid: str, ts: str, magnitude: int = 2) -> SectorCard:
    return SectorCard(
        id=cid, ts=ts, axis="A", direction="pos", magnitude=magnitude,
        source_grade="A", title=f"title-{cid}",
        interpreted_signal="", raw_quote=f"quote-{cid}",
        url=f"https://example.com/{cid}", entities=["SK하이닉스"],
    )


def _seed_store(tmp_path: Path) -> SectorStore:
    store = SectorStore(tmp_path / "sector")
    store.append_cards([
        _card("c-mag3", "2026-06-01T00:00:00", magnitude=3),
        _card("c-mag2", "2026-06-15T00:00:00", magnitude=2),
        _card("c-mag1", "2026-06-20T00:00:00", magnitude=1),  # 필터돼야 함
    ])
    return store


def _make_bundle(evals_dir: Path, store: SectorStore, bundle_name: str,
                 as_of: str = "2026-06-20") -> Path:
    """unproven bundle을 evals_dir/bundles/ 아래 생성 (validate는 _HERE/bundle_path로 접근)."""
    return capture_bundle(
        store, evals_dir / "bundles" / bundle_name,
        as_of=as_of, availability="unproven",
        ra_docs=[], prices={}, macro={},
    )


def _write_golden(evals_dir: Path, rows: list[dict]) -> None:
    (evals_dir / "golden_chain.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    )


# ---------------------------------------------------------------------------
# cmd_list 스모크
# ---------------------------------------------------------------------------

def test_cmd_list_smoke(tmp_path, capsys, monkeypatch):
    """magnitude≥2 카드만 날짜순 출력, --since 필터, 주별 분포 포함."""
    store = _seed_store(tmp_path)
    monkeypatch.setattr("evals.build_chain_cases._get_store", lambda: store)

    # since=2026-06-10 이후: c-mag2(2026-06-15, m=2), c-mag1(2026-06-20, m=1)
    # magnitude>=2 필터 후: c-mag2만 — c-mag3는 2026-06-01이라 since 전
    args = SimpleNamespace(since="2026-06-10")
    cmd_list(args)

    out = capsys.readouterr().out
    # magnitude=2 카드가 출력돼야 함
    assert "c-mag2" in out
    # magnitude=3 카드는 since(2026-06-10) 이전(2026-06-01)이므로 포함 안 됨
    assert "c-mag3" not in out
    # magnitude=1 카드는 magnitude 필터로 제외
    assert "c-mag1" not in out
    # 주별 분포 섹션 포함
    assert "주별 분포" in out or "W" in out


# ---------------------------------------------------------------------------
# cmd_validate 오류 케이스
# ---------------------------------------------------------------------------

def test_validate_hash_mismatch(tmp_path, monkeypatch):
    """bundle manifest의 content_hash 조작 → hash 불일치 오류."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    store = _seed_store(tmp_path)
    bundle_path = _make_bundle(evals_dir, store, "cj-hash-test")
    rel = bundle_path.relative_to(evals_dir)

    # manifest의 content_hash를 잘못된 값으로 교체 (파일 파싱은 깨지지 않음)
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_hash"] = "0000000000000000"   # 실제 hash와 불일치
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    _write_golden(evals_dir, [{
        "id": "cj-01",
        "type": "factual",
        "split": "dev",
        "question": "질문",
        "as_of": "2026-06-20",
        "bundle_path": str(rel),
        "availability": "unproven",
        "rubric": {"evidence": []},
        "must_not": [],
    }])

    monkeypatch.setattr("evals.build_chain_cases._HERE", evals_dir)

    with pytest.raises(SystemExit) as exc:
        cmd_validate(SimpleNamespace())
    assert "hash 불일치" in str(exc.value)


def test_validate_availability_mismatch(tmp_path, monkeypatch):
    """case availability != manifest availability → availability 불일치 오류."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    store = _seed_store(tmp_path)
    bundle_path = _make_bundle(evals_dir, store, "cj-avail-test")
    rel = bundle_path.relative_to(evals_dir)

    _write_golden(evals_dir, [{
        "id": "cj-02",
        "type": "factual",
        "split": "dev",
        "question": "질문",
        "as_of": "2026-06-20",
        "bundle_path": str(rel),
        "availability": "proven",          # bundle은 unproven인데 여기서 proven으로 선언
        "rubric": {"evidence": []},
        "must_not": [],
    }])

    monkeypatch.setattr("evals.build_chain_cases._HERE", evals_dir)

    with pytest.raises(SystemExit) as exc:
        cmd_validate(SimpleNamespace())
    assert "availability 불일치" in str(exc.value)


def test_validate_evidence_not_in_bundle(tmp_path, monkeypatch):
    """rubric evidence 문자열이 bundle_text에 없을 때 오류."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    store = _seed_store(tmp_path)
    bundle_path = _make_bundle(evals_dir, store, "cj-ev-test")
    rel = bundle_path.relative_to(evals_dir)

    _write_golden(evals_dir, [{
        "id": "cj-03",
        "type": "factual",
        "split": "dev",
        "question": "질문",
        "as_of": "2026-06-20",
        "bundle_path": str(rel),
        "availability": "unproven",
        "rubric": {"evidence": ["이건_번들에_없는_증거_문자열_XYZZY"]},
        "must_not": [],
    }])

    monkeypatch.setattr("evals.build_chain_cases._HERE", evals_dir)

    with pytest.raises(SystemExit) as exc:
        cmd_validate(SimpleNamespace())
    assert "bundle에 없음" in str(exc.value)


def test_validate_ok(tmp_path, monkeypatch, capsys):
    """정상 케이스 — evidence가 bundle_text에 있으면 OK 출력."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    store = _seed_store(tmp_path)
    bundle_path = _make_bundle(evals_dir, store, "cj-ok-test")
    rel = bundle_path.relative_to(evals_dir)

    # bundle_text에 실제로 존재하는 카드 ID를 evidence로 사용
    from evals.bundle import EvalBundle
    b = EvalBundle(bundle_path)
    btxt = b.bundle_text(max_chars=200_000)
    # "c-mag2"는 _seed_store가 넣은 카드 ID — bundle_text에 포함돼야 함
    evidence = "c-mag2"
    assert evidence in btxt, f"테스트 전제 실패: '{evidence}'가 bundle_text에 없음"

    _write_golden(evals_dir, [{
        "id": "cj-ok",
        "type": "factual",
        "split": "dev",
        "question": "질문",
        "as_of": "2026-06-20",
        "bundle_path": str(rel),
        "availability": "unproven",
        "rubric": {"evidence": [evidence]},
        "must_not": [],
    }])

    monkeypatch.setattr("evals.build_chain_cases._HERE", evals_dir)

    cmd_validate(SimpleNamespace())   # SystemExit 없어야 함
    out = capsys.readouterr().out
    assert "OK: 1 cases" in out
