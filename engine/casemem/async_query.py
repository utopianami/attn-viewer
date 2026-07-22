"""async 질의 어댑터 (Plan 4-a) — 코어(query/rerank) 무수정 재사용.

미스매치: rerank의 llm_fn은 sync (str)->str, 엔진 LLM(Role.run)은 async.
해법: 프롬프트를 **미리 async로 호출**해 텍스트를 받아두고, 캡처된 텍스트를
돌려주는 클로저를 llm_fn으로 주입 → rerank_matches의 점수 블렌딩·폴백 로직
전부 재사용. sync 함수 안 asyncio.run() 금지(핸드오프 §1 — 이벤트루프 충돌).
"""
from __future__ import annotations

from casemem.contracts import CaseQueryResult
from casemem.query import query_case_memory
from casemem.rerank import build_rerank_prompt, rerank_matches


def _build_candidates(matches, episodes_by_id):
    """rerank_matches 내부와 동일한 후보 구성 — 프롬프트 일치 보장."""
    candidates = []
    for m in matches:
        ep = episodes_by_id.get(m.episode_id)
        label = ""
        ph_signals: list[str] = []
        if ep is not None:
            for p in ep.phases:
                if p.order == m.matched_phase_order:
                    label, ph_signals = p.label, p.identifying_signals
                    break
        candidates.append((m, label, ph_signals))
    return candidates


async def query_case_memory_async(store, *, signals: list[str], as_of: str,
                                  sector: str = "memory", k: int = 5,
                                  role=None) -> CaseQueryResult:
    """결정적 질의 + (role 주입 시) async LLM 구조 리랭크. never-raise."""
    res = query_case_memory(store, signals=signals, as_of=as_of, sector=sector, k=k)
    if role is None or not res.matches:
        return res

    episodes = store.read_episodes(sector=sector)
    by_id = {ep.id: ep for ep in episodes}
    prompt = build_rerank_prompt(signals, _build_candidates(res.matches, by_id))
    try:
        text = await role.run(prompt)               # async — 유일한 LLM 콜
    except Exception:  # noqa: BLE001 — never-raise, 표면 순서 폴백
        return res.model_copy(update={"rerank_used": True, "rerank_failed": True})

    # 캡처 텍스트를 돌려주는 sync 클로저 → 코어 rerank 로직(파싱·블렌드·폴백) 재사용
    matches, failed = rerank_matches(res.matches, signals, by_id,
                                     lambda _prompt: text)
    return res.model_copy(update={"matches": matches, "rerank_used": True,
                                  "rerank_failed": failed})
