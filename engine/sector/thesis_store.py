"""테제(Thesis) 저장소 — append-only jsonl·단일 writer(flock)·freshness 파생 (2부 T2).

`<root>/theses.jsonl`에 `ThesisRevision`을 한 줄씩 append한다. 절대 재작성하지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import json
from pathlib import Path

from sector.contracts import MetricObservation
from sector.period import parse_period as _parse_period
from sector.store import SectorStore
from sector.thesis_contracts import RequiredInput, ThesisRevision


def _dump(rev: ThesisRevision) -> dict:
    """정규화 dump — 실질 동일 비교에 쓰는 안정적 표현."""
    return rev.model_dump(mode="json")


def _is_same_substance(a: ThesisRevision, b: ThesisRevision) -> bool:
    """statements·assessment·key_metrics(metric,value) 목록이 동일하면 '실질 동일'."""
    da, db = _dump(a), _dump(b)
    if da["statements"] != db["statements"]:
        return False
    if da["assessment"] != db["assessment"]:
        return False
    km_a = [(km["metric"], km["value"]) for km in da["key_metrics"]]
    km_b = [(km["metric"], km["value"]) for km in db["key_metrics"]]
    return km_a == km_b


class ThesisStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "theses.jsonl"

    def _read_all(self) -> list[ThesisRevision]:
        if not self._path.exists():
            return []
        out: list[ThesisRevision] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(ThesisRevision.model_validate_json(line))
            except Exception:  # noqa: BLE001 — 손상 줄은 건너뜀
                continue
        return out

    def append(self, rev: ThesisRevision) -> bool:
        """rev를 append. 중복 revision_id → ValueError. 직전 최신과 실질 동일 → False(미기록)."""
        with self._path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                existing = self._read_all()
                for e in existing:
                    if e.revision_id == rev.revision_id:
                        raise ValueError(
                            f"duplicate revision_id: {rev.revision_id!r}")
                same_id = [e for e in existing if e.id == rev.id]
                if same_id:
                    latest = max(same_id, key=lambda e: e.valid_from)
                    if _is_same_substance(latest, rev):
                        return False
                f.write(json.dumps(_dump(rev), ensure_ascii=False) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return True

    def revisions(self, id: str) -> list[ThesisRevision]:
        return sorted((e for e in self._read_all() if e.id == id),
                     key=lambda e: e.valid_from)

    def latest(self, id: str) -> ThesisRevision | None:
        revs = self.revisions(id)
        return revs[-1] if revs else None

    def latest_all(self) -> list[ThesisRevision]:
        """모든 id의 최신 revision 목록."""
        by_id: dict[str, ThesisRevision] = {}
        for e in self._read_all():
            cur = by_id.get(e.id)
            if cur is None or e.valid_from > cur.valid_from:
                by_id[e.id] = e
        return list(by_id.values())

    def latest_as_of(self, id: str, as_of: str) -> ThesisRevision | None:
        """as_of가 날짜(YYYY-MM-DD, len==10, 'T' 없음)면 valid_from[:10] <= as_of 비교,
        아니면 valid_from <= as_of 전체 문자열 비교."""
        is_date_only = len(as_of) == 10 and "T" not in as_of
        candidates = []
        for e in self.revisions(id):
            if is_date_only:
                if e.valid_from[:10] <= as_of:
                    candidates.append(e)
            else:
                if e.valid_from <= as_of:
                    candidates.append(e)
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.valid_from)


# parse_period는 sector.period로 이전(2부 T9 블로커 3) — thesis_guard.py의
# resolve_required_inputs와 동일 로직 공유, 이 모듈은 하위호환 re-export만 유지.


def _matches_filter(meta: dict, meta_filter: dict) -> bool:
    return all(meta.get(k) == v for k, v in meta_filter.items())


def freshness_for_inputs(
    required_inputs: list[RequiredInput], store: SectorStore, now: _dt.datetime,
    rows_by_metric: dict[str, list[MetricObservation]] | None = None,
) -> str:
    """required_inputs 목록만으로 fresh/degraded/stale을 판정한다 (freshness()의 코어).

    각 입력은 meta_filter에 매칭하는 관측 중 (미래·파싱불가 제외한) 유효 관측의
    최신 ts 나이 <= max_age_days 이고, 유효 매칭 관측 수 >= min_count 이면 충족.
    전부 충족 → fresh, 일부 충족 → degraded, 전무 충족 → stale.
    required_inputs가 비어있으면 fresh.

    `ThesisRevision`이 아직 없는 상태(예: 신규 생성 전 사전 게이트, 2부 T5)에서도
    쓸 수 있도록 rev 대신 required_inputs 자체를 받는다 — freshness()가 이를 감싼다.

    `rows_by_metric`을 주면 metric별 store.read_metric 호출을 건너뛰고 그 값을
    쓴다(2부 T9 블로커 4 — update_thesis가 게이트·조립 전체에서 metric당 정확히
    1회만 읽도록 호출측이 미리 읽어 캐시를 넘긴다). 없으면 기존처럼 직접 읽는다.
    """
    if not required_inputs:
        return "fresh"
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    satisfied_count = 0
    for ri in required_inputs:
        if rows_by_metric is not None:
            observations = rows_by_metric.get(ri.metric, [])
        else:
            observations = store.read_metric(ri.metric, last_n=1_000_000)
        valid_ages: list[float] = []
        for o in observations:
            if not _matches_filter(o.meta, ri.meta_filter):
                continue
            period = _parse_period(o.ts)
            if period is None:
                continue  # 파싱 불가 → 무효
            start, end = period
            if start > now:
                continue  # 기간 전체가 미래 → 무효 (fail-closed)
            age_days = max(0.0, (now - end).total_seconds() / 86400.0)
            valid_ages.append(age_days)
        if not valid_ages:
            continue
        latest_age = min(valid_ages)
        if latest_age <= ri.max_age_days and len(valid_ages) >= ri.min_count:
            satisfied_count += 1

    if satisfied_count == len(required_inputs):
        return "fresh"
    if satisfied_count == 0:
        return "stale"
    return "degraded"


def freshness(rev: ThesisRevision, store: SectorStore, now: _dt.datetime) -> str:
    """required_inputs별 충족 여부를 계산해 fresh/degraded/stale을 판정한다.

    각 입력은 meta_filter에 매칭하는 관측 중 (미래·파싱불가 제외한) 유효 관측의
    최신 ts 나이 <= max_age_days 이고, 유효 매칭 관측 수 >= min_count 이면 충족.
    전부 충족 → fresh, 일부 충족 → degraded, 전무 충족 → stale.
    required_inputs가 비어있으면 fresh.
    """
    return freshness_for_inputs(rev.required_inputs, store, now)
