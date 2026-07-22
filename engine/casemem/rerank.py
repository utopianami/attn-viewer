"""LLM 구조 리랭크 — 표면 후보를 signal 조합의 구조적 정합성으로 재정렬(설계 §5-5).
LLM 프로바이더 비의존: (prompt:str)->str 콜러블 주입. never-raise 폴백."""
from __future__ import annotations

import json
import re
from typing import Callable

from casemem.contracts import CaseEpisode, CaseMatch

LlmFn = Callable[[str], str]

_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def build_rerank_prompt(signals: list[str],
                        candidates: list[tuple[CaseMatch, str, list[str]]]) -> str:
    lines = [
        "너는 메모리 반도체 사이클 분석가다. 오늘 관측된 signal 집합과, 과거 사례의 "
        "후보 국면들이 주어진다. 각 후보에 대해 '오늘 signal 조합이 이 국면의 구조와 "
        "얼마나 정합적인가'를 0~1로 채점하라(표면 단어 겹침이 아니라 구조적 의미).",
        "",
        "오늘 signal:",
    ]
    for s in signals:
        lines.append(f"  - {s}")
    lines.append("")
    lines.append("후보 국면:")
    for i, (_m, label, ph_signals) in enumerate(candidates):
        lines.append(f"  [{i}] 국면={label}")
        for ps in ph_signals:
            lines.append(f"        · {ps}")
    lines += [
        "",
        '오직 JSON 배열만 출력: [{"i":<index>,"s":<0~1 점수>}, ...]. 설명 금지.',
    ]
    return "\n".join(lines)


def parse_rerank_response(text: str, n: int) -> dict[int, float]:
    if not isinstance(text, str) or not text:   # 비문자열(오작동 llm_fn) 방어 — never-raise
        return {}
    m = _ARRAY.search(text)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[int, float] = {}
    if not isinstance(arr, list):
        return {}
    for item in arr:
        try:
            i = int(item["i"])
            s = float(item["s"])
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < n and 0.0 <= s <= 1.0:
            out[i] = s
    return out


def rerank_matches(matches: list[CaseMatch], signals: list[str],
                   episodes_by_id: dict[str, CaseEpisode], llm_fn: LlmFn,
                   *, ws: float = 0.4, wl: float = 0.6) -> tuple[list[CaseMatch], bool]:
    """표면 후보를 구조 점수로 재정렬. 반환 (matches, failed).
    llm_fn 예외·빈 파싱이면 원본 순서 폴백(failed=True). never-raise."""
    if not matches:
        return matches, False
    candidates: list[tuple[CaseMatch, str, list[str]]] = []
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

    prompt = build_rerank_prompt(signals, candidates)
    try:
        raw = llm_fn(prompt)
    except Exception:  # noqa: BLE001 — never-raise, 표면 순서 폴백
        return matches, True
    scores = parse_rerank_response(raw, len(candidates))
    if not scores:
        return matches, True

    out: list[CaseMatch] = []
    for i, m in enumerate(matches):
        if i in scores:
            st = scores[i]
            m = m.model_copy(update={
                "structural_score": st,
                "score": ws * m.surface_score + wl * st,
                "reranked": True,
            })
        out.append(m)
    out.sort(key=lambda x: x.score, reverse=True)
    return out, False
