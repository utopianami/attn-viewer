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
    v, _ = find_violations(layers, answer, m)
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
    v, u = find_violations([], "판단 근거 [근거:c-0,ghost-9]", m)
    assert "cite:ghost-9" in v and "cite:c-0" not in v
    # 실제 ref 형식 yahoo:<symbol>은 허용, quote 없는 bundle에선 거부
    v_yahoo, _ = find_violations([], "[근거:yahoo:005930.KS]", m)
    assert v_yahoo == []
    out2 = capture_bundle(store, tmp_path / "b6", as_of="2026-07-10",
                          availability="unproven", ra_docs=[], prices={}, macro={})
    m2 = EvalBundle(out2).manifest
    v_yahoo2, _ = find_violations([], "[근거:yahoo:005930.KS]", m2)
    assert v_yahoo2                                               # 빈 snapshot → 위반
    # calc는 이번 실행 calc 레이어의 실구조(data.results, ok=true metric)만 (r5)
    calc_layer = [{"name": "calc",
                   "data": {"results": [{"metric": "per_gap", "ok": True, "value": 1.0}]}}]
    v_calc1, _ = find_violations(calc_layer, "[근거:calc:per_gap]", m2)
    assert v_calc1 == []
    v_calc2, _ = find_violations(calc_layer, "[근거:calc]", m2)
    assert v_calc2 == []                                          # bare calc — 실생성 有
    v_calc3, _ = find_violations([], "[근거:calc]", m2)
    assert v_calc3                                                # calc 레이어 없으면 위반


def test_url_norm_allows_scheme_host_case_and_trailing_slash(tmp_path):
    """I-1: scheme·host 대소문자 및 끝 슬래시 차이는 위반으로 보지 않는다.
    manifest에 https://a.example/c-0 이 있을 때:
      - 답변의 https://A.EXAMPLE/c-0/ → 위반 아님 (host 대소문자 + 끝 슬래시)
      - 답변의 https://a.example/C-0  → 위반 (path 대소문자는 민감하게 보존)"""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_norm", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    # 카드 c-0의 URL이 manifest에 등록돼 있어야 함
    assert "https://a.example/c-0" in m["urls"]

    # host 대소문자 + 끝 슬래시: 위반 아님
    v_allowed, _ = find_violations([], "참고: https://A.EXAMPLE/c-0/", m)
    assert "https://A.EXAMPLE/c-0/" not in v_allowed, (
        "host 대소문자·끝 슬래시 차이만 있는 URL이 위반으로 잡혔다")

    # path 대소문자 다름: 위반
    v_path, _ = find_violations([], "참고: https://a.example/C-0", m)
    assert "https://a.example/C-0" in v_path, (
        "path 대소문자가 다른 URL이 위반으로 잡히지 않았다")


