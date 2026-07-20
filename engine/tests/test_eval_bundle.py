# engine/tests/test_eval_bundle.py
import argparse
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evals.build_chain_cases import cmd_capture
from evals.bundle import EvalBundle, capture_bundle, find_violations
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore


def _card(cid: str, ts: str) -> SectorCard:
    # direction 허용값은 sector/contracts.py:22 — pos|neg|neutral|mixed
    return SectorCard(id=cid, ts=ts, axis="A", direction="pos", magnitude=2,
                      source_grade="A", title=f"t-{cid}", interpreted_signal="",
                      raw_quote=f"q-{cid}", url=f"https://a.example/{cid}",
                      entities=["SK하이닉스"])


def _seed(tmp_path, n_cards: int = 3) -> SectorStore:
    store = SectorStore(tmp_path / "sector")
    store.append_cards([_card(f"c-{i}", f"2026-07-{i+1:02d}T00:00:00") for i in range(n_cards)])
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd"),
        MetricObservation(metric="kr_semi_export", ts="2026-07-15", value=2.0, unit="k_usd")])
    return store


def test_store_stamps_ingested_at(tmp_path):
    store = _seed(tmp_path)
    cards = store.read_cards(days=None, limit=100_000)
    assert all(c.ingested_at for c in cards)          # append가 스탬프
    obs = store.read_metric("kr_semi_export")
    assert all(o.ingested_at for o in obs)


def test_capture_refuses_overwrite_and_bad_proven(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(FileExistsError):
        capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                       availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(ValueError):                    # 과거 as_of에 proven 금지
        capture_bundle(store, tmp_path / "b2", as_of="2026-07-02",
                       availability="proven", ra_docs=[], prices={}, macro={})
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with pytest.raises(ValueError):                    # r3-B4: 빈 채널 proven은 사유 없인 거부
        capture_bundle(store, tmp_path / "b3", as_of=today,
                       availability="proven", ra_docs=[], prices={}, macro={})
    capture_bundle(store, tmp_path / "b4", as_of=today, availability="proven",
                   ra_docs=[], prices={"quotes": [{"token": "005930.KS", "last": 1.0}]},
                   macro={"kospi": 1.0},
                   empty_reasons={"ra": "회고성 사건 — RA 미수집"})       # 사유 있으면 OK


def test_capture_filters_full_store_not_limit500(tmp_path):
    store = SectorStore(tmp_path / "sector")
    # 600건 적재 — 기본 limit=500 함정 검증 (store.py:53)
    store.append_cards([_card(f"c-{i}", "2026-07-01T00:00:00") for i in range(600)])
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["card_ids"]) == 600


