"""메모리 섹터 판정 (judge) — sonnet 배치 판정 → SectorCard 변환 (P1 Task 7).

LLM 예외는 그대로 raise — runner가 격리 (news_summary와 동일 계약).
"""
from __future__ import annotations

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


_INSTR = """너는 반도체 메모리 주가 인과 분석 판정자다.

인과 사슬: C0(원자재·장비) → C(DRAM/NAND 공급자) → B(GPU/AI 가속기, 엔비디아 등) → GPU(AI 데이터센터 수요) → A(삼성전자 메모리 사업)
E 축: 거시경제·금리·환율 → A 수익
P 축: 정책·무역 규제 → A 메모리

direction·axis·magnitude는 항상 A(삼성전자 메모리 주가) 관점으로 판정하라.
엣지 매핑 불가 → relevant=false."""

_ITEMS_HEADER = """
[판정 기준]
- axis: A/A_prime/B/C/C0/E/P/market (A=삼성전자 직접, A_prime=하이닉스, B=GPU·AI HW, C=DRAM·NAND 공급자, C0=장비·소재, E=거시, P=정책·규제, market=시장 전반)
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
    ts = item.published_at or datetime.now(timezone.utc).isoformat()
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
