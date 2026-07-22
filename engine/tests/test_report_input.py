"""리포트 입력 조립 — 계약·시간헬퍼·메트릭요약·결정적 창 (Phase 1)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import MetricObservation, RawNewsDoc, SectorCard
from sector.store import SectorStore
from sector.report_input import (
    MetricSummary,
    ReportInput,
    ReportInputDiagnostics,
    _REPORT_METRICS,
    _parse_ts,
    _to_utc,
    assemble_report_input,
    build_metric_summaries,
)


# ── Task 1: 계약 + 시간 헬퍼 ──────────────────────────────────────────────
def test_seams_empty_and_diagnostics_required():
    ri = ReportInput(window_from="a", window_to="b",
                     diagnostics=ReportInputDiagnostics(
                         cards_in_window=0, raw_news_in_window=0,
                         cards_scanned=0, raw_scanned=0))
    assert ri.stock_signals == [] and ri.analyst_reports == [] and ri.external_knowledge == []
    assert ri.metrics == [] and ri.diagnostics.metrics_missing == []


def test_parse_ts_normalizes_kst_to_utc():
    dt = _parse_ts("2026-07-21T16:23:13+09:00")
    assert dt == datetime(2026, 7, 21, 7, 23, 13, tzinfo=timezone.utc)
    assert _parse_ts("garbage") is None
    assert _parse_ts("") is None


def test_to_utc_adds_tz_when_naive():
    naive = datetime(2026, 7, 21, 12, 0)
    assert _to_utc(naive) == datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


# ── Task 3: build_metric_summaries ────────────────────────────────────────
def test_build_metric_summaries_marks_missing(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=3.0,
                          unit="$/GB", meta={"item": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=3.5,
                          unit="$/GB", meta={"item": "DRAM"}),
    ])
    out, missing = build_metric_summaries(s, metrics=["memory_price_usd_per_gb", "token_price"])
    by = {m.metric: m for m in out}
    assert by["memory_price_usd_per_gb"].available is True
    assert by["memory_price_usd_per_gb"].summary != ""
    assert by["token_price"].available is False
    assert missing == ["token_price"]


def test_build_metric_summaries_empty_list_is_empty(tmp_path):
    s = SectorStore(tmp_path)
    out, missing = build_metric_summaries(s, metrics=[])   # [] ≠ None
    assert out == [] and missing == []


def test_report_allowlist_covers_core_series():
    for m in ("memory_price_usd_per_gb", "memory_capex", "equip_revenue",
              "tw_monthly_revenue", "openrouter_daily_tokens", "hyperscaler_capex"):
        assert m in _REPORT_METRICS


# ── Task 4: assemble_report_input ─────────────────────────────────────────
def _card(cid, ts):
    # ingested_at 명시 — store.append가 실시계를 찍으면 과거 now 주입 테스트가
    # ingested 게이트(Phase2 T3)에 걸리므로, 수집시각=사건시각으로 고정
    ing = ts if ts and ts[0].isdigit() else ""
    return SectorCard(id=cid, ts=ts, axis="A", title=f"card {cid}", ingested_at=ing)


def _news(nid, title, created_at):
    ing = created_at if created_at and created_at[0].isdigit() else ""
    return RawNewsDoc(id=nid, title=title, created_at=created_at, ingested_at=ing)


def test_assemble_window_is_deterministic_and_bounded(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([
        _card("in",     "2026-07-21T15:00:00+00:00"),  # 창 안(6h 전)
        _card("old",    "2026-07-21T03:00:00+00:00"),  # 창 밖(18h 전)
        _card("future", "2026-07-21T23:00:00+00:00"),  # now 이후 → 제외
        _card("bad",    "not-a-date"),                 # 파싱 불가 → 제외
    ])
    s.append_raw_news([
        _news("rn_in",  "in",  "2026-07-22T00:30:00+09:00"),  # 15:30Z 창 안
        _news("rn_old", "old", "2026-07-21T03:00:00+00:00"),  # 창 밖
    ])
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {c.id for c in ri.cards} == {"in"}
    assert {d.id for d in ri.raw_news} == {"rn_in"}
    assert ri.window_to == now.isoformat()
    assert ri.diagnostics.cards_in_window == 1
    assert ri.diagnostics.raw_news_in_window == 1
    assert ri.diagnostics.cards_scanned == 4
    assert ri.diagnostics.cards_dropped_future == 1
    assert ri.diagnostics.cards_dropped_out == 1
    assert ri.diagnostics.cards_dropped_unparsed == 1
    assert ri.stock_signals == [] and ri.external_knowledge == []


def test_assemble_uses_injected_now_not_wall_clock(tmp_path):
    s = SectorStore(tmp_path)
    past = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
    s.append_cards([_card("x", "2020-01-01T09:00:00+00:00")])  # past-3h → 창 안
    ri = assemble_report_input(s, window_hours=12, now=past, metrics=[])
    assert {c.id for c in ri.cards} == {"x"}


# ── codex 리뷰 보강 ───────────────────────────────────────────────────────
def test_diagnostics_is_required():
    with pytest.raises(ValidationError):
        ReportInput(window_from="a", window_to="b")   # diagnostics 누락 → 검증 실패


def test_build_metric_summaries_handles_interleaved_series(tmp_path):
    # 한 metric 파일에 두 시리즈(DRAM/NAND) 교차 — key()가 meta.item으로 분리
    s = SectorStore(tmp_path)
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=3.0, unit="$/GB", meta={"item": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=1.0, unit="$/GB", meta={"item": "NAND"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=3.6, unit="$/GB", meta={"item": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.9, unit="$/GB", meta={"item": "NAND"}),
    ])
    out, missing = build_metric_summaries(s, metrics=["memory_price_usd_per_gb"])
    assert out[0].available is True and out[0].summary != "" and missing == []


def test_window_boundaries_inclusive(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)  # win_from = 09:00
    s.append_cards([
        _card("at_from", "2026-07-21T09:00:00+00:00"),   # 정확히 win_from
        _card("at_now",  "2026-07-21T21:00:00+00:00"),   # 정확히 now
    ])
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {c.id for c in ri.cards} == {"at_from", "at_now"}   # 양 경계 포함


def test_assemble_reads_across_kst_month_boundary(tmp_path):
    # now = 2026-08-01 04:39 KST = 2026-07-31 19:39 UTC; win_from = 07:39 UTC
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 31, 19, 39, tzinfo=timezone.utc)
    # created 2026-08-01 03:00 KST(=07-31 18:00 UTC) → 창 안이지만 파티션은 KST '2026-08'
    s.append_raw_news([_news("aug", "aug", "2026-08-01T03:00:00+09:00")])
    assert (s.root / "news_raw" / "2026-08.jsonl").exists()   # 8월 파티션에 저장됨
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {d.id for d in ri.raw_news} == {"aug"}             # months=None이라 8월도 읽음


def test_raw_drop_counters(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_raw_news([
        _news("in",  "in",  "2026-07-21T15:00:00+00:00"),
        _news("out", "out", "2026-07-21T03:00:00+00:00"),
        _news("fut", "fut", "2026-07-21T23:00:00+00:00"),
        _news("bad", "bad", "nope"),
    ])
    d = assemble_report_input(s, window_hours=12, now=now, metrics=[]).diagnostics
    assert d.raw_news_in_window == 1
    assert d.raw_dropped_out == 1 and d.raw_dropped_future == 1 and d.raw_dropped_unparsed == 1


def test_unlimited_reads_past_default_500(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([_card(f"c{i}", "2026-07-21T15:00:00+00:00") for i in range(501)])
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert ri.diagnostics.cards_in_window == 501   # 기본 500 캡을 넘어 전량(limit=None)


def test_external_knowledge_filled_when_case_store_given(tmp_path):
    from casemem.store import CaseStore
    from casemem.seeds import load_seeds
    from datetime import datetime, timezone
    cs = CaseStore(tmp_path / "cm")
    load_seeds(cs)
    s = SectorStore(tmp_path / "sec")
    now = datetime(2018, 10, 1, 12, 0, tzinfo=timezone.utc)
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[],
                               case_store=cs, signals=["고객 재고조정 시작"],
                               as_of="2018-10-01")
    assert len(ri.external_knowledge) == 1
    ek = ri.external_knowledge[0]
    assert ek["sector"] == "memory"
    assert any(m["episode_id"] == "mem-2016-2019-supercycle-crash" for m in ek["matches"])


# ── Phase 2 T3: ingested_at look-ahead 게이트 ────────────────────────────
def test_assemble_excludes_future_ingested_but_passes_legacy_empty(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([
        SectorCard(id="ok", ts="2026-07-21T15:00:00+00:00", axis="A", title="ok",
                   ingested_at="2026-07-21T15:05:00+00:00"),
        SectorCard(id="leak", ts="2026-07-21T15:00:00+00:00", axis="A", title="leak",
                   ingested_at="2026-07-21T23:00:00+00:00"),   # 미래 수집 → 제외
    ])
    # 레거시 빈 ingested_at — append가 실시계를 찍으므로 index.jsonl 직접 기록
    legacy = SectorCard(id="legacy", ts="2026-07-21T15:00:00+00:00", axis="A",
                        title="legacy", ingested_at="")
    with s._index.open("a", encoding="utf-8") as f:
        f.write(legacy.model_dump_json() + "\n")
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {c.id for c in ri.cards} == {"ok", "legacy"}         # leak만 차단
    assert ri.diagnostics.cards_ingested_unknown == 1            # legacy 카운트
    assert ri.diagnostics.cards_dropped_future == 1              # ingested 미래도 future로


def test_external_knowledge_empty_without_case_store(tmp_path):
    s = SectorStore(tmp_path)
    from datetime import datetime, timezone
    ri = assemble_report_input(s, window_hours=12,
                               now=datetime(2018, 7, 1, tzinfo=timezone.utc), metrics=[])
    assert ri.external_knowledge == []          # 하위호환
