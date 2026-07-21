"""섹터 저장소 — storage/rag/memory_sector/ 아래 jsonl 단일 창구 (원칙 6·계획 §8-2)."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path

from sector.contracts import CollectorResult, MetricObservation, RawNewsDoc, SectorCard

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


class SectorStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "cards").mkdir(parents=True, exist_ok=True)
        (self.root / "metrics").mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(parents=True, exist_ok=True)
        (self.root / "news_raw").mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.jsonl"
        self._state = self.root / "state.json"
        self._status = self.root / "status.json"

    # ---- 카드 ----
    def _known_ids(self) -> set[str]:
        if not self._index.exists():
            return set()
        out = set()
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001 — 손상 줄은 건너뜀
                continue
        return out

    def append_cards(self, cards: list[SectorCard]) -> int:
        known = self._known_ids()
        added = 0
        with self._index.open("a", encoding="utf-8") as f:
            for c in cards:
                if c.id in known:
                    continue
                known.add(c.id)
                if not c.ingested_at:
                    c.ingested_at = _dt.datetime.now(_dt.timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S")
                f.write(c.model_dump_json() + "\n")
                month = (c.ts[:7] or "unknown")
                mdir = self.root / "cards" / month
                mdir.mkdir(parents=True, exist_ok=True)
                (mdir / f"{_SAFE.sub('_', c.id)}.json").write_text(
                    c.model_dump_json(indent=1), encoding="utf-8")
                added += 1
        return added

    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   entity: str | None = None, limit: int = 500) -> list[SectorCard]:
        if not self._index.exists():
            return []
        cutoff = None
        if days is not None:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        out: list[SectorCard] = []
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                c = SectorCard.model_validate_json(line)
            except Exception:  # noqa: BLE001
                continue
            if cutoff and c.ts.replace("Z", "") < cutoff:
                continue
            if axis and c.axis != axis:
                continue
            if entity and entity not in c.entities:
                continue
            out.append(c)
        out.sort(key=lambda c: c.ts, reverse=True)
        return out[:limit]

    # ---- 지표 ----
    def _metric_path(self, metric: str) -> Path:
        return self.root / "metrics" / f"{_SAFE.sub('_', metric)}.jsonl"

    def append_observations(self, obs: list[MetricObservation]) -> int:
        added = 0
        by_metric: dict[str, list[MetricObservation]] = {}
        for o in obs:
            by_metric.setdefault(o.metric, []).append(o)
        for metric, rows in by_metric.items():
            p = self._metric_path(metric)
            seen = set()
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        seen.add(MetricObservation.model_validate_json(line).key())
                    except Exception:  # noqa: BLE001
                        continue
            with p.open("a", encoding="utf-8") as f:
                for o in rows:
                    if o.key() in seen:
                        continue
                    seen.add(o.key())
                    if not o.ingested_at:
                        o.ingested_at = _dt.datetime.now(_dt.timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S")
                    f.write(o.model_dump_json() + "\n")
                    added += 1
        return added

    def read_metric(self, metric: str, *, last_n: int = 90) -> list[MetricObservation]:
        p = self._metric_path(metric)
        if not p.exists():
            return []
        rows: list[MetricObservation] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(MetricObservation.model_validate_json(line))
            except Exception:  # noqa: BLE001
                continue
        rows.sort(key=lambda o: o.ts)
        return rows[-last_n:]

    # ---- 상태 ----
    def get_state(self, key: str):
        if not self._state.exists():
            return None
        try:
            return json.loads(self._state.read_text(encoding="utf-8")).get(key)
        except Exception:  # noqa: BLE001
            return None

    def set_states(self, mapping: dict) -> None:
        """다중 키를 임시파일+fsync+os.replace로 원자 저장(부분기록 방지)."""
        data = {}
        if self._state.exists():
            try:
                data = json.loads(self._state.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
        data.update(mapping)
        tmp = self._state.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._state)

    def set_state(self, key: str, value) -> None:
        self.set_states({key: value})

    # ---- raw 뉴스 코퍼스 (firehose 전량) ----
    def _raw_path(self, month: str) -> Path:
        return self.root / "news_raw" / f"{_SAFE.sub('_', month or 'unknown')}.jsonl"

    def append_raw_news(self, docs: list[RawNewsDoc]) -> int:
        """news_raw/<created_at[:7]>.jsonl에 id dedup(대상 파티션 기준) 후 신규만 append."""
        by_part: dict[str, list[RawNewsDoc]] = {}
        for d in docs:
            month = (d.created_at[:7] if d.created_at else "") or "unknown"
            by_part.setdefault(month, []).append(d)
        added = 0
        for month, rows in by_part.items():
            p = self._raw_path(month)
            seen: set[str] = set()
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        seen.add(json.loads(line)["id"])
                    except Exception:  # noqa: BLE001
                        continue
            with p.open("a", encoding="utf-8") as f:
                for d in rows:
                    if d.id in seen:
                        continue
                    seen.add(d.id)
                    if not d.ingested_at:
                        d.ingested_at = _dt.datetime.now(_dt.timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S")
                    f.write(d.model_dump_json() + "\n")
                    added += 1
                f.flush()
                os.fsync(f.fileno())
        return added

    def write_status(self, results: list[CollectorResult]) -> None:
        data = {}
        if self._status.exists():
            try:
                data = json.loads(self._status.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        for r in results:
            data[r.name] = {"status": r.status, "detail": r.detail,
                            "took_ms": r.took_ms, "at": now,
                            "items": len(r.items), "observations": len(r.observations),
                            "stats": r.stats}
        self._status.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")

    def read_status(self) -> dict:
        if not self._status.exists():
            return {}
        try:
            return json.loads(self._status.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
