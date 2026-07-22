"""f1 관련성(카드 무조건 통과) → f2 중요도 → f3 이벤트 클러스터(단일 콜).

전부 never-raise·StageResult 반환. judge의 raise/80캡/grade_hint는 상속하지 않음(스펙 v3).
f1/f2 배치 실패는 fail-closed(해당 배치 drop+사유), f3 실패는 fail-open(1건=1클러스터 —
dedup만 잃고 재료는 보존). 중복 idx는 첫 행 유지."""
from __future__ import annotations

import time

from pydantic import BaseModel

from sector.report_contracts import EventCluster, EvidenceRef, StageIO, StageResult

_BATCH = 40
_CLUSTER_CAP = 200


class _RelRow(BaseModel):
    idx: int
    relevant: bool = False
    reason: str = ""


class _RelBatch(BaseModel):
    rows: list[_RelRow]


class _ImpRow(BaseModel):
    idx: int
    impact: str = "하"
    keep: bool = False
    reason: str = ""


class _ImpBatch(BaseModel):
    rows: list[_ImpRow]


class _ClusterRow(BaseModel):
    cluster_id: str
    title: str
    member_idxs: list[int] = []
    axis: str = "B"
    direction: str = "neutral"


class _ClusterOut(BaseModel):
    clusters: list[_ClusterRow]


def _news_ref(d) -> EvidenceRef:
    return EvidenceRef(kind="news", id=d.id, title=d.title,
                       ts=getattr(d, "created_at", ""), source=getattr(d, "source", ""),
                       url=getattr(d, "url", ""),
                       excerpt=(getattr(d, "content", "") or "")[:280])


def _card_ref(c) -> EvidenceRef:
    return EvidenceRef(kind="card", id=c.id, title=c.title, ts=c.ts,
                       source=getattr(c, "source", ""), url=getattr(c, "url", ""),
                       excerpt=getattr(c, "interpreted_signal", "")
                       or getattr(c, "raw_quote", ""))


def _first_by_idx(rows) -> dict:
    out: dict[int, object] = {}
    for r in rows:
        if r.idx not in out:                     # 중복 idx → 첫 행 유지(스펙)
            out[r.idx] = r
    return out


async def filter_relevance(raw_news, cards, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f1", label="1차 필터 — 관련성",
                 in_count=len(raw_news) + len(cards))
    kept: list[EvidenceRef] = [_card_ref(c) for c in cards]    # 판정본 무조건 통과
    err = None
    for start in range(0, len(raw_news), _BATCH):
        batch = raw_news[start:start + _BATCH]
        prompt = "\n".join(f"{i}. {d.title}" for i, d in enumerate(batch))
        try:
            res = await role.run(
                prompt,
                instructions="메모리 반도체 밸류체인(수요·공급·가격·재고·AI수요·매크로 채널) "
                             "관련만 relevant=true.",
                response_format=_RelBatch, effort="low")
            rows = _first_by_idx(res.rows)
            for i, d in enumerate(batch):
                r = rows.get(i)
                if r is not None and r.relevant:
                    kept.append(_news_ref(d))
                else:
                    io.dropped.append({"title": d.title,
                                       "reason": (r.reason if r else "판정 누락") or "무관"})
        except Exception as exc:  # noqa: BLE001 — 배치 fail-closed
            err = str(exc)
            for d in batch:
                io.dropped.append({"title": d.title, "reason": f"llm 실패: {exc}"})
    io.out_count = len(kept)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=kept, io=io, error=err)


async def filter_importance(evidence, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f2", label="2차 필터 — 중요도", in_count=len(evidence))
    kept: list[EvidenceRef] = []
    err = None
    for start in range(0, len(evidence), _BATCH):
        batch = evidence[start:start + _BATCH]
        prompt = "\n".join(f"{i}. [{e.kind}] {e.title}" for i, e in enumerate(batch))
        try:
            res = await role.run(
                prompt,
                instructions="12시간 시황 판단에 임팩트 있는 항목만 keep=true. impact=상|중|하.",
                response_format=_ImpBatch, effort="low")
            rows = _first_by_idx(res.rows)
            for i, e in enumerate(batch):
                r = rows.get(i)
                if r is not None and r.keep:
                    kept.append(e)
                else:
                    io.dropped.append({"title": e.title,
                                       "reason": (r.reason if r else "판정 누락") or "임팩트 낮음"})
        except Exception as exc:  # noqa: BLE001 — 배치 fail-closed
            err = str(exc)
            for e in batch:
                io.dropped.append({"title": e.title, "reason": f"llm 실패: {exc}"})
    io.out_count = len(kept)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=kept, io=io, error=err)


async def cluster_events(evidence, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f3", label="3차 필터 — 이벤트 dedup", in_count=len(evidence))
    items = evidence[:_CLUSTER_CAP]
    if len(evidence) > _CLUSTER_CAP:
        io.note = f"클러스터 입력 캡 {_CLUSTER_CAP}건(원 {len(evidence)}건) — 초과분 미클러스터"
    try:
        # 단일 글로벌 호출 — 배치 분할하면 교차배치 중복 이벤트가 못 묶임
        prompt = "\n".join(f"{i}. {e.title}" for i, e in enumerate(items))
        res = await role.run(
            prompt,
            instructions="같은 사건을 다룬 항목들을 하나의 이벤트로 묶어라. "
                         "모든 idx는 정확히 한 클러스터에.",
            response_format=_ClusterOut, effort="low")
        used: set[int] = set()
        clusters: list[EventCluster] = []
        for row in res.clusters:
            members = [items[i] for i in row.member_idxs
                       if 0 <= i < len(items) and i not in used]
            used.update(i for i in row.member_idxs if 0 <= i < len(items))
            if members:
                clusters.append(EventCluster(cluster_id=row.cluster_id, title=row.title,
                                             axis=row.axis, direction=row.direction,
                                             members=members))
        for i, e in enumerate(items):            # 누락 idx → 단독 클러스터(무성 누락 금지)
            if i not in used:
                clusters.append(EventCluster(cluster_id=f"solo-{e.id}", title=e.title,
                                             members=[e]))
        io.out_count = len(clusters)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=clusters, io=io, error=None)
    except Exception as exc:  # noqa: BLE001 — fail-open: 1건=1클러스터(재료 보존)
        clusters = [EventCluster(cluster_id=f"solo-{e.id}", title=e.title, members=[e])
                    for e in items]
        io.out_count = len(clusters)
        io.note = (io.note + " · " if io.note else "") + "클러스터 LLM 실패 → 1건=1클러스터"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=clusters, io=io, error=str(exc))
