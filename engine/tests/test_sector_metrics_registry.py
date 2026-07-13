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


def test_metric_summary_single_series(tmp_path):
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


def test_metric_summary_missing_data(tmp_path):
    assert metric_summary(SectorStore(tmp_path), "kr_semi_export") == ""
    assert metric_summary(SectorStore(tmp_path), "no_such_metric") == ""