def test_bundle_store_read_cards_signature(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b3", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    bs = EvalBundle(out).store()
    assert bs.read_cards(days=14, axis="A", entity=None, limit=500)  # 시그니처 호환
    assert bs.read_metric("kr_semi_export", last_n=90)


# ---------------------------------------------------------------------------
# 새 테스트: 서술형/식별자형 분리 + bundle_text 부분일치 허용
# ---------------------------------------------------------------------------

def test_descriptive_cite_tokens_go_to_unresolved_not_violations(tmp_path):
    """한글/공백 포함 서술형 토큰은 violations 아닌 unresolved_cites로."""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_desc", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    answer = "요약 [근거:S급 공시,뉴스]"
    v, u = find_violations([], answer, m)
    assert v == []                              # violations 없음
    assert "cite:S급 공시" in u
    assert "cite:뉴스" in u


def test_ghost_identifier_still_violation(tmp_path):
    """ghost-99 같은 식별자형 미등록 토큰은 violations에 남는다."""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_ghost", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    v, u = find_violations([], "[근거:ghost-99]", m)
    assert "cite:ghost-99" in v
    assert u == []


def test_identifier_in_bundle_text_is_allowed(tmp_path):
    """식별자형이라도 bundle_text에 부분문자열로 있으면 허용 (매체명 오탐 차단)."""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_msn", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    # MSN이 bundle_text에 있을 때 → 허용
    v_pass, u_pass = find_violations([], "[근거:MSN]", m, bundle_text="MSN 뉴스 기사")
    assert "cite:MSN" not in v_pass
    # MSN이 bundle_text에 없을 때 → 위반
    v_fail, u_fail = find_violations([], "[근거:MSN]", m, bundle_text="다른 내용")
    assert "cite:MSN" in v_fail


def test_url_violations_unchanged(tmp_path):
    """URL 위반 동작은 변경 없음 — tuple 반환으로 변경돼도 violations[0]에 URL 포함."""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_url", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    answer = "자세한 내용은 https://leak.example/secret 참고"
    v, u = find_violations([], answer, m)
    assert "https://leak.example/secret" in v
    assert u == []


# ---------------------------------------------------------------------------
# judge_context: 관련성 선발 + 지표 상시 포함
# ---------------------------------------------------------------------------

def _card_many(n: int) -> list[SectorCard]:
    """n장 카드 생성 — 마지막 카드(인덱스 n-1)에만 'HBMSPECIAL' 포함."""
    cards = []
    for i in range(n):
        title = "HBMSPECIAL 공급 이슈" if i == n - 1 else f"일반 뉴스 {i}"
        raw = "HBMSPECIAL 분기 출하량" if i == n - 1 else f"내용 {i}"
        cards.append(SectorCard(
            id=f"c-{i}",
            ts=f"2026-0{(i % 9) + 1}-01T00:00:00",
            axis="A", direction="pos", magnitude=2,
            source_grade="A", title=title,
            interpreted_signal="",
            raw_quote=raw,
            url=f"https://a.example/c-{i}",
            entities=[],
        ))
    return cards


def test_judge_context_includes_evidence_term_from_last_card(tmp_path):
    """rubric evidence 용어가 마지막 카드(600번째)에만 있을 때 judge_context에 포함됨."""
    store = SectorStore(tmp_path / "sector")
    store.append_cards(_card_many(600))
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd"),
    ])
    out = capture_bundle(store, tmp_path / "b_jc", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    eb = EvalBundle(out)
    rubric = {"evidence": ["HBMSPECIAL 분기 출하량"], "mechanism": "", "state_link": ""}
    answer_md = "HBM 공급이 증가했다. [근거:c-599]"
    ctx = eb.judge_context(answer_md, rubric, max_chars=20000)
    assert "HBMSPECIAL" in ctx, "rubric evidence 용어가 포함된 마지막 카드가 judge_context에 없음"


def test_judge_context_always_includes_metric_lines(tmp_path):
    """지표 라인은 max_chars가 작아도 항상 포함된다."""
    store = SectorStore(tmp_path / "sector")
    store.append_cards([_card("c-0", "2026-07-01T00:00:00")])
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=9.9, unit="k_usd"),
    ])
    out = capture_bundle(store, tmp_path / "b_metric", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    eb = EvalBundle(out)
    # max_chars를 매우 작게 줘도 지표 라인은 포함돼야 함
    ctx = eb.judge_context("", {}, max_chars=5000)
    assert "kr_semi_export" in ctx, "지표 라인이 judge_context에 없음"


# ---------------------------------------------------------------------------
# 픽스: 위반 검출 오탐 2종 — 본문 URL & DA 태그 (2026-07-20)
# ---------------------------------------------------------------------------

def test_url_in_bundle_text_not_manifest_is_allowed(tmp_path):
    """manifest.urls에 없어도 bundle_text에 부분문자열로 존재하는 URL은 허용.
    없으면 위반으로 잡혀야 한다. (cj-14 seekingalpha·cj-19 stocktwits 오탐 재현)"""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_bt_url", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    url_in_text = "https://seekingalpha.com/article/12345"
    url_absent = "https://seekingalpha.com/article/99999"

    # bundle_text에 url_in_text가 있을 때 → 허용
    v_pass, _ = find_violations([], f"참고 [자세히]({url_in_text})", m,
                                bundle_text=f"raw_quote: ...{url_in_text}...")
    assert url_in_text not in v_pass, "bundle_text에 존재하는 URL이 위반으로 잡혔다"

    # bundle_text에 url_absent가 없을 때 → 위반 유지
    v_fail, _ = find_violations([], f"참고 [자세히]({url_absent})", m,
                                bundle_text=f"raw_quote: ...{url_in_text}...")
    assert url_absent in v_fail, "bundle_text에 없는 URL이 위반으로 잡히지 않았다"


def test_da_cite_tokens_allowed_when_da_blind_layer_present(tmp_path):
    """da_blind 레이어가 있을 때 cite:da_gpt·cite:da_fable 허용.
    레이어 없으면 위반으로 잡혀야 한다. (cj-10 da_gpt 오탐 재현)"""
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b_da", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    da_layer = [{"name": "da_blind", "data": {"unit_answers": [], "status": "ok"}}]

    # da_blind 레이어 있음 → 허용
    v_pass, _ = find_violations(da_layer, "[근거:da_gpt,da_fable]", m)
    assert "cite:da_gpt" not in v_pass, "da_blind 레이어 있는데 da_gpt가 위반으로 잡혔다"
    assert "cite:da_fable" not in v_pass, "da_blind 레이어 있는데 da_fable가 위반으로 잡혔다"

    # da_blind 레이어 없음 → 위반
    v_fail, _ = find_violations([], "[근거:da_gpt,da_fable]", m)
    assert "cite:da_gpt" in v_fail, "da_blind 레이어 없는데 da_gpt가 위반으로 잡히지 않았다"
    assert "cite:da_fable" in v_fail, "da_blind 레이어 없는데 da_fable가 위반으로 잡히지 않았다"
