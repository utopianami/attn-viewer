"""플레이북 선택+주입 — 결정적 매칭(LLM 없음), holdout_passed만, 1장만.
스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md §선택+주입
"""
import json
import os
from pathlib import Path

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT",
                    Path(__file__).resolve().parents[2] / "storage"))

# 질문 유형 → 허용 conclusionType. fact_lookup·unknown·smalltalk은 주입 없음(안전 기본값).
_TYPE_MAP = {
    "stock_judgment": {"방향 판단", "종목 비교", "시점 판단"},
    "industry_analysis": {"방향 판단", "리스크 점검"},
    "event_interpretation": {"방향 판단", "리스크 점검"},
    "strategy_portfolio": {"시점 판단"},
}


def load_playbooks(user_id: str) -> list[dict]:
    pb_dir = STORAGE_ROOT / "users" / user_id / "corpus" / "playbooks"
    out = []
    if not pb_dir.is_dir():
        return out
    for f in pb_dir.glob("*.json"):
        if f.name in ("clusters.json", "holdout.json", "holdout-report.json"):
            continue
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue  # 손상 파일은 무시하고 주입 없이 정상 답변 (스펙 §오류 처리)
    return out


def match_playbook(question: str, question_type: str, playbooks: list[dict]) -> dict | None:
    allowed = _TYPE_MAP.get(question_type)
    if not allowed:
        return None
    best, best_score = None, 0
    for pb in playbooks:
        if pb.get("status") != "holdout_passed":
            continue
        if pb.get("conclusionType") not in allowed:
            continue
        keys = set(pb.get("triggers", [])) | set(pb.get("topics", []))
        score = sum(1 for k in keys if k and k in question)
        if score > best_score:
            best, best_score = pb, score
    return best  # 키워드 0히트면 best_score=0 → None


def format_gates(pb: dict) -> str:
    lines = [f"[참고 절차 — {pb['situation']} (전문가 사고 재구성)]",
             "아래는 확인 '절차'다. 절차 내용을 사실·근거로 인용하지 말고, 계획 수립에만 써라."]
    for g in pb["gates"]:
        kill = f" / 킬: {g['kill']}" if g.get("kill") else ""
        lines.append(f"{g['order']}. {g['check']} (기준: {g['operationalization']}{kill})")
    return "\n".join(lines)


def format_connection(pb: dict) -> str:
    lines = [f"[사고 연결 참고 — {pb['situation']}]",
             "아래는 결론 연결 '방식'이다. 이 절의 내용을 사실 근거로 인용하지 마라.",
             f"연결: {pb['connection']}"]
    if pb.get("reservations"):
        lines.append(f"유보: {pb['reservations']}")
    return "\n".join(lines)
