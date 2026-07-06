"""M2 PoC — MAF 워크플로 기본기 (LLM 불필요, 그래프 구조만).

    engine/.venv/bin/python -m pytest engine/poc/test_workflow.py -v -s

검증:
- fan-in 핸들러가 list를 받는가 (계획 PoC #4 — "집계 메시지 타입 실측")
- switch-case 배타 라우팅 (Tier4 차단 / REFLECT 배타 라우팅 기반)
- WorkflowBuilder(start_executor=...) 필수, .run() 사용, run 결과 .get_outputs()
"""

import asyncio

from agent_framework import (
    Case,
    Default,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)


class Start(Executor):
    @handler
    async def run(self, msg: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(msg)


class Dispatch(Executor):
    @handler
    async def run(self, msg: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(msg)


class _Branch(Executor):
    label = "?"

    @handler
    async def run(self, msg: str, ctx: WorkflowContext[dict]) -> None:
        await ctx.send_message({"branch": self.label, "msg": msg})


class BranchA(_Branch):
    label = "A"


class BranchB(_Branch):
    label = "B"


class BranchC(_Branch):
    label = "C"


class Blocked(Executor):
    @handler
    async def run(self, msg: str, ctx: WorkflowContext[str, str]) -> None:
        await ctx.yield_output("BLOCKED")


class Assembler(Executor):
    received_type: str = ""
    received_count: int = 0

    @handler
    async def run(self, packets: list[dict], ctx: WorkflowContext[str, str]) -> None:
        Assembler.received_type = type(packets).__name__
        Assembler.received_count = len(packets) if isinstance(packets, list) else 1
        await ctx.yield_output(f"assembled {Assembler.received_count}")


def _build():
    start, dispatch, blocked = Start(id="start"), Dispatch(id="dispatch"), Blocked(id="blocked")
    a, b, c = BranchA(id="a"), BranchB(id="b"), BranchC(id="c")
    asm = Assembler(id="asm")
    wb = WorkflowBuilder(start_executor=start)
    wb.add_switch_case_edge_group(start, [
        Case(condition=lambda m: "block" in m, target=blocked),
        Default(target=dispatch),
    ])
    for br in (a, b, c):
        wb.add_edge(dispatch, br)
    wb.add_fan_in_edges([a, b, c], asm)
    return wb.build()


def test_fan_in_receives_list():
    r = asyncio.run(_build().run("hello"))
    assert Assembler.received_type == "list"
    assert Assembler.received_count == 3
    assert r.get_outputs() == ["assembled 3"]


def test_switch_case_blocks():
    r = asyncio.run(_build().run("please block this"))
    assert r.get_outputs() == ["BLOCKED"]
