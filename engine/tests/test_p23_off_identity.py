"""3부 T1 — off-arm 구조 등치 회귀 (r2-1). golden = pre-P3(T1 커밋 SHA) 캡처.

권위 있는 실행은 공유 작업트리가 아니라 clean 워크트리에서만
(brief candidate 절차, r3-1): `git worktree add /tmp/p3-cand-wt HEAD` →
`cd /tmp/p3-cand-wt/engine && .venv/bin/python -m pytest tests/test_p23_off_identity.py -q`.

공유 작업트리는 여러 세션이 동시 편집 중이라 dirty할 수 있다(브리핑 실측: orchestrator.py 등).
그 상태로 이 테스트를 돌리면 golden(clean-SHA 캡처)과 실측이 달라 오탐 실패가 난다 — 그래서
engine/ dirty가 감지되면 skip하고, 진짜 회귀 판정은 candidate 워크트리 절차에 위임한다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.p23_harness import CASES, QUESTION, run_pipeline

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "p23_off_golden.json"


def _engine_dirty() -> bool:
    """공유 작업트리의 engine/ 변경 여부 — dirty면 이 테스트는 권위가 없다(skip)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "status", "--porcelain", "--", "engine"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return True  # git 불가 — 안전하게 skip(비권위 실행 방지)
    if out.returncode != 0:
        return True
    return bool(out.stdout.strip())


@pytest.mark.skipif(
    _engine_dirty(),
    reason=(
        "공유 작업트리 engine/ dirty — 이 테스트는 clean 워크트리에서만 권위 있음 "
        "(3부 T1 candidate 절차: git worktree add <tmp> HEAD 후 실행). 공유 트리에서는 skip."
    ),
)
def test_off_arm_structural_identity_to_pre_p3_golden(tmp_path_factory):
    assert _GOLDEN_PATH.exists(), f"golden fixture 없음: {_GOLDEN_PATH}"
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    for case_id, user_id in CASES:
        case_tmp = tmp_path_factory.mktemp(f"p23_{case_id}")
        got = run_pipeline(QUESTION, overrides_extra={"disable_p23": True},
                          user_id=user_id, tmp_path=case_tmp)
        want = golden["cases"][case_id]
        assert got == want, f"case={case_id} 구조 등치 실패 (off-arm)"
