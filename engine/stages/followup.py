"""followup / smalltalk 경로 — deep 파이프라인을 타지 않는 경량 응답.

followup: 직전 답변 + 이미 수집한 raw(매크로·트렌드·시세·뉴스·claims)를 재사용해 합성 1콜.
smalltalk: 짧은 대화 응답 1콜.
둘 다 새 데이터 수집·검증 파이프라인 없음 (빠름·쌈).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from providers import Role


class _FuCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answerable: bool = True
    search_query: str = ""   # 답 불가 시 부족한 사실을 겨냥한 한국어 검색어 1개

_FOLLOWUP_INSTR = """너는 금융 QA의 후속 응답이다. 사용자가 방금 받은 답변에 대해 이어서 묻고 있다.
[직전 답변]과 [수집된 데이터]를 근거로 답하라. 새 사실을 지어내지 마라 — 이미 있는 것만 쓴다.
재설명·재포맷·부분 확대 요청이면 그에 맞게. 데이터에 없는 걸 물으면 "추가 조회가 필요하다"고 밝혀라.
한국어, 결론부터, 마크다운."""

_SMALLTALK_INSTR = """너는 금융 리서치 채팅 어시스턴트다. 짧고 자연스럽게 답하라.
금융 분석 요청이 아니면 간결히 응대하고, 필요하면 "종목·주제를 물어보시면 분석해 드립니다"로 안내하라."""


def _reuse_context(history: list | None) -> tuple[str, dict]:
    """직전 assistant 턴의 답변 + raw_layers를 꺼낸다."""
    if not history:
        return "", {}
    for t in reversed(history):
        if t.get("role") == "assistant":
            return str(t.get("content", "")), (t.get("raw_layers") or {})
    return "", {}


def _render_raw(raw: dict) -> str:
    parts = []
    if "macro" in raw:
        m = raw["macro"]
        parts.append("[매크로] " + ", ".join(
            f"{k} {v.get('day_pct')}%" for k, v in m.items() if isinstance(v, dict) and "day_pct" in v))
    if "price" in raw and raw["price"].get("quotes"):
        for q in raw["price"]["quotes"]:
            if "error" not in q:
                parts.append(f"[시세] {q.get('token')}: {q.get('last')} ({q.get('day_pct',0):+.1f}%)")
    if "toss_trend" in raw and raw["toss_trend"].get("trends"):
        parts.append("[트렌드] " + "; ".join(t.get("label", "") for t in raw["toss_trend"]["trends"][:5]))
    if "ra_x" in raw and raw["ra_x"].get("items"):
        parts.append("[뉴스] " + " / ".join(n.get("title", "") for n in raw["ra_x"]["items"][:6]))
    if "claims" in raw and raw["claims"].get("claims"):
        parts.append("[주장] " + " · ".join(c.get("text", "")[:60] for c in raw["claims"]["claims"][:8]))
    return "\n".join(parts)


async def run_followup(question: str, history: list | None = None,
                       overrides: dict | None = None) -> str:
    prev_answer, raw = _reuse_context(history)
    ctx = f"[직전 답변]\n{prev_answer[:2500]}\n\n[수집된 데이터]\n{_render_raw(raw) or '(재사용 가능한 데이터 없음)'}\n\n[이번 질문] {question}"

    # P3-4 프리패스 — 직전 raw로 답 가능한가 (mini 1콜). 불가면 brave 1쿼리만 표적 검색
    # (grok 불경유 — followup은 경량 유지, 지연 +2~4s 한도)
    try:
        check: _FuCheck = await Role("plan_extract", overrides).run(
            ctx[:6000],
            "위 [직전 답변]과 [수집된 데이터]만으로 [이번 질문]에 답할 수 있는지 판정하라.\n"
            "- 재설명·재포맷·부분 확대 요청이면 answerable=true.\n"
            "- 데이터에 없는 새 사실(다른 종목·최신 수치·새 사건)을 물으면 answerable=false로 하고 "
            "부족한 사실 하나를 겨냥한 한국어 뉴스 검색어 1개를 search_query에 적어라.",
            response_format=_FuCheck,
        )
        if not check.answerable and check.search_query.strip():
            import httpx

            from stages.ra_external import _search_fallback
            async with httpx.AsyncClient(timeout=8) as hc:  # 경량 경로 — 최악 지연 상한
                rows = await _search_fallback(check.search_query.strip(), count=5,
                                              freshness="pw", client=hc,
                                              geo={"country": "kr", "search_lang": "ko"})
            if rows:
                lines = "\n".join(
                    f"- {r.get('title', '')} ({r.get('age', '?')}): {r.get('description', '')[:150]}"
                    for r in rows[:5])
                ctx += (f"\n\n[추가 검색 — '{check.search_query.strip()}']\n{lines}\n"
                        "(위 추가 검색 결과는 검증 파이프라인을 거치지 않았다 — 인용 시 출처·시점을 밝혀라)")
    except Exception:
        pass  # 프리패스 실패 = 기존 경로 그대로

    role = Role("synthesizer", overrides)
    return await role.run(ctx, _FOLLOWUP_INSTR)


async def run_smalltalk(question: str, history: list | None = None,
                        overrides: dict | None = None) -> str:
    ctx = f"[메시지] {question}"
    role = Role("plan_extract", overrides)  # mini — 가볍게
    return await role.run(ctx, _SMALLTALK_INSTR)
