"""메모리 섹터 판정 (judge) — sonnet 배치 판정 → SectorCard 변환 (P1 Task 7).

LLM 예외는 그대로 raise — runner가 격리 (news_summary와 동일 계약).
"""
from __future__ import annotations

import re

from datetime import datetime, timezone

from pydantic import BaseModel

from providers import Role
from sector.contracts import RawNewsItem, SectorCard

_BATCH_SIZE = 40
_MAX_BATCHES = 2

_VALID_AXIS = {"A", "A_prime", "B", "C", "C0", "E", "P", "market"}
_VALID_DIRECTION = {"pos", "neg", "neutral", "mixed"}
_VALID_TIME_HORIZON = {"immediate", "next_quarter", "next_2_4_quarters"}
_VALID_EVENT_TYPE = {
    "demand_signal", "supply_signal", "price_signal", "earnings",
    "filing", "policy", "speaker", "product_policy", "market_reaction",
}
_VALID_MEMORY_SEGMENT = {"hbm", "dram", "nand", "mixed"}

_GRADE_B = {"reuters", "bloomberg", "연합", "로이터", "yna.co.kr", "wsj.com", "ft.com",
            "yonhap"}  # 도메인이 아니라 표기명으로 오는 소스(SaveTicker "reuters")까지 부분매칭


class _JudgeRow(BaseModel):
    idx: int
    relevant: bool
    axis: str = "B"
    edge: str = "B->A"
    event_type: str = "demand_signal"
    memory_segment: str = "mixed"
    direction: str = "neutral"
    magnitude: int = 1
    time_horizon: str = "immediate"
    speaker: str = ""
    interpreted_signal: str = ""


class _JudgeBatch(BaseModel):
    rows: list[_JudgeRow]


_INSTR = """너는 반도체 메모리 섹터의 인과 분석 판정자다. 관측 대상(A)은 메모리 생산 3사
— 삼성전자·SK하이닉스·마이크론 — 의 주가·실적이다.

인과 사슬 (스펙 §1-3, 각 단계가 시차를 두고 A에 도달):
C0(AI 사용량·침투: 제품 사용·기업 도입·개발자 채택)
 → C(AI 프론티어: OpenAI·Anthropic·구글·xAI의 토큰/컴퓨트 수요)
 → B(하이퍼스케일러/소비: MS·구글·아마존·메타·애플·오라클·GPU클라우드의 capex·서버구매)
 → GPU/ASIC(중간 노드: 엔비디아·AMD — 별도 축이 아니라 A_prime으로 태깅)
 → HBM/DRAM/NAND 수요 → A(메모리 3사 실적·주가)
보조 경로: A_prime(공급망/패키징: TSMC CoWoS·ASML 등 장비 — HBM 선행 신호),
E(전통 최종수요: 스마트폰·PC·일반서버 — 범용 D램·낸드의 절반을 결정),
P(정책/지정학: 수출통제·관세·보조금·CXMT 등 중국 공급 교란 — 외생 충격),
market(시장 전반: 지수·섹터 흐름·금리·환율).

direction·magnitude는 항상 A(메모리 3사) 주가 관점: 메모리 수요 증가·공급 타이트=pos,
수요 감소·공급 과잉·"더 적은 칩으로 같은 성능"(효율화)=neg.
위 사슬의 어떤 엣지에도 매핑 안 되면 → relevant=false."""

_ITEMS_HEADER = """
[판정 기준]
- axis: A/A_prime/B/C/C0/E/P/market (A=삼성전자·SK하이닉스·마이크론, A_prime=TSMC·장비·엔비디아 등 공급망/중간노드, B=하이퍼스케일러/클라우드, C=AI 프론티어(OpenAI 등), C0=AI 사용량·채택 신호, E=폰·PC 등 전통 수요, P=정책·지정학, market=시장 전반)
- direction: pos/neg/neutral/mixed (A 메모리 주가 방향)
- magnitude: 1(소)/2(중)/3(대)
- time_horizon: immediate/next_quarter/next_2_4_quarters
- event_type: demand_signal/supply_signal/price_signal/earnings/filing/policy/speaker/product_policy/market_reaction
- memory_segment: hbm/dram/nand/mixed
- speaker: 발언자 이름 (없으면 빈 문자열)
- interpreted_signal: A 메모리 관점 핵심 함의 한 줄

[뉴스 목록]
"""


