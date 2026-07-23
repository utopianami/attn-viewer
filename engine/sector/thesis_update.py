"""테제(Thesis) updater 파이프 — pre-LLM 게이트·재가드·방향 집계·role 배선 (2부 T5).

순서 계약(바인딩 — 테스트가 sentinel로 강제):
1. required_inputs 게이트(LLM 호출 전) — freshness가 "fresh"(전체 충족)일 때만
   통과시킨다. "degraded"(일부만 충족)·"stale"(전무)은 전부 None(2부 T9 블로커 1
   — codex 재검토 판정: degraded 통과는 fail-closed 위반이며 정답은 fixture
   보정이지 게이트 완화가 아니다).
2. 입력 조립: 이 시점에 seed의 required_inputs 전체를 `resolve_required_inputs`로
   단 한 번 해석한다(metric 이름당 store 읽기 1회 — 2부 T9 블로커 4 TOCTOU 방지).
   fresh 게이트는 meta_filter 매칭 존재/나이만 보므로, 다중 그룹 모호성(핀 필터
   없음)으로 resolver가 None을 낸 required_input이 하나라도 있으면 여기서
   fail-closed로 None을 반환한다(LLM 호출 전 — 2부 T9 블로커 2 잔여 1, 이전엔
   조용히 드롭 후 LLM 호출이라 fail-open이었음). 전부 해석돼야 다음 단계로
   간다. 그 결과가 (a) prompt용 지표 요약(meta·observation_id 포함해 동일
   metric 이름의 여러 항목을 구분), (b) InputSnapshot.metric_observation_ids,
   (c) 최종 key_metrics의 유일한 근원이다 — LLM·verifier 이후 다시 읽지 않는다.
   카드는 now 기준 최근 14일(selectors entities/segments/event_types 필터·
   eligible_card만)을 별도로 읽는다. 제공한 전체 card_id·metric_observation_id를
   InputSnapshot에 정확히 기록한다(r2-B8).
3. 제안 LLM(thesis_updater role) — assessment는 절대 요청하지 않는다(B2).
4. build_evidence로 Evidence 재구성 → statement당 evidence를 card_id로 dedup
   (2부 T9 블로커 6a — 같은 카드 중복 인용 방지) → filter_statements →
   verify_statements(VerificationFailed → None) → filter_statements 재실행
   (B3 — verifier가 근거를 솎아낸 뒤 독립성 재검).
5. 잔여 statements 0 → None. assessment는 코드가 verifier 방향을 집계해서 정한다.
   최종 key_metrics는 2단계에서 조립해 둔 결과 중 LLM이 고른 key_metric_names에
   속하는 항목들이다(같은 이름이 여러 required_inputs에 있으면 전부 포함 — 블로커 2c).
6. ThesisRevision 조립 → tstore.append(False면 "unchanged").
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from providers import Role
from sector.contracts import SectorCard
from sector.store import SectorStore
from sector.thesis_contracts import (
    InputSnapshot,
    KeyMetric,
    RequiredInput,
    Selectors,
    Statement,
    ThesisRevision,
)
from sector.thesis_guard import build_evidence, eligible_card, filter_statements, resolve_required_inputs
from sector.thesis_seeds import SEED_THESES
from sector.thesis_store import ThesisStore, freshness_for_inputs
from sector.thesis_verify import VerificationFailed, verify_statements

# SectorStore/ThesisStore 운영 루트 — report_pipeline.py의 _ROOT 패턴을 그대로 미러링
# (동일 storage/rag/memory_sector). theses.jsonl은 index.jsonl·cards/·metrics/와
# 나란히 같은 루트에 둔다(테제도 "섹터 데이터"의 일부라는 결정 — 별도 서브디렉터리를
# 만들 이유가 없음, ThesisStore(root)가 root에 직접 theses.jsonl을 쓰는 것과 일치).
_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "memory_sector"
_WINDOW_DAYS = 14


# ---- 제안 LLM 구조화 출력 (assessment 없음 — B2) ----------------------------


class _ProposalEvidence(BaseModel):
    card_id: str
    quote: str


class _ProposalStatement(BaseModel):
    text: str
    evidence: list[_ProposalEvidence] = []


class _ProposalOut(BaseModel):
    statements: list[_ProposalStatement] = []
    key_metric_names: list[str] = []


_PROPOSAL_INSTRUCTIONS = (
    "너는 금융/반도체 섹터 테제(가설)를 최근 카드·지표 근거로 갱신하는 애널리스트다. "
    "아래 제공된 카드·지표 요약에 없는 사실은 절대 지어내지 마라. statements 각각에는 "
    "evidence(card_id·quote)를 반드시 포함하고, quote는 해당 card_id의 raw_quote 또는 "
    "title에서 그대로 발췌한 부분 문자열이어야 한다(가공·요약 금지). assessment(강화/"
    "약화 여부)는 절대 판단하지 마라 — 그건 이 파이프라인의 별도 검증 단계가 정한다."
)


# ---- 입력 조립 --------------------------------------------------------------


def _parse_card_ts(ts: str) -> _dt.datetime | None:
    try:
        parsed = _dt.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _selector_matches(card: SectorCard, selectors: dict) -> bool:
    """entities overlap는 hard 필터(entities 셀렉터가 있는데 하나도 안 겹치면 탈락).

    segments/event_types는 지정돼 있으면 둘 중 하나만 맞아도 통과시키는 soft
    OR 필터로 뒀다 — SectorCard.memory_segment/event_type은 판정기 기본값이
    "mixed"/"demand_signal"로 흔히 남아(세밀한 신호가 아님) entities만큼 믿을 수
    있는 축이 아니기 때문에, AND로 묶으면 실제로 관련 있는 카드까지 과도하게
    걸러진다(2부 T5 설계 결정, 테스트로 확인 — 문서화 필요 사항). "mixed"는
    세그먼트 무관을 뜻하는 값이라 세그먼트 셀렉터가 지정돼 있어도 항상 통과.
    """
    entities = set(selectors.get("entities") or [])
    if entities and not (set(card.entities) & entities):
        return False
    segments = selectors.get("segments") or []
    event_types = selectors.get("event_types") or []
    if not segments and not event_types:
        return True
    seg_ok = bool(segments) and (card.memory_segment in segments or card.memory_segment == "mixed")
    evt_ok = bool(event_types) and (card.event_type in event_types)
    return seg_ok or evt_ok


def _assemble_cards(
    seed: dict, store: SectorStore, now: _dt.datetime
) -> dict[str, SectorCard]:
    """now 기준 최근 14일·selectors·eligible_card로 걸러진 카드 dict."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=_WINDOW_DAYS)
    selectors = seed["selectors"]

    all_cards = store.read_cards(days=None, limit=None)
    cards_by_id: dict[str, SectorCard] = {}
    for c in all_cards:
        ts = _parse_card_ts(c.ts)
        if ts is None or ts < cutoff or ts > now:
            continue
        if not eligible_card(c):
            continue
        if not _selector_matches(c, selectors):
            continue
        cards_by_id[c.id] = c
    return cards_by_id


