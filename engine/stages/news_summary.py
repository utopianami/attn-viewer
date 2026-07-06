"""NEWS_SUMMARY — 큐레이션 통과 뉴스를 질문 관점에서 요약 (sonnet, low).

실패 시 raise — 오케스트레이터가 degrade 처리 (파이프라인 비차단).
큐레이션 뉴스가 없으면 None (요약할 것이 없음 ≠ 실패).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from contracts.packets import NewsSummaryLine, NewsSummaryPacket, PlanPacket, RaPacket
from providers import Role

_MAX_ITEMS = 15          # 입력 뉴스 상한 (유닛 균등)
_MAX_LINES = 6


class _Line(BaseModel):
    text: str
    url: str = ""


class _Summary(BaseModel):
    lines: list[_Line] = Field(default_factory=list)


_INSTR = """너는 금융 뉴스 브리핑 작성자다. 질문에 답하지 마라. 뉴스 요약만 한다.
- 질문과 직접 관련된 사실만 3~6줄. 한 줄 = 한 사실 + 해당 출처 url.
- 관련 없는 기사는 무시하라. 요약할 관련 기사가 없으면 lines를 빈 배열로.
- 숫자·날짜는 기사에 있는 그대로. 지어내지 마라."""


async def run_news_summary(plan: PlanPacket, ra: RaPacket,
                           overrides: dict | None = None) -> NewsSummaryPacket | None:
    pools = ra.curated_items()
    items = [n for lst in pools.values() for n in lst][:_MAX_ITEMS]
    if not items:
        return None

    lines = "\n".join(
        f"- [{n.published_at or '?'}] {n.title} — {n.summary[:200]} ({n.url})"
        for n in items)
    prompt = (f"[질문] {plan.standalone_question or plan.original_question}\n"
              f"[기준시점] {plan.knowledge_cutoff}\n[뉴스]\n{lines}")

    role = Role("news_summary", overrides)
    val: _Summary = await role.run(prompt, _INSTR, response_format=_Summary)
    return NewsSummaryPacket(
        lines=[NewsSummaryLine(text=l.text, url=l.url) for l in val.lines[:_MAX_LINES]],
        as_of=plan.knowledge_cutoff,
    )