def _source_grade(item: RawNewsItem) -> str:
    if item.grade_hint:
        return item.grade_hint
    src = item.source or ""
    if any(g in src for g in _GRADE_B):
        return "B"
    return "C"


def _validate_row(row: _JudgeRow) -> _JudgeRow:
    if row.axis not in _VALID_AXIS:
        row.axis = "B"
    if row.direction not in _VALID_DIRECTION:
        row.direction = "neutral"
    row.magnitude = max(1, min(3, row.magnitude))
    if row.time_horizon not in _VALID_TIME_HORIZON:
        row.time_horizon = "immediate"
    if row.event_type not in _VALID_EVENT_TYPE:
        row.event_type = "demand_signal"
    if row.memory_segment not in _VALID_MEMORY_SEGMENT:
        row.memory_segment = "mixed"
    return row


def _row_to_card(row: _JudgeRow, item: RawNewsItem) -> SectorCard:
    # ISO형("2026-…")이 아닌 published_at(brave age "2 hours ago" 등)은 버림 —
    # store가 ts[:7]로 월 파티션·날짜 필터를 하므로 (2026-07-06 라이브 발견)
    pub = item.published_at
    ts = pub if re.match(r"^\d{4}-\d{2}", pub or "") else datetime.now(timezone.utc).isoformat()
    speaker = row.speaker if row.speaker else None
    return SectorCard(
        id=item.id,
        ts=ts,
        axis=row.axis,  # type: ignore[arg-type]
        edge=row.edge,
        event_type=row.event_type,  # type: ignore[arg-type]
        memory_segment=row.memory_segment,  # type: ignore[arg-type]
        direction=row.direction,  # type: ignore[arg-type]
        magnitude=row.magnitude,
        time_horizon=row.time_horizon,  # type: ignore[arg-type]
        source_grade=_source_grade(item),  # type: ignore[arg-type]
        title=item.title,
        raw_quote=item.content[:500],
        interpreted_signal=row.interpreted_signal,
        speaker=speaker,
        url=item.url,
        source=item.source,
    )


async def _call_once(batch: list[RawNewsItem]) -> list[SectorCard]:
    items_text = "\n".join(
        f"idx={i} | {it.title} | {it.content[:400]} | {it.source}"
        for i, it in enumerate(batch)
    )
    prompt = _INSTR + _ITEMS_HEADER + items_text
    result: _JudgeBatch = await Role("sector_judge").run(
        prompt, instructions=_INSTR, response_format=_JudgeBatch
    )
    cards: list[SectorCard] = []
    for row in result.rows:
        if not row.relevant:
            continue
        if row.idx < 0 or row.idx >= len(batch):
            continue
        row = _validate_row(row)
        cards.append(_row_to_card(row, batch[row.idx]))
    return cards


async def judge_items(items: list[RawNewsItem]) -> list[SectorCard]:
    """아이템 목록을 배치 판정하고 SectorCard 목록을 반환한다.

    배치 최대 40건 × 2콜 = 80건. 초과분은 무시하되, 상한을 자르기 전에
    S/A급(공시 등)을 앞으로 정렬 — 수집 순서 때문에 뒤에 온 공시가 통째로
    버려지는 것을 방지 (2026-07-06 라이브 검증 발견).
    """
    _rank = {"S": 0, "A": 1}
    items = sorted(items, key=lambda it: _rank.get(it.grade_hint or "", 2))
    items = items[: _BATCH_SIZE * _MAX_BATCHES]
    cards: list[SectorCard] = []
    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start : start + _BATCH_SIZE]
        cards.extend(await _call_once(batch))
    return cards
