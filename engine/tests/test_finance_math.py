"""finance_math 회귀 (LLM 불필요 — CI 상시 실행 가능).

하네스 numeric_policy.md의 단위 규율 골든: percent−percent=pp 등.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.calc import evaluate, run  # noqa: E402


def test_growth_rate_percent():
    # (120-100)/100 * 100 = 20%
    payload = {
        "typed_facts": [
            {"id": "rev_now", "value": 120, "unit": "num"},
            {"id": "rev_prev", "value": 100, "unit": "num"},
        ],
        "program": [
            {"op": "subtract", "args": ["rev_now", "rev_prev"], "out": "delta"},
            {"op": "divide", "args": ["delta", "rev_prev"], "out": "ratio"},
            {"op": "multiply", "args": ["ratio", 100], "out": "pct"},
        ],
    }
    r = evaluate(payload)
    assert not r["errors"], r
    assert float(r["result"]["value"]) == 20.0
    assert r["result"]["unit"] == "percent"


def test_margin_percentage_point():
    # 10% - 8% = 2pp (NOT 2%) — 단위 규율의 핵심
    payload = {
        "typed_facts": [
            {"id": "m_now", "value": 10, "unit": "percent"},
            {"id": "m_prev", "value": 8, "unit": "percent"},
        ],
        "program": [
            {"op": "subtract", "args": ["m_now", "m_prev"], "out": "delta"},
        ],
    }
    r = evaluate(payload)
    assert not r["errors"], r
    assert float(r["result"]["value"]) == 2.0
    assert r["result"]["unit"] == "pp"


def test_pp_to_bps():
    payload = {
        "typed_facts": [{"id": "d", "value": 2, "unit": "pp"}],
        "program": [{"op": "pp_to_bps", "args": ["d"], "out": "bps"}],
    }
    r = evaluate(payload)
    assert not r["errors"], r
    assert float(r["result"]["value"]) == 200.0
    assert r["result"]["unit"] == "bps"


def test_divide_by_zero_reports_error():
    payload = {
        "typed_facts": [{"id": "a", "value": 10, "unit": "num"}, {"id": "z", "value": 0, "unit": "num"}],
        "program": [{"op": "divide", "args": ["a", "z"], "out": "x"}],
    }
    r = run(payload)  # never-raise 래퍼
    assert r["errors"], "division by zero should report error"