def _build_proposal_prompt(seed: dict, cards: dict[str, SectorCard], kms: list[KeyMetric]) -> str:
    lines = [f"[핵심 주장(seed claim)] {seed['claim']}", "", "[최근 14일 카드]"]
    for c in cards.values():
        lines.append(json.dumps({
            "card_id": c.id, "title": c.title,
            "raw_quote": (c.raw_quote or "")[:200], "url": c.url,
        }, ensure_ascii=False))
    lines.append("")
    lines.append("[지표 요약]")
    for km in kms:
        # meta(item/model/token 등 구분자)와 observation_id를 반드시 포함한다 —
        # 같은 metric 이름을 쓰는 여러 required_inputs(HBM/DRAM 가격, 3사 CAPEX
        # 등)가 값만 나열되면 LLM이 서로 구분할 수 없다(2부 T9 블로커 2 잔여 1).
        lines.append(json.dumps({
            "metric": km.metric, "value": km.value, "unit": km.unit, "ts": km.ts,
            "meta": km.meta, "observation_id": km.observation_id,
        }, ensure_ascii=False))
    return "\n".join(lines)


def _aggregate_assessment(directions: dict[str, str]) -> Literal["strengthening", "weakening", "mixed"]:
    values = set(directions.values())
    if values == {"supports"}:
        return "strengthening"
    if values == {"contradicts"}:
        return "weakening"
    return "mixed"


