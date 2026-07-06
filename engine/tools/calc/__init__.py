"""결정적 계산 — 하네스 finance_math 벤더링 (무수정).

evaluate(payload)는 순수 함수지만 오류 시 FinanceMathError를 raise한다.
엔진은 never-raise 원칙이므로 run(payload)를 쓴다 — 오류를 errors 리스트로 감싸 반환.
"""

from .finance_math import FinanceMathError, evaluate


def run(payload: dict) -> dict:
    """evaluate를 감싸 오류를 errors 리스트로 반환 (executor용, never-raise)."""
    try:
        return evaluate(payload)
    except FinanceMathError as exc:
        return {"result": None, "steps": [], "checks": {}, "errors": [str(exc)]}


__all__ = ["evaluate", "run", "FinanceMathError"]
