"""TRIAGE 확장 오프라인 — LLM 스텁으로 분류 필드·폴백 검증."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stages.triage as triage_mod  # noqa: E402
from stages.triage import TriageResult, run_triage  # noqa: E402


class _StubRole:
    def __init__(self, payload):
        self.payload = payload

    async def run(self, prompt, instructions="", **kw):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_deep_prefix_defaults_to_unknown_full():
    """/deep 강제는 LLM 없이 — 유형은 unknown(→풀코스), countercase False."""
    r, q = asyncio.run(run_triage("/deep 삼성전자 어때?"))
    assert r.route == "deep" and q == "삼성전자 어때?"
    assert r.question_type == "unknown" and r.requires_countercase is False


def test_llm_classification_parsed(monkeypatch):
    payload = triage_mod._TriageLLM(
        route="deep", needs_fresh_data=True, reason="새 질문",
        question_type="stock_judgment", type_confidence="high",
        requires_countercase=True)
    monkeypatch.setattr(triage_mod, "Role", lambda *a, **k: _StubRole(payload))
    r, _ = asyncio.run(run_triage("삼성전자 오를까?"))
    assert r.question_type == "stock_judgment"
    assert r.type_confidence == "high"
    assert r.requires_countercase is True


def test_invalid_type_falls_back_to_unknown(monkeypatch):
    payload = triage_mod._TriageLLM(
        route="deep", needs_fresh_data=True, reason="",
        question_type="banana", type_confidence="sky", requires_countercase=False)
    monkeypatch.setattr(triage_mod, "Role", lambda *a, **k: _StubRole(payload))
    r, _ = asyncio.run(run_triage("아무거나"))
    assert r.question_type == "unknown" and r.type_confidence == "low"


def test_llm_failure_defaults(monkeypatch):
    monkeypatch.setattr(triage_mod, "Role",
                        lambda *a, **k: _StubRole(RuntimeError("down")))
    r, _ = asyncio.run(run_triage("질문"))
    assert r.route == "deep" and r.question_type == "unknown"
