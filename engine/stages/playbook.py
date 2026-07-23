"""플레이북 선택+주입 — 결정적 매칭(LLM 없음), holdout_passed만, 1장만.
스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md §선택+주입

구조 게이트 소비(3부 T8, r2-6): PLAN 이후 evaluate_playbook_gates가 각 gate의
metric_id를 SectorStore 관측과 대조해 pass/fail/unavailable을 코드로 판정한다.
문자열(레거시) gate는 무변경 — parse_gate_checks가 all-or-none으로 채택한다.
"""
import datetime as _dt
import json
import math
import os
from pathlib import Path

from contracts import PlaybookGateCheck, PlaybookGateOutcome
from sector.metrics_registry import METRIC_REGISTRY, _group_key
from sector.period import parse_period
from sector.thesis_contracts import observation_id

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT",
                    Path(__file__).resolve().parents[2] / "storage"))

# 구조 게이트 all-or-none 판정 키 (selector·window_days는 선택)
_STRUCT_KEYS = ("metric_id", "aggregation", "comparator", "threshold", "unit", "max_age_days")
_READ_ALL = 1_000_000               # store.read_metric 전량 읽기 (thesis_guard.py 관례와 동일)
_YOY_BASELINE_DAYS = 365
_YOY_FIXED_WINDOW_DAYS = 45          # r2-6 — 무제한 "최근접" 금지, ±45일 고정 창

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


def _score(question: str, pb: dict) -> tuple[int, int, list[str]]:
    """(score, mk_hits, matched_keys) — match_playbook과 report_rules.rank_playbooks가 공유.

    matchKeys hit = 2 points, topics hit = 1 point.
    dedupe: iterate set(matchKeys) for 2-point hits, then set(topics) - set(matchKeys)
    for 1-point hits. DROP triggers from scoring (synthesis provenance only).
    유비쿼터스 대형주 이름은 matchKey여도 1점 — 무관 질문("갤럭시 신제품 어때?")까지
    종목명 하나로 임계를 넘는 오매칭 실측(2026-07-14). 니치 이름(원익IPS 등)은 2점 유지."""
    match_keys = [k for k in (pb.get("matchKeys") or []) if k]
    topics = [k for k in (pb.get("topics") or []) if k]
    match_key_set = set(match_keys)
    topic_only_set = set(topics) - match_key_set
    score = 0
    mk_hits = 0
    matched: list[str] = []
    for k in match_key_set:
        if k in question:
            mk_hits += 1
            matched.append(k)
            score += 1 if k in _UBIQUITOUS_NAMES else 2
    for k in topic_only_set:
        if k in question:
            score += 1
    return score, mk_hits, sorted(matched)


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
        score, mk_hits, _matched = _score(question, pb)
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


# ── 구조 게이트 소비 (3부 T8, r2-6) ──────────────────────────────────────────

def parse_gate_checks(pb: dict) -> tuple[list[PlaybookGateCheck], list[str]]:
    """플레이북 gates를 구조 게이트로 파싱 — all-or-none.

    _STRUCT_KEYS 전무 → 문자열 gate(레거시, 무로그 — 하위 호환).
    전부 존재 + validate 통과 → 채택. 일부만 또는 validate 실패 → 이 gate는
    구조 판정에서 전체 무시 + 로그(다른 gate 판정에는 영향 없음).
    """
    checks: list[PlaybookGateCheck] = []
    logs: list[str] = []
    for g in pb.get("gates", []):
        if not isinstance(g, dict):
            continue
        present = sum(1 for k in _STRUCT_KEYS if k in g)
        if present == 0:
            continue  # 문자열 gate — 하위 호환, 무로그
        order = g.get("order")
        if present != len(_STRUCT_KEYS):
            logs.append(f"[playbook] gate order={order}: 구조 게이트 키 일부만 존재 — 무시")
            continue
        aggregation = g.get("aggregation")
        if aggregation in ("mean_window", "yoy"):
            window_days = g.get("window_days", 0)
            if not (isinstance(window_days, int) and not isinstance(window_days, bool)
                    and window_days > 0):
                logs.append(
                    f"[playbook] gate order={order}: {aggregation}에 window_days 누락/비양수 — 무시")
                continue
        try:
            chk = PlaybookGateCheck(
                order=g.get("order"), check=g.get("check"), metric_id=g.get("metric_id"),
                selector=g.get("selector") or {}, aggregation=g.get("aggregation"),
                window_days=g.get("window_days", 0), comparator=g.get("comparator"),
                threshold=g.get("threshold"), unit=g.get("unit"),
                max_age_days=g.get("max_age_days"))
        except Exception as exc:  # noqa: BLE001 — validate 실패 fail-closed
            logs.append(f"[playbook] gate order={order}: 구조 게이트 validate 실패 — {exc}")
            continue
        checks.append(chk)
    return checks, logs


