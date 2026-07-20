"""저지 calibration — 튜닝 fixture(공개) / 봉인 metamorphic 셋(버전당 1회) 분리 (r3-B8)."""
from __future__ import annotations

import json
from pathlib import Path

_FIX = Path(__file__).parent / "fixtures" / "chain_judge"


def load_tuning_fixtures() -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted((_FIX / "tuning").glob("*.json"))]


async def run_selftest(judge_fn) -> list[str]:
    failures: list[str] = []
    for f in load_tuning_fixtures():
        res = await judge_fn(f["id"], f["answer_md"], f["rubric"], f["bundle_text"])
        if res is None:
            failures.append(f"{f['id']}: judge invalid")
            continue
        for ax, want in f["expected"].items():
            got = res.axes[ax].score
            ok = got is not None and (got == float(want) if want in (0, 1)
                                      else abs(got - want) < 0.26)
            if not ok:
                failures.append(f"{f['id']}: {ax} expected {want} got {got}")
    return failures
