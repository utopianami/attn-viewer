"""METRIC_REGISTRY 단일 소스 + metric_summary (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.metrics_registry import METRIC_REGISTRY, metric_summary  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def _store(tmp_path, metric: str, rows: list[dict]) -> SectorStore:
    store = SectorStore(tmp_path)
    mdir = tmp_path / "metrics"
    mdir.mkdir(exist_ok=True)
    (mdir / f"{metric}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    return store


def test_registry_covers_existing_metric_files():
    """저장소의 실제 지표 파일이 전부 레지스트리에 등록돼 있다 (real upstream)."""
    mdir = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector/metrics"
    if not mdir.exists():
        return  # CI 등 저장소 없는 환경 — 등록 검증은 라이브 환경에서만
    on_disk = {p.stem for p in mdir.glob("*.jsonl")}
    assert on_disk <= set(METRIC_REGISTRY), f"미등록 지표: {on_disk - set(METRIC_REGISTRY)}"


def test_registry_entries_complete():
    for name, info in METRIC_REGISTRY.items():
        assert info["label"] and info["desc"], name
        assert isinstance(info["keywords"], tuple), name
        assert info["keywords"], name  # 빈 tuple 금지


def test_metric_summary_single_series(tmp_path):
    # meta.item이 같은 두 행 (01~10)이 하나의 그룹으로 뭉쳐서 직전 대비(%) 계산 코드 실행
    store = _store(tmp_path, "kr_semi_export", [
        {"metric": "kr_semi_export", "ts": "2026-06", "value": 100.0,
         "unit": "k_usd", "meta": {"item": "01~10", "provider": "customs"}},
        {"metric": "kr_semi_export", "ts": "2026-07", "value": 110.0,
         "unit": "k_usd", "meta": {"item": "01~10", "provider": "customs"}},
    ])
    txt = metric_summary(store, "kr_semi_export")
    assert "반도체 수출" in txt        # label
    assert "110" in txt and "2026-07" in txt
    assert "+10.0%" in txt             # 직전 대비


def test_metric_summary_grouped_series(tmp_path):
    """meta 그룹(회사·모델별)이 섞인 시계열은 그룹별 최신값으로 요약한다."""
    store = _store(tmp_path, "hyperscaler_capex", [
        {"metric": "hyperscaler_capex", "ts": "2026-03", "value": 19.0,
         "unit": "b_usd", "meta": {"token": "META", "item": "META"}},
        {"metric": "hyperscaler_capex", "ts": "2026-03", "value": 30.0,
         "unit": "b_usd", "meta": {"token": "MSFT", "item": "MSFT"}},
    ])
    txt = metric_summary(store, "hyperscaler_capex")
    assert "META" in txt and "MSFT" in txt


def test_metric_summary_groups_by_app_no_cross_series_delta(tmp_path):
    """app_rank는 meta.app별로 그룹 — 다른 앱 순위끼리 비교한 허위 변화율 금지
    (2026-07-13 codex 리뷰 H1: ChatGPT 25위 vs Claude 5위 → '+400%' 재현)."""
    store = _store(tmp_path, "app_rank", [
        {"metric": "app_rank", "ts": "2026-07-12", "value": 5.0,
         "unit": "rank", "meta": {"app": "Claude", "country": "kr"}},
        {"metric": "app_rank", "ts": "2026-07-12", "value": 25.0,
         "unit": "rank", "meta": {"app": "ChatGPT", "country": "kr"}},
    ])
    txt = metric_summary(store, "app_rank")
    assert "Claude" in txt and "ChatGPT" in txt   # 앱별 그룹 분리
    assert "%" not in txt                          # 순위는 변화율 표시 자체가 무의미


def test_metric_summary_calendar_no_delta(tmp_path):
    """캘린더류(stars/event)는 전기 대비율 계산이 무의미 — 표시 금지."""
    store = _store(tmp_path, "macro_calendar", [
        {"metric": "macro_calendar", "ts": "2026-07-10", "value": 1.0,
         "unit": "stars", "meta": {"title": "CPI", "provider": "x", "kind": "cpi"}},
        {"metric": "macro_calendar", "ts": "2026-07-15", "value": 2.0,
         "unit": "stars", "meta": {"title": "FOMC", "provider": "x", "kind": "fomc"}},
    ])
    txt = metric_summary(store, "macro_calendar")
    assert "FOMC" in txt and "CPI" in txt          # title로 그룹 — 제목 없는 요약 금지
    assert "직전 대비" not in txt


def test_metric_summary_pkg_grouping(tmp_path):
    """sdk_downloads는 meta.pkg별 그룹 — 다른 패키지끼리 변화율 계산 금지."""
    store = _store(tmp_path, "sdk_downloads", [
        {"metric": "sdk_downloads", "ts": "2026-07-11", "value": 1000.0,
         "unit": "downloads", "meta": {"pkg": "openai", "ecosystem": "pypi"}},
        {"metric": "sdk_downloads", "ts": "2026-07-12", "value": 500.0,
         "unit": "downloads", "meta": {"pkg": "anthropic", "ecosystem": "pypi"}},
    ])
    txt = metric_summary(store, "sdk_downloads")
    assert "openai" in txt and "anthropic" in txt
    assert "-50" not in txt                        # 교차 시계열 delta가 없어야 함


def test_metric_summary_missing_data(tmp_path):
    assert metric_summary(SectorStore(tmp_path), "kr_semi_export") == ""
    assert metric_summary(SectorStore(tmp_path), "no_such_metric") == ""


def test_metric_summary_with_null_value(tmp_path):
    """null value 행이 포함되어도 raise하지 않음 (never-raise 계약)."""
    # MetricObservation.value는 float 타입이므로 pydantic이 null 거부
    # 하지만 수집기 버그나 직렬화 우회로 None이 들어올 경우 방어 필요
    # value=None인 스텁 객체로 시뮬레이션
    from unittest.mock import Mock

    store = Mock()
    stub_with_none = Mock()
    stub_with_none.value = None
    stub_with_none.ts = "2026-07"
    stub_with_none.unit = "k_usd"
    stub_with_none.meta = {"item": "01~10"}

    stub_good = Mock()
    stub_good.value = 100.0
    stub_good.ts = "2026-06"
    stub_good.unit = "k_usd"
    stub_good.meta = {"item": "01~10"}

    store.read_metric.return_value = [stub_good, stub_with_none]

    # null value를 건너뛰고 요약 생성 — raise하지 않음
    txt = metric_summary(store, "kr_semi_export")
    assert isinstance(txt, str)  # 예외 없음을 증명
    # stub_with_none을 스킵하고 stub_good만 처리하거나, 포맷 에러 시 ""
    assert "반도체 수출" in txt or txt == ""
