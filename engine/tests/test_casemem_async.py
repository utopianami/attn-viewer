"""Plan 4-a — async 리랭크 어댑터: 코어 재사용·never-raise·이벤트루프 안전."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.async_query import query_case_memory_async
from casemem.seeds import load_seeds
from casemem.store import CaseStore

_AS_OF = "2018-07-01"
_SIGNALS = ["재고일수 상승", "가격 하락"]


def _store(tmp_path):
    cs = CaseStore(tmp_path / "cm")
    load_seeds(cs)
    return cs


def test_no_role_is_pure_deterministic(tmp_path):
    cs = _store(tmp_path)
    r1 = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF))
    r2 = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF))
    assert r1.model_dump() == r2.model_dump()
    assert r1.rerank_used is False and r1.matches


def test_role_reranks_inside_running_loop(tmp_path):
    cs = _store(tmp_path)

    class _Role:
        async def run(self, prompt, *a, **k):
            # 이미 도는 이벤트루프 안에서 호출됨 — asyncio.run() 썼다면 여기서 터짐
            assert asyncio.get_running_loop() is not None
            assert "오늘 signal" in prompt
            n = prompt.count("[")               # 후보 수만큼 만점 부여
            return "[" + ",".join(f'{{"i":{i},"s":0.9}}' for i in range(n)) + "]"

    res = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF,
                                              role=_Role()))
    assert res.rerank_used is True and res.rerank_failed is False
    assert all(m.reranked for m in res.matches)
    assert all(m.structural_score is not None for m in res.matches)


def test_role_failure_falls_back_to_surface_order(tmp_path):
    cs = _store(tmp_path)

    class _Boom:
        async def run(self, *a, **k):
            raise RuntimeError("llm down")

    base = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF))
    res = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF,
                                              role=_Boom()))
    assert res.rerank_used is True and res.rerank_failed is True
    assert [m.episode_id for m in res.matches] == [m.episode_id for m in base.matches]


def test_garbage_llm_output_falls_back(tmp_path):
    cs = _store(tmp_path)

    class _Garbage:
        async def run(self, *a, **k):
            return "no json here"

    res = asyncio.run(query_case_memory_async(cs, signals=_SIGNALS, as_of=_AS_OF,
                                              role=_Garbage()))
    assert res.rerank_used is True and res.rerank_failed is True