def test_capture_fail_closed_and_manifest(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(
        store, tmp_path / "b", as_of="2026-07-10", availability="unproven",
        ra_docs=[{"id": "n1", "title": "t", "url": "https://n.example/x",
                  "published_at": "2026-07-09", "snippet": "s"},
                 {"id": "n2", "title": "t", "url": "https://n.example/undated",
                  "snippet": "s"}],
        prices={"quotes": [], "macro": {}}, macro={})
    m = json.loads((out / "manifest.json").read_text())
    assert m["dropped_undated_docs"] == 1
    assert "https://n.example/x" in m["urls"]
    assert "https://n.example/undated" not in m["urls"]
    assert m["content_hash"]                           # hash 존재


# ---------------------------------------------------------------------------
# auto-live 배선 테스트 — 네트워크 호출 없이 monkeypatch로 배선만 검증
# ---------------------------------------------------------------------------

_FAKE_QUOTES = [
    {"token": "005930.KS", "symbol": "005930.KS", "last": 80000.0, "as_of": "2026-07-20"},
    {"token": "000660.KS", "symbol": "000660.KS", "last": 200000.0, "as_of": "2026-07-20"},
]
_FAKE_MACRO = {
    "KOSPI": {"symbol": "^KS11", "last": 2700.0, "day_pct": 0.5, "as_of": "2026-07-20"},
    "USD/KRW": {"symbol": "KRW=X", "last": 1380.0, "day_pct": -0.1, "as_of": "2026-07-20"},
}


def _make_args(**kwargs) -> SimpleNamespace:
    """cmd_capture용 args namespace 헬퍼."""
    defaults = dict(
        case="test-case",
        as_of=time.strftime("%Y-%m-%d", time.gmtime()),
        availability="proven",
        ra_docs="",
        prices="",
        macro="",
        auto_live=False,
        allow_empty_ra="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_auto_live_wires_quotes_and_macro_to_capture_bundle(tmp_path, monkeypatch):
    """--auto-live일 때 수집 함수 결과가 capture_bundle에 올바르게 전달되는지 검증."""
    captured_kwargs: dict = {}

    def fake_collect_prices():
        return {"quotes": _FAKE_QUOTES}

    def fake_collect_macro():
        return _FAKE_MACRO

    def fake_capture_bundle(store, out_dir, *, as_of, availability,
                            ra_docs, prices, macro, empty_reasons=None):
        captured_kwargs.update(
            prices=prices, macro=macro, empty_reasons=empty_reasons
        )
        # 실제 파일 시스템 쓰기는 스킵 — 배선만 검증
        return tmp_path / "bundle"

    monkeypatch.setattr(
        "evals.build_chain_cases._collect_live_prices", fake_collect_prices
    )
    monkeypatch.setattr(
        "evals.build_chain_cases._collect_live_macro", fake_collect_macro
    )
    monkeypatch.setattr(
        "evals.build_chain_cases.capture_bundle", fake_capture_bundle
    )
    monkeypatch.setattr(
        "evals.build_chain_cases._get_store", lambda: object()
    )

    args = _make_args(auto_live=True, allow_empty_ra="테스트 — RA 없음")
    cmd_capture(args)

    assert captured_kwargs["prices"] == {"quotes": _FAKE_QUOTES}
    assert captured_kwargs["macro"] == _FAKE_MACRO
    assert captured_kwargs["empty_reasons"] == {"ra": "테스트 — RA 없음"}


def test_auto_live_conflict_with_prices_file_raises(tmp_path):
    """--auto-live + --prices 파일 동시 지정은 SystemExit."""
    args = _make_args(auto_live=True, prices="/some/prices.json")
    with pytest.raises(SystemExit):
        cmd_capture(args)


def test_auto_live_conflict_with_macro_file_raises(tmp_path):
    """--auto-live + --macro 파일 동시 지정은 SystemExit."""
    args = _make_args(auto_live=True, macro="/some/macro.json")
    with pytest.raises(SystemExit):
        cmd_capture(args)


def test_proven_without_any_source_raises(tmp_path, monkeypatch):
    """proven인데 --auto-live도 --prices/--macro도 없으면 명확한 에러."""
    monkeypatch.setattr(
        "evals.build_chain_cases._get_store", lambda: object()
    )
    args = _make_args(availability="proven", auto_live=False, prices="", macro="")
    with pytest.raises(SystemExit):
        cmd_capture(args)


def test_auto_live_without_allow_empty_ra_passes_no_empty_reasons(tmp_path, monkeypatch):
    """--allow-empty-ra 없으면 empty_reasons는 None(빈 dict 아님)으로 전달."""
    captured_kwargs: dict = {}

    monkeypatch.setattr(
        "evals.build_chain_cases._collect_live_prices",
        lambda: {"quotes": _FAKE_QUOTES}
    )
    monkeypatch.setattr(
        "evals.build_chain_cases._collect_live_macro",
        lambda: _FAKE_MACRO
    )
    monkeypatch.setattr(
        "evals.build_chain_cases.capture_bundle",
        lambda store, out_dir, *, as_of, availability, ra_docs, prices, macro,
               empty_reasons=None: (captured_kwargs.update(empty_reasons=empty_reasons)
                                    or tmp_path / "bundle")
    )
    monkeypatch.setattr(
        "evals.build_chain_cases._get_store", lambda: object()
    )

    args = _make_args(auto_live=True, allow_empty_ra="")
    cmd_capture(args)

    # allow_empty_ra가 빈 문자열이면 empty_reasons=None으로 전달 (빈 dict 아님)
    assert captured_kwargs["empty_reasons"] is None


# ---------------------------------------------------------------------------
# Task 4: EvalBundle 읽기 + find_violations 위반 검출
# ---------------------------------------------------------------------------

def test_bundle_text_includes_metrics_and_prices(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-10",
                         availability="unproven", ra_docs=[],
                         prices={"quotes": [{"symbol": "005930.KS", "close": 254500}],
                                 "macro": {}},
                         macro={"kospi": 3300})
    b = EvalBundle(out)
    assert b.verify_hash()
    txt = b.bundle_text()
    assert "kr_semi_export" in txt and "005930.KS" in txt   # B3: 지표·가격 포함


def test_find_violations_real_layer_shapes_and_answer(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b2", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    layers = [
        {"name": "ra_x", "data": {"items": [{"url": "https://leak.example/a"}]}},
        {"name": "sector_rag", "data": {"cards": [{"url": "https://a.example/c-0"}]}},
    ]
    answer = "결론이다. 자세한 근거는 https://leak.example/b 참고."
    v = find_violations(layers, answer, m)
    assert "https://leak.example/a" in v and "https://leak.example/b" in v
    assert "https://a.example/c-0" not in v                 # bundle 내 카드 URL은 허용


def test_cite_tokens_comma_split_and_channel_binding(tmp_path):   # r4-B1
    store = _seed(tmp_path)
    # token(질의어)과 symbol(야후 심볼)을 다르게 둬 불일치를 못 가리게 한다 (r5)
    out = capture_bundle(store, tmp_path / "b5", as_of="2026-07-10",
                         availability="unproven", ra_docs=[],
                         prices={"quotes": [{"token": "005930", "symbol": "005930.KS",
                                             "last": 1.0}]},
                         macro={})
    m = EvalBundle(out).manifest
    assert m["quote_symbols"] == ["005930.KS"]                    # symbol 저장 (token 아님)
    # 쉼표 근거 전수 검사 — 뒤 토큰(ghost)도 걸린다
    v = find_violations([], "판단 근거 [근거:c-0,ghost-9]", m)
    assert "cite:ghost-9" in v and "cite:c-0" not in v
    # 실제 ref 형식 yahoo:<symbol>은 허용, quote 없는 bundle에선 거부
    assert find_violations([], "[근거:yahoo:005930.KS]", m) == []
    out2 = capture_bundle(store, tmp_path / "b6", as_of="2026-07-10",
                          availability="unproven", ra_docs=[], prices={}, macro={})
    m2 = EvalBundle(out2).manifest
    assert find_violations([], "[근거:yahoo:005930.KS]", m2)      # 빈 snapshot → 위반
    # calc는 이번 실행 calc 레이어의 실구조(data.results, ok=true metric)만 (r5)
    calc_layer = [{"name": "calc",
                   "data": {"results": [{"metric": "per_gap", "ok": True, "value": 1.0}]}}]
    assert find_violations(calc_layer, "[근거:calc:per_gap]", m2) == []
    assert find_violations(calc_layer, "[근거:calc]", m2) == []   # bare calc — 실생성 有
    assert find_violations([], "[근거:calc]", m2)                 # calc 레이어 없으면 위반


def test_bundle_store_read_cards_signature(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b3", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    bs = EvalBundle(out).store()
    assert bs.read_cards(days=14, axis="A", entity=None, limit=500)  # 시그니처 호환
    assert bs.read_metric("kr_semi_export", last_n=90)
