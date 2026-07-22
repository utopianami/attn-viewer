"""엔진 FastAPI 앱 — M1 배관 버전.

POST /v1/answer 는 NDJSON 스트림을 반환한다 (contracts/events.py 계약):
heartbeat(12s) · layer(스테이지 완료마다) · final · error.

M1에서는 실제 워크플로 대신 **에코 파이프라인**이 돈다 — 진짜 layer 어휘·순서
(plan → da_blind → ra_x → toss_trend → macro → final)로 더미 데이터를 방출해
Node/프론트 배관을 端to端 검증한다. M4에서 이 자리에 MAF 그래프가 들어간다.

클라이언트 disconnect 시 스트림 제너레이터에 CancelledError가 전파되어
백그라운드 작업이 중단된다 (고아 런 비용 차단 — 2차 리뷰).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from app.settings import settings  # noqa: E402
from sector.api import router as sector_router  # noqa: E402
from casemem.api import router as casemem_router  # noqa: E402
import sector.scheduler as sector_scheduler  # noqa: E402
from contracts import (  # noqa: E402
    AnswerRequest,
    ErrorEvent,
    FinalEvent,
    HeartbeatEvent,
    LayerEvent,
)
from orchestrator import run_qa  # noqa: E402
from tools.registry import build_default_registry  # noqa: E402

app = FastAPI(title="ryze-qa-engine", version="0.1.0")
app.include_router(sector_router)
app.include_router(casemem_router)
_registry = build_default_registry()


@app.on_event("startup")
async def _startup():
    await sector_scheduler.start(app)

_GPT_ROLES = [
    "planner",
    "plan_extract",
    "da_gpt",
    "da_fable",
    "extract",
    "calc_program",
    "verifier",
    "verifier_cross",
    "risk",
    "synthesizer",
    "audit",
]


def _gpt_overrides(req: AnswerRequest) -> dict | None:
    if req.model_mode not in {"fast", "deep"}:
        return None
    model = req.model or (settings.model_gpt if req.model_mode == "deep" else settings.model_gpt_mini)
    effort = "high" if req.model_mode == "deep" else "low"
    return {role: [("openai", model, effort)] for role in _GPT_ROLES}


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "mode": "qa(M4)",
        "capabilities": settings.capabilities(),
        "tools": _registry.capabilities(),
    }


async def _echo_pipeline(req: AnswerRequest) -> AsyncIterator[str]:
    """M1 더미 파이프라인 — 실제 layer 어휘/순서로 배관 검증."""
    started = time.monotonic()
    hb_at = time.monotonic()

    async def maybe_heartbeat() -> str | None:
        nonlocal hb_at
        if time.monotonic() - hb_at >= settings.heartbeat_interval_s:
            hb_at = time.monotonic()
            return HeartbeatEvent().ndjson()
        return None

    try:
        # ① plan — 중간 표시 UX 1순위: 질문 분해가 채팅에 먼저 보인다
        yield LayerEvent(name="plan", data={
            "tier": 2,
            "standalone_question": req.question,
            "sub_questions": [
                {"id": "q1", "text": f"[에코] '{req.question}'의 배경은?"},
                {"id": "q2", "text": f"[에코] '{req.question}'의 최근 변화는?"},
            ],
            "knowledge_cutoff": "2026-07-02",
            "richness": {"grade": "B", "prelim": True},
        }).ndjson()
        await asyncio.sleep(1.0)

        # ② 유닛별 sub-answer (da_blind)
        yield LayerEvent(name="da_blind", data={
            "unit_answers": [
                {"unit_id": "q0", "model": "da_gpt", "answer_text": "[에코] 전체 질문 독립답변 (더미)"},
                {"unit_id": "q0", "model": "da_fable", "answer_text": "[에코] 전체 질문 독립답변 2 (더미)"},
                {"unit_id": "q1", "model": "da_gpt", "answer_text": "[에코] q1 답 (더미)"},
            ],
        }).ndjson()
        await asyncio.sleep(1.0)

        # ③ 뉴스
        yield LayerEvent(name="ra_x", data={
            "items": [{"title": "[에코] 관련 뉴스 헤드라인 1", "url": "https://example.com/1",
                       "published_at": "2026-07-02T10:00:00"}],
        }).ndjson()
        hb = await maybe_heartbeat()
        if hb:
            yield hb
        await asyncio.sleep(1.0)

        # ④ 트렌드 / ⑤ 매크로
        yield LayerEvent(name="toss_trend", data={
            "trends": [{"label": "[에코] 시장 트렌드 더미", "stocks": ["005930"]}],
        }).ndjson()
        yield LayerEvent(name="macro", data={
            "KOSPI": {"last": 7648.09, "day_pct": -7.89},
            "USD/KRW": {"last": 1542.5, "day_pct": -0.39},
        }).ndjson()
        await asyncio.sleep(1.0)

        # 최종
        yield FinalEvent(
            answer=(
                f"**[에코 답변 — M1 배관 테스트]**\n\n"
                f"질문: {req.question}\n\n"
                f"이 답은 더미입니다. 배관(엔진→Node→저장→화면)이 정상이라는 뜻입니다."
            ),
            meta={
                "degraded": [],
                "models_used": ["echo"],
                "rounds": 0,
                "elapsed_s": round(time.monotonic() - started, 2),
                "plan_summary": {"tier": 2, "knowledge_cutoff": "2026-07-02",
                                 "tickers": [], "fiscal_periods": []},
            },
        ).ndjson()
    except asyncio.CancelledError:
        # 클라이언트 disconnect — 정리 후 중단 (고아 런 차단)
        raise
    except Exception as exc:  # noqa: BLE001
        yield ErrorEvent(message=str(exc), partial=True).ndjson()


async def _qa_pipeline(req: AnswerRequest) -> AsyncIterator[str]:
    """실제 QA 파이프라인 — orchestrator layer를 NDJSON으로 변환 + heartbeat 병행."""
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    async def produce():
        try:
            history = [t.model_dump() for t in req.history]
            async for ev in run_qa(req.question, history=history, overrides=_gpt_overrides(req), user_id=req.user_id):
                await queue.put(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await queue.put({"kind": "error", "message": str(exc)})
        finally:
            await queue.put(DONE)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=settings.heartbeat_interval_s)
            except asyncio.TimeoutError:
                yield HeartbeatEvent().ndjson()
                continue
            if ev is DONE:
                break
            kind = ev.get("kind")
            if kind == "layer":
                yield LayerEvent(name=ev["name"], round=ev.get("round", 0), data=ev["data"]).ndjson()
            elif kind == "final":
                yield FinalEvent(answer=ev["answer"], meta=ev.get("meta", {})).ndjson()
            elif kind == "error":
                yield ErrorEvent(message=ev["message"], partial=True).ndjson()
    finally:
        # 클라이언트 disconnect 등 — producer 취소 후 정리 완료까지 대기 (고아 런·미회수 예외 방지)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@app.post("/v1/answer")
async def answer(req: AnswerRequest) -> StreamingResponse:
    return StreamingResponse(_qa_pipeline(req), media_type="application/x-ndjson")
