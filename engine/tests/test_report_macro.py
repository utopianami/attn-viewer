"""거시 관측 브리프(F1/F3, 2026-07-24) — 중요도 게이트·cutoff·부재 처리."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import MetricObservation
from sector.report_macro import macro_brief
from sector.store import SectorStore


def _obs(name, value, day_pct, ts="2026-07-24"):
    return MetricObservation(metric="macro_market", ts=ts, value=value, unit="",
                             meta={"name": name, "token": name, "day_pct": day_pct})


def test_importance_gate_marks_only_threshold_crossers(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("나스닥", 25137.7, -2.2),      # |−2.2| ≥ 2.0 → 중요
        _obs("S&P500", 7408.3, -1.2),       # 임계 미달
        _obs("WTI유가", 90.9, -6.1),        # |−6.1| ≥ 5.0 → 중요
        _obs("엔달러", 163.8, 0.4),         # 임계 미달 (사용자 명시 지표 — 관측엔 포함)
    ])
    block, hot = macro_brief(s)
    assert sorted(hot) == ["WTI유가", "나스닥"]
    assert "나스닥" in block and "⚠중요" in block
    assert "엔달러" in block                 # 게이트 미달이어도 관측 블록엔 존재
    assert sum(1 for l in block.splitlines() if l.endswith("⚠중요")) == 2


def test_day_pct_fallback_uses_previous_observation(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("나스닥", 100.0, None, ts="2026-07-23"),
        _obs("나스닥", 97.0, None, ts="2026-07-24"),   # −3% 계산 폴백 → 중요
    ])
    block, hot = macro_brief(s)
    assert hot == ["나스닥"]
    assert "-3.0%" in block


def test_cutoff_blocks_lookahead_and_empty_store_degrades(tmp_path):
    s = SectorStore(tmp_path)
    assert macro_brief(s) == ("", [])                   # 부재 → 리포트는 기존대로
    s.append_observations([_obs("나스닥", 25137.7, -2.2, ts="2026-07-24")])
    cut = datetime(2026, 7, 23, tzinfo=timezone.utc)
    assert macro_brief(s, cutoff=cut) == ("", [])       # 미래 관측 차단(SF1)
    block, hot = macro_brief(s, cutoff=datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert hot == ["나스닥"]