# ---- 코어 파이프 ------------------------------------------------------------


async def _run_one(
    seed: dict, store: SectorStore, tstore: ThesisStore, updater_role, verifier_role,
    now: _dt.datetime,
) -> tuple[ThesisRevision | None, str]:
    reqs = [RequiredInput(**ri) for ri in seed.get("required_inputs", [])]

    # metric 이름당 정확히 1회만 읽는다(2부 T9 블로커 4 — 게이트·조립·최종
    # key_metrics가 전부 이 캐시 하나를 공유; 이후 store를 다시 읽지 않는다).
    metric_names = sorted({ri["metric"] for ri in seed.get("required_inputs", [])})
    rows_by_metric = {name: store.read_metric(name, last_n=1_000_000) for name in metric_names}

    # 1) required_inputs 게이트 — LLM 호출 전. "fresh"(전체 충족)일 때만 통과시킨다
    #    (degraded·stale은 전부 차단 — 위 모듈 docstring 참조, 2부 T9 블로커 1).
    gate = freshness_for_inputs(reqs, store, now, rows_by_metric=rows_by_metric)
    if gate != "fresh":
        return None, f"skipped: required_inputs {gate}"

    # 2) 입력 조립 — required_inputs 전체를 한 번에 해석(첫 read 그대로 재사용,
    #    이 결과가 prompt·InputSnapshot·최종 key_metrics의 유일한 근원 — 블로커 2/4)
    resolved = resolve_required_inputs(seed, store, now, rows_by_metric=rows_by_metric)
    # fresh 게이트(freshness_for_inputs)는 meta_filter 매칭 존재/나이만 보고 그룹
    # 모호성은 보지 않는다 — resolver가 다중 그룹(핀 필터 없음)·유효 관측 0으로
    # None을 낸 required_input이 하나라도 있으면 여기서 fail-closed로 멈춘다
    # (2부 T9 블로커 2 잔여 1 — 이전엔 조용히 드롭하고 LLM을 호출해 fail-open이었음).
    unresolved = [ri["metric"] for ri, km in resolved if km is None]
    if unresolved:
        return None, f"skipped: required_input unresolved: {unresolved[0]}"
    kms_summary = [km for _ri, km in resolved if km is not None]
    cards_by_id = _assemble_cards(seed, store, now)
    card_ids_snapshot = sorted(cards_by_id.keys())
    obs_ids_snapshot = sorted({km.observation_id for km in kms_summary})

    # 3) 제안 LLM — assessment 없음(B2)
    prompt = _build_proposal_prompt(seed, cards_by_id, kms_summary)
    proposal: _ProposalOut = await updater_role.run(
        prompt, instructions=_PROPOSAL_INSTRUCTIONS, response_format=_ProposalOut)

    # 4) build_evidence 재구성(statement당 card_id로 dedup — 블로커 6a)
    #    → filter_statements → verify_statements → 재filter
    statements: list[Statement] = []
    for i, ps in enumerate(proposal.statements, start=1):
        sid = f"s{i}"
        supporting = []
        seen_card_ids: set[str] = set()
        for pe in ps.evidence:
            if pe.card_id in seen_card_ids:
                continue  # 같은 statement 내 같은 카드 중복 인용 — 첫 건만 유지(블로커 6a)
            card = cards_by_id.get(pe.card_id)
            if card is None:
                continue  # 조립 대상에 없는 card_id — 신뢰 안 함(B4)
            ev = build_evidence(card, pe.quote)
            if ev is None:
                continue
            supporting.append(ev)
            seen_card_ids.add(pe.card_id)
        statements.append(Statement(statement_id=sid, text=ps.text, supporting=supporting))

    kept, _dropped1 = filter_statements(statements, cards_by_id)
    if not kept:
        return None, "skipped: 구조 필터(filter_statements) 통과 statement 0개"

    try:
        verified, directions, _reasons = await verify_statements(kept, seed["claim"], verifier_role)
    except VerificationFailed as exc:
        return None, f"skipped: 검증 실패(VerificationFailed) — {exc}"

    if not verified:
        return None, "skipped: 교차 검증 통과 statement 0개"

    reverified, _dropped2 = filter_statements(verified, cards_by_id)  # B3 — 재가드
    if not reverified:
        return None, "skipped: 검증 후 재가드 통과 statement 0개"

    # 5) assessment — 코드가 잔여 statement들의 verifier 방향을 집계
    kept_ids = {st.statement_id for st in reverified}
    dirs = {sid: d for sid, d in directions.items() if sid in kept_ids}
    assessment = _aggregate_assessment(dirs)

    # 최종 key_metrics — 2단계에서 조립해 둔 SAME 결과에서 LLM이 고른 이름만 채택
    # (재조회 없음 — 블로커 4. 같은 이름이 여러 required_inputs에 있으면 전부 포함 — 블로커 2c)
    key_names = set(proposal.key_metric_names)
    kms = [km for ri, km in resolved if km is not None and ri["metric"] in key_names]

    # 6) ThesisRevision 조립 → append
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    rev = ThesisRevision(
        id=seed["id"], revision_id=f"{seed['id']}@{now_str}",
        claim=seed["claim"], axis=seed["axis"],
        selectors=Selectors(**seed["selectors"]), priority=seed["priority"],
        assessment=assessment, statements=reverified, key_metrics=kms,
        required_inputs=reqs, valid_from=now_str,
        input_snapshot=InputSnapshot(card_ids=card_ids_snapshot,
                                     metric_observation_ids=obs_ids_snapshot),
        updated_at=now_str,
    )
    appended = tstore.append(rev)
    return rev, ("updated" if appended else "unchanged")


