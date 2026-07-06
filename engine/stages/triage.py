"""TRIAGE 스테이지 — 입구 라우팅 (deep / followup / smalltalk).

첫 질문이나 새 종목·새 데이터는 deep. 직전 답변을 참조하는 가벼운 후속은 followup
(이전 raw 재사용). 인사·잡담·순수 재포맷은 smalltalk.

빠르고 싸게(gpt-5.5-mini, ~1s). `/deep` 접두어는 LLM 없이 무조건 deep 강제.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from providers import Role

DEEP_PREFIX = re.compile(r"^\s*/deep\b\s*", re.IGNORECASE)


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str = "deep"              # deep | followup | smalltalk
    needs_fresh_data: bool = True    # followup이어도 새 데이터 필요하면 deep로 승격
    reason: str = ""


class _TriageLLM(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str
    needs_fresh_data: bool
    reason: str = ""


_INSTR = """너는 금융 채팅의 입구 분류기다. 이번 메시지를 대화 이력과 함께 보고 경로를 정한다.
가장 중요한 원칙: **이번 메시지가 직전 답변에서 이미 언급된 것을 가리키는지** 먼저 확인하라.
직전 답변에 나온 회사·사건·용어를 되묻는 것이면 followup이다 (새 주제처럼 보여도).

route:
- followup: 직전 답변을 참조하는 후속. 재설명·재포맷·부분 확대, 그리고
  **직전 답변에서 언급된 회사/사건/원인을 더 물어보는 것**.
  (예: "그거 왜 그래?", "더 자세히", "표로 정리해줘", "3번 무슨 뜻?")
  (★핵심 예: 직전 답변이 "삼성·하이닉스 하락은 메타 클라우드 우려 때문"이라 했고
   사용자가 "메타 클라우드 소식은?"이라 물으면 → 이건 그 원인을 더 파는 followup이다.
   절대 "메타의 일반 클라우드 뉴스"로 오해하지 마라. 직전 맥락에 붙여 해석하라.)
- deep: 직전 답변과 무관한 새 금융 질문. 새 종목/새 주제.
  (예: "삼성전기 어때?", "SK하이닉스 살만해?", "그럼 하이닉스는?" ← 직전과 다른 새 종목)
- smalltalk: 인사·감사·잡담·시스템 질문. 금융 분석 불필요.
  (예: "고마워", "ㅇㅋ", "너 누구야?", "안녕")

needs_fresh_data: 이번 답에 새 시세/뉴스 수집이 필요하면 true.
  - 직전 답변에 이미 있는 내용을 되묻는 것이면 false (이전 자료 재사용).
  - 하지만 "그 원인에 대한 최신/구체 뉴스"를 물으면, 이전 답변엔 헤드라인만 있었으므로
    보강 수집이 필요할 수 있다 → 애매하면 true (그러면 그 맥락으로 deep 검색).
  - reason에 "직전 답변의 무엇을 가리키는지"를 반드시 적어라.

이력이 없으면(첫 메시지) 거의 항상 deep 또는 smalltalk다."""


async def run_triage(question: str, history: list | None = None,
                     overrides: dict | None = None) -> tuple[TriageResult, str]:
    """(TriageResult, 정제된 질문) 반환. /deep 접두어면 제거 후 무조건 deep."""
    if DEEP_PREFIX.match(question):
        stripped = DEEP_PREFIX.sub("", question).strip()
        return TriageResult(route="deep", needs_fresh_data=True, reason="/deep 강제"), stripped

    # 이력 없으면 LLM 없이 빠른 판정 (첫 질문 = deep, 아주 짧으면 smalltalk 후보만 LLM)
    if not history:
        if len(question.strip()) <= 6 and not re.search(r"[가-힣]{2,}(전자|전기|하이닉스|증권|화학|바이오|반도체)", question):
            pass  # 짧아도 종목명일 수 있어 LLM에 맡김
        # 첫 질문은 대체로 deep — 단 인사류만 거르려 경량 LLM 1콜
    ctx = f"[이번 메시지] {question}"
    if history:
        turns = []
        for t in history[-4:]:
            role = t.get("role")
            content = str(t.get("content", ""))[:250]
            turns.append(f"- {role}: {content}")
        ctx = "[대화 이력]\n" + "\n".join(turns) + f"\n\n[이번 메시지] {question}"

    role = Role("plan_extract", overrides)  # mini
    try:
        r: _TriageLLM = await role.run(ctx, _INSTR, response_format=_TriageLLM)
        route = r.route if r.route in {"deep", "followup", "smalltalk"} else "deep"
        return TriageResult(route=route, needs_fresh_data=bool(r.needs_fresh_data), reason=r.reason), question
    except Exception:
        return TriageResult(route="deep", needs_fresh_data=True, reason="triage 실패→deep"), question