def _apply_comparator(comparator: str, value: float, threshold: float) -> str:
    if comparator == ">=":
        ok = value >= threshold
    elif comparator == "<=":
        ok = value <= threshold
    elif comparator == ">":
        ok = value > threshold
    elif comparator == "<":
        ok = value < threshold
    elif comparator == "==":
        ok = value == threshold
    else:
        ok = False  # 방어적 — Literal이 이미 차단
    return "pass" if ok else "fail"


def evaluate_gate(check: PlaybookGateCheck, store, now: _dt.datetime) -> PlaybookGateOutcome:
    """단일 구조 게이트를 실제 SectorStore 관측과 대조해 판정한다 — 전부 코드, fail-closed."""

    def _unavail(reason: str) -> PlaybookGateOutcome:
        return PlaybookGateOutcome(order=check.order, metric_id=check.metric_id,
                                   verdict="unavailable", unavailable_reason=reason)

    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    if check.metric_id not in METRIC_REGISTRY:
        return _unavail("no_metric")

    try:
        rows = store.read_metric(check.metric_id, last_n=_READ_ALL)
    except Exception:  # noqa: BLE001 — 저장소 결함도 fail-closed
        return _unavail("no_metric")

    meta_filter = check.selector.meta_filter or {}
    series = check.selector.series
    filtered = []
    for o in rows:
        if not all(o.meta.get(k) == v for k, v in meta_filter.items()):
            continue
        if series and _group_key(o.meta) != series:
            continue
        filtered.append(o)
    if not filtered:
        return _unavail("no_metric")

    # 혼합 단위 거부 (B8) — 참여 자격 이전 단계의 시리즈 혼입 신호
    nonblank_units = {o.unit for o in filtered if o.unit}
    if len(nonblank_units) >= 2:
        return _unavail("unit_mismatch")

    # yoy는 산출 단위 percent 고정
    if check.aggregation == "yoy" and check.unit != "percent":
        return _unavail("unit_mismatch")

    def _participates(o) -> bool:
        if o.value is None or not math.isfinite(o.value):
            return False
        if not o.unit:                                    # 빈 unit 관측 불참(r2-6)
            return False
        if check.aggregation != "yoy" and o.unit != check.unit:
            return False
        return True

    participants = [o for o in filtered if _participates(o)]
    if not participants:
        return _unavail("unit_mismatch")

    valid: list[tuple] = []
    for o in participants:
        period = parse_period(o.ts)
        if period is None:
            continue                                       # 파싱 불가 → 무효
        start, end = period
        if start > now:
            continue                                       # 미래 → 무효 (fail-closed)
        valid.append((o, start, end))
    if not valid:
        return _unavail("stale_data")

    latest_obs, _latest_start, latest_end = max(valid, key=lambda t: t[2])
    age_days = max(0.0, (now - latest_end).total_seconds() / 86400.0)
    if age_days > check.max_age_days:
        return _unavail("stale_data")

    evidence_id = observation_id(check.metric_id, latest_obs.ts, latest_obs.meta)

    if check.aggregation == "last":
        value = float(latest_obs.value)
    elif check.aggregation == "mean_window":
        window_start = now - _dt.timedelta(days=check.window_days)
        window_vals = [o.value for o, _s, e in valid if window_start <= e <= now]
        if not window_vals:
            return _unavail("stale_data")
        value = sum(window_vals) / len(window_vals)
    elif check.aggregation == "yoy":
        target = latest_end - _dt.timedelta(days=_YOY_BASELINE_DAYS)
        window_lo = target - _dt.timedelta(days=_YOY_FIXED_WINDOW_DAYS)
        window_hi = target + _dt.timedelta(days=_YOY_FIXED_WINDOW_DAYS)
        candidates = [(o, e) for o, _s, e in valid
                      if not (o.ts == latest_obs.ts and o.meta == latest_obs.meta)
                      and window_lo <= e <= window_hi]
        if not candidates:
            return _unavail("stale_data")                  # r2-6 — 고정 창 밖은 stale
        baseline_obs, _be = min(candidates, key=lambda t: abs((t[1] - target).total_seconds()))
        if not baseline_obs.value:
            return _unavail("stale_data")
        value = (float(latest_obs.value) / float(baseline_obs.value) - 1.0) * 100.0
    else:
        return _unavail("no_metric")  # 방어적 — Literal이 이미 차단

    verdict = _apply_comparator(check.comparator, value, check.threshold)
    return PlaybookGateOutcome(order=check.order, metric_id=check.metric_id,
                               value=value, verdict=verdict,
                               evidence_observation_id=evidence_id)


def evaluate_playbook_gates(pb: dict, store, now: _dt.datetime
                            ) -> tuple[list[PlaybookGateOutcome], list[str]]:
    """플레이북 전체 구조 게이트를 평가한다 — 문자열 gate는 parse 단계에서 이미 제외."""
    checks, logs = parse_gate_checks(pb)
    outcomes = [evaluate_gate(chk, store, now) for chk in checks]
    return outcomes, logs