async def update_thesis(
    seed: dict, store: SectorStore, tstore: ThesisStore, updater_role, verifier_role,
    now: _dt.datetime,
) -> ThesisRevision | None:
    rev, _status = await _run_one(seed, store, tstore, updater_role, verifier_role, now)
    return rev


async def update_all(
    store: SectorStore, tstore: ThesisStore | None = None, only: list[str] | None = None,
    role_factory=None,
) -> dict[str, str]:
    """SEED_THESES(only로 필터)를 순회하며 시드별로 격리해 갱신한다."""
    if tstore is None:
        tstore = ThesisStore(_ROOT)
    if role_factory is None:
        role_factory = lambda name: Role(name)  # noqa: E731
    updater_role = role_factory("thesis_updater")
    verifier_role = role_factory("thesis_verifier")

    now = _dt.datetime.now(_dt.timezone.utc)
    seeds = [s for s in SEED_THESES if not only or s["id"] in only]
    statuses: dict[str, str] = {}
    for seed in seeds:
        try:
            _rev, status = await _run_one(seed, store, tstore, updater_role, verifier_role, now)
        except Exception as exc:  # noqa: BLE001 — 시드별 격리(원칙 2 never-block)
            status = f"error: {type(exc).__name__}: {exc}"
        statuses[seed["id"]] = status
    return statuses


# ---- CLI ---------------------------------------------------------------


def _get_store() -> SectorStore:
    return SectorStore(_ROOT)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None,
                    help="처리할 테제 id (반복 가능, 예: --only hbm-tightness)")
    args = ap.parse_args(argv)
    store = _get_store()
    statuses = asyncio.run(update_all(store, only=args.only))
    print(json.dumps(statuses, ensure_ascii=False))
    return 1 if any("error" in v for v in statuses.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
