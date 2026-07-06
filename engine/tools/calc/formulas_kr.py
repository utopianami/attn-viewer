"""한국 시장 공식 템플릿 (P3-1, F8: 공식 계획을 명시 단계로 두면 작성 오류·단위 실수 감소).

CALC 프로그램 작성 프롬프트에 few-shot으로 주입된다 — 직접 실행되는 게 아니라
GPT가 이 모양대로 typed_fact id를 끼워 프로그램을 작성하게 하는 가이드.
program의 args 이름은 '필요 입력' 자리표시자 — 실제 작성 시 typed_fact id로 치환된다.
"""

from __future__ import annotations

FORMULAS: dict[str, dict] = {
    "ytd_return": {
        "label": "연초 대비 수익률(%)",
        "inputs": ["price_now", "price_yearstart"],
        "program": [
            {"op": "subtract", "args": ["price_now", "price_yearstart"], "out": "diff"},
            {"op": "divide", "args": ["diff", "price_yearstart"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "ytd_pct"},
        ],
        "tol_pct": 0.5,
    },
    "period_return": {
        "label": "기간 수익률(%)",
        "inputs": ["price_now", "price_base"],
        "program": [
            {"op": "subtract", "args": ["price_now", "price_base"], "out": "diff"},
            {"op": "divide", "args": ["diff", "price_base"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "period_pct"},
        ],
        "tol_pct": 0.5,
    },
    "per": {
        "label": "PER(배)",
        "inputs": ["price_now", "eps_ttm"],
        "program": [{"op": "divide", "args": ["price_now", "eps_ttm"], "out": "per"}],
        "tol_pct": 1.0,
    },
    "pbr": {
        "label": "PBR(배)",
        "inputs": ["price_now", "bps"],
        "program": [{"op": "divide", "args": ["price_now", "bps"], "out": "pbr"}],
        "tol_pct": 1.0,
    },
    "div_yield": {
        "label": "배당수익률(%)",
        "inputs": ["dps", "price_now"],
        "program": [
            {"op": "divide", "args": ["dps", "price_now"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "yield_pct"},
        ],
        "tol_pct": 0.5,
    },
    "yoy": {
        "label": "전년 동기 대비(%)",
        "inputs": ["value_now", "value_prev_year"],
        "program": [
            {"op": "subtract", "args": ["value_now", "value_prev_year"], "out": "diff"},
            {"op": "divide", "args": ["diff", "value_prev_year"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "yoy_pct"},
        ],
        "tol_pct": 0.5,
    },
    "qoq": {
        "label": "전분기 대비(%)",
        "inputs": ["value_now", "value_prev_q"],
        "program": [
            {"op": "subtract", "args": ["value_now", "value_prev_q"], "out": "diff"},
            {"op": "divide", "args": ["diff", "value_prev_q"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "qoq_pct"},
        ],
        "tol_pct": 0.5,
    },
    "gap_pct": {
        "label": "괴리율(%)",
        "inputs": ["value_a", "value_b"],
        "program": [
            {"op": "subtract", "args": ["value_a", "value_b"], "out": "diff"},
            {"op": "divide", "args": ["diff", "value_b"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", "100"], "out": "gap_pct"},
        ],
        "tol_pct": 0.5,
    },
}

# 동의어 매핑 — 순서 중요: 구체적 표현("올해 수익률")이 일반 표현("수익률")보다 먼저
_SYNONYMS: list[tuple[str, tuple[str, ...]]] = [
    ("ytd_return", ("연초 대비", "올해 수익률", "올해 상승률", "연초 이후", "ytd", "연중 수익률")),
    ("yoy", ("전년 동기", "전년 대비", "yoy", "작년 대비", "작년 동기")),
    ("qoq", ("전분기 대비", "직전 분기 대비", "qoq", "전 분기 대비")),
    ("div_yield", ("배당수익률", "배당 수익률", "배당률", "시가배당률")),
    ("per", ("per", "주가수익비율", "주가 수익 비율", "p/e")),
    ("pbr", ("pbr", "주가순자산비율", "주가 순자산 비율", "p/b")),
    ("gap_pct", ("괴리율", "괴리", "차이율", "갭 비율")),
    ("period_return", ("기간 수익률", "수익률", "상승률", "등락률", "하락률", "변동률")),
]


def match_formula(metric_text: str) -> str | None:
    """metric 자유 서술 → 공식 키 ("올해 수익률(%)" → "ytd_return"). 없으면 None."""
    m = (metric_text or "").strip().lower()
    if not m:
        return None
    for key, words in _SYNONYMS:
        if any(w in m for w in words):
            return key
    return None


def render_template(key: str) -> str:
    """few-shot 주입용 텍스트 렌더."""
    f = FORMULAS[key]
    steps = "\n".join(
        f"  {{op: {s['op']}, args: {s['args']}, out: {s['out']}}}" for s in f["program"])
    return (f"[{key}] {f['label']} — 필요 입력: {', '.join(f['inputs'])}\n"
            f"  (입력 이름을 실제 typed_fact id로 치환해 작성)\n{steps}")
