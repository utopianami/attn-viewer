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


_REQUIRED_KEYS = {"slug", "situation", "triggers", "topics", "conclusionType",
                  "gates", "connection", "status"}

# 온갖 질문에 등장하는 대형주 호칭 — matchKey여도 1점으로 강등 (단독으로 임계 통과 금지)
_UBIQUITOUS_NAMES = {"삼성전자", "SK하이닉스", "하이닉스", "마이크론", "Micron",
                     "TSMC", "엔비디아", "NVIDIA", "인텔", "Intel"}
_REQUIRED_GATE_KEYS = {"order", "check", "operationalization"}


def _valid_playbook(pb: object) -> bool:
    """플레이북 dict 구조+타입 유효성 검사 — 손상 항목은 무시 (스펙 §오류 처리)."""
    if not isinstance(pb, dict):
        return False
    if not _REQUIRED_KEYS.issubset(pb.keys()):
        return False
    # 타입 검증: str 스칼라 필드
    for field in ("slug", "situation", "connection", "status", "conclusionType"):
        if not isinstance(pb.get(field), str):
            return False
    # triggers / topics: list of str
    for field in ("triggers", "topics"):
        val = pb.get(field)
        if not isinstance(val, list) or not all(isinstance(t, str) for t in val):
            return False
    # matchKeys: optional; if present must be list[str]
    match_keys_val = pb.get("matchKeys")
    if match_keys_val is not None:
        if not isinstance(match_keys_val, list) or not all(isinstance(k, str) for k in match_keys_val):
            return False
    # gates: 비어있지 않은 dict 리스트, 각 gate의 필수 키+타입 검사
    gates = pb.get("gates")
    if not isinstance(gates, list) or len(gates) == 0:
        return False
    for g in gates:
        if not isinstance(g, dict) or not _REQUIRED_GATE_KEYS.issubset(g.keys()):
            return False
        if not (isinstance(g.get("order"), int) and not isinstance(g.get("order"), bool)):
            return False
        if not isinstance(g.get("check"), str):
            return False
        if not isinstance(g.get("operationalization"), str):
            return False
    return True


def load_playbooks(user_id: str) -> list[dict]:
    pb_dir = STORAGE_ROOT / "users" / user_id / "corpus" / "playbooks"
    out = []
    if not pb_dir.is_dir():
        return out
    for f in sorted(pb_dir.glob("*.json")):  # glob 순서 결정적으로
        if f.name in ("clusters.json", "holdout.json", "holdout-report.json"):
            continue
        try:
            pb = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            print(f"[playbook] skip {f.name}: JSON 파싱 실패")
            continue  # 손상 파일은 무시하고 주입 없이 정상 답변 (스펙 §오류 처리)
        if not _valid_playbook(pb):
            print(f"[playbook] skip {f.name}: 구조/타입 검증 실패")
            continue  # 구조 불량 항목도 무시
        out.append(pb)
    return out


def match_playbook(question: str, question_type: str, playbooks: list[dict]) -> dict | None:
    allowed = _TYPE_MAP.get(question_type)
    if not allowed:
        return None
    scores: list[tuple[int, str, dict, int]] = []  # (score, slug, playbook, mk_hits)
    # slug 오름차순 정렬 → 동점 시 결정적(사전순 앞) 플레이북 선택
    for pb in sorted(playbooks, key=lambda p: p.get("slug", "") if isinstance(p, dict) else ""):
        if not isinstance(pb, dict):
            continue  # 방어적 스킵: load_playbooks를 우회해도 안전
        if not _REQUIRED_KEYS.issubset(pb.keys()):
            continue  # 필수 필드 누락 → 스킵
        if pb.get("status") != "holdout_passed":
            continue
        if pb.get("conclusionType") not in allowed:
            continue
        # matchKeys hit = 2 points, topics hit = 1 point
        # dedupe: iterate set(matchKeys) for 2-point hits, then set(topics) - set(matchKeys) for 1-point hits
        # DROP triggers from scoring (keep triggers field in JSON — it's synthesis provenance)
        # 유비쿼터스 대형주 이름은 matchKey여도 1점 — 무관 질문("갤럭시 신제품 어때?")까지
        # 종목명 하나로 임계를 넘는 오매칭 실측(2026-07-14). 니치 이름(원익IPS 등)은 2점 유지.
        match_keys = [k for k in (pb.get("matchKeys") or []) if k]
        topics = [k for k in (pb.get("topics") or []) if k]
        match_key_set = set(match_keys)
        topic_only_set = set(topics) - match_key_set
        score = 0
        mk_hits = 0
        for k in match_key_set:
            if k in question:
                mk_hits += 1
                score += 1 if k in _UBIQUITOUS_NAMES else 2
        for k in topic_only_set:
            if k in question:
                score += 1
        scores.append((score, pb.get("slug", ""), pb, mk_hits))

    if not scores:
        return None

    scores.sort(key=lambda x: (-x[0], x[1]))  # 점수 내림차순, 동점이면 slug 오름차순
    best_score = scores[0][0]
    if best_score < 2:
        return None  # 최소 점수 미달
    if scores[0][3] == 0:
        return None  # topics만으로는 매칭 불가 — matchKey 히트 최소 1개 (배경 topic 오매칭 차단 실측)

    # 마진 검사: 1위와 2위의 점수 차이가 1 이상이어야 함
    second_score = scores[1][0] if len(scores) > 1 else 0
    if best_score - second_score < 1:
        return None  # 마진 부족 → 안전 기본값 무매칭

    return scores[0][2]


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
