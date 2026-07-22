"""오케스트레이션(순수) + 영속화(예약 필수) + CLI 엔트리포인트.

싱글턴 시스템 리포트 — AGENTS.md '시스템 리포트 예외' 참조. 스펙 v3 · 계획 v2 T10.
저장 순서: ① alloc_report_slot(예약) → ② run_report_pipeline(seq 주입, 순수)
→ ③ save_report(예약 경로 검증 후 원자 교체). 예약은 1회용(codex NB7).
과거사례(Plan4-c): case_store 주입 시 external_knowledge를 심화·합성에 전달."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sector.report_anchors import build_anchors
from sector.report_assemble import assemble_report
from sector.report_contracts import PipelineStage, Report
from sector.report_filters import cluster_events, filter_importance, filter_relevance
from sector.report_input import _to_utc, assemble_report_input
from sector.report_rules import derive_topics, rank_playbooks
from sector.report_synthesis import deepen, synthesize_claims
from sector.report_verify import verify_claims

_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "memory_sector"
_ALLOWED_TYPES = {"방향 판단", "종목 비교", "시점 판단", "리스크 점검"}
_KST = timezone(timedelta(hours=9))


def alloc_report_slot(root: Path, date_str: str) -> tuple[int, Path, str]:
    """flat reports/에 토큰 파일을 배타 생성으로 예약 — 동시 실행 충돌·위조 방지.

    반환 (seq, path, token). 토큰(uuid)이 파일에 기록되며 save_report가 대조한다
    (빈 파일 위조 차단 — code review B7)."""
    import uuid
    d = root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    token = f"__reserved__{uuid.uuid4().hex}"
    seq = 1
    while True:
        p = d / f"{date_str}-{seq}.json"
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, token.encode())
            os.close(fd)
            return seq, p, token
        except FileExistsError:
            seq += 1


def save_report(report: Report, path: Path, token: str) -> Path:
    """예약 경로에만 저장 — 토큰 대조로 예약 진위 확인(B7). 이름 불일치 거부."""
    if not path.exists():
        raise ValueError(f"예약되지 않은 경로: {path} — alloc_report_slot 먼저")
    if path.read_text(encoding="utf-8", errors="replace") != token:
        raise ValueError(f"예약 토큰 불일치(위조/기저장): {path}")
    if path.name != f"{report.id}.json":
        raise ValueError(f"report.id({report.id})와 예약 파일명({path.name}) 불일치")
    tmp = path.with_suffix(f".{token[-12:]}.tmp")             # 토큰별 tmp — 공유 tmp 레이스 방지
    tmp.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)                                     # 예약 파일 위 원자 교체
    return path


def _stage(io, items: list[str]) -> PipelineStage:
    flow = f"in {io.in_count} → out {io.out_count}"
    if io.dropped:
        flow += f" (drop {len(io.dropped)})"
    note = f"{io.note} · {flow}" if io.note else flow
    return PipelineStage(key=io.key, label=io.label, note=note,
                         items=items, io=io.model_dump())   # 전량 — 뷰어가 더보기로 접음


def _default_roles(overrides=None):
    from providers import Role
    fil = Role("report_filter", overrides)
    return {"filter": fil, "importance": fil, "cluster": fil,
            "deepen": Role("report_deepen", overrides),
            "synth": Role("report_synth", overrides),
            "verifier": Role("verifier", overrides),
            "cross": Role("verifier_cross", overrides)}


async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12,
                              seq: int, playbook_corpus: str = "ryze_yn",
                              roles: dict | None = None,
                              case_store=None) -> Report:
    eff = _to_utc(now)
    errors: list[str] = []
    stages: list[PipelineStage] = []
    seams = ["price_reaction", "analyst_reports"]

    try:
        roles = roles or _default_roles()
    except Exception as exc:  # noqa: BLE001 — never-raise: role 없으면 빈 리포트로
        errors.append(f"roles: {exc}")
        roles = {}

    class _NoRole:
        async def run(self, *a, **k):
            raise RuntimeError("role unavailable")

    def _role(name):
        return roles.get(name) or _NoRole()

    try:
        ri = assemble_report_input(store, window_hours=window_hours, now=eff)
        ri_diag = ri.diagnostics.model_dump()
        raw_news, cards = ri.raw_news, ri.cards
    except Exception as exc:  # noqa: BLE001 — never-raise(B5): 진단 리포트라도 발행
        errors.append(f"input: {exc}")
        raw_news, cards, ri_diag = [], [], {"error": str(exc)}
    try:
        anchors = build_anchors(store, now=eff)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"anchors: {exc}")
        anchors = []
    stages.append(PipelineStage(
        key="raw", label="raw",
        sources=[{"name": f"SectorCard ({len(cards)}건)",
                  "items": [c.title for c in cards]},
                 {"name": f"SaveTicker raw ({len(raw_news)}건)",
                  "items": [d.title for d in raw_news]},
                 {"name": f"anchors ({len(anchors)}건)",
                  "items": [f"{a.anchor_id}={a.value}{a.unit} @{a.as_of}"
                            for a in anchors]}],
        io=ri_diag))

    # 교차 스트림 중복 정규화(codex F7): SaveTicker 원문(id X)과 그 판정 카드(st-X)가
    # 둘 다 있으면 뉴스 쪽을 제거 — 같은 문서가 출처 2건으로 부풀지 않게
    card_ids = {c.id for c in cards}
    canon_dupes = [d for d in raw_news if f"st-{d.id}" in card_ids or d.id in card_ids]
    if canon_dupes:
        dup_ids = {d.id for d in canon_dupes}
        raw_news = [d for d in raw_news if d.id not in dup_ids]

    f1 = await filter_relevance(raw_news, cards, role=_role("filter"))
    if f1.error:
        errors.append(f"f1: {f1.error}")
    if canon_dupes:
        f1.io.note = ((f1.io.note + " · ") if f1.io.note else "") + \
            f"교차중복 정규화 {len(canon_dupes)}건(카드 우선)"
    stages.append(_stage(f1.io, [e.title for e in f1.output]))

    f2 = await filter_importance(f1.output, role=_role("importance"),
                                 window_hours=window_hours)
    if f2.error:
        errors.append(f"f2: {f2.error}")
    stages.append(_stage(f2.io, [e.title for e in f2.output]))

    f3 = await cluster_events(f2.output, role=_role("cluster"))
    if f3.error:
        errors.append(f"f3: {f3.error}")
    f3_stage = _stage(f3.io, [c.title for c in f3.output])
    f3_stage.io = dict(f3_stage.io or {}, clusters=[
        {"cluster_id": c.cluster_id, "title": c.title, "axis": c.axis,
         "direction": c.direction, "member_ids": [m.id for m in c.members]}
        for c in f3.output])                     # 감사 가능성(codex F9)
    stages.append(f3_stage)
    clusters = f3.output

    # 규칙 인출(코드, 결정적)
    try:
        from stages.playbook import load_playbooks
        pbs = load_playbooks(playbook_corpus)
    except Exception as exc:  # noqa: BLE001 — never-raise
        pbs = []
        errors.append(f"playbook: {exc}")
    # anchor 라벨은 규칙 매칭 신호에서 제외 — 전역 anchor 텍스트가 모든 이벤트를
    # 규칙에 오매칭시킴(codex F10: 무관 기사가 anchor 때문에 score 6 실증)
    signal_text = " ".join(t for c in clusters for t in derive_topics(c, []))
    rules = rank_playbooks(signal_text, pbs, allowed_conclusion_types=_ALLOWED_TYPES)

    # 과거사례 질의(Plan4-c) — case_store 있을 때만, 결정적(llm_fn 없음), never-raise
    cases: list[dict] = []
    case_diag: dict = {}
    case_ok = False
    if case_store is not None:
        try:
            from casemem.query import query_case_memory
            signals = [t for c in clusters for t in derive_topics(c, anchors)]
            res = query_case_memory(case_store, signals=signals,
                                    as_of=eff.isoformat(), sector="memory")
            cases = [m.model_dump() for m in res.matches]
            case_diag = {"case_memory_matches": len(cases),
                         "case_memory_scanned": res.scanned}
            case_ok = True
        except Exception as exc:  # noqa: BLE001
            errors.append(f"case_memory: {exc}")
    if not case_ok:
        seams.append("case_memory")     # 질의 실패/미주입이면 seam 유지(SF2 — 정직 표기)

    dp = await deepen(clusters, rules, anchors, cases=cases, role=_role("deepen"))
    if dp.error:
        errors.append(f"deepen: {dp.error}")
    stages.append(_stage(dp.io, [r["slug"] for r in rules]
                         + [f"case:{c.get('episode_id')}" for c in cases]))

    sy = await synthesize_claims(dp.output, clusters, anchors, rules, cases=cases,
                                 role=_role("synth"))
    if sy.error:
        errors.append(f"synth: {sy.error}")
    stages.append(_stage(sy.io, [c.title for c in sy.output]))

    vf = await verify_claims(sy.output, anchors, clusters, cutoff=eff,
                             verifier=_role("verifier"), cross=_role("cross"))
    if vf.error:
        errors.append(f"verify: {vf.error}")
    vstage = _stage(vf.io, [f"{v.claim_id}:{v.status}" for v in vf.output])
    vstage.io = dict(vstage.io or {},
                     verdicts=[v.model_dump() for v in vf.output])  # 사유 직렬화(SF7)
    stages.append(vstage)

    try:
        report = assemble_report(sy.output, vf.output, stages=stages, now=eff,
                                 window_hours=window_hours, seq=seq,
                                 title=f"메모리 반도체 {window_hours}시간 시황",
                                 stage_errors=errors, seams_empty=seams)
        report.diagnostics.update(case_diag)
        return report
    except Exception as exc:  # noqa: BLE001 — 최후 안전망: 진단만 담은 리포트
        from datetime import timedelta as _td
        from sector.report_contracts import FinalOpinion, ReportPipeline
        kst = eff.astimezone(_KST)
        return Report(
            id=f"{kst.strftime('%Y-%m-%d')}-{seq}", seq=seq,
            generatedAt=kst.isoformat(),
            title=f"메모리 반도체 {window_hours}시간 시황 (조립 실패)",
            window={"from": (eff - _td(hours=window_hours)).astimezone(_KST).isoformat(),
                    "to": kst.isoformat()},
            overview="리포트 조립 실패 — 진단 참조.",
            finalOpinion=FinalOpinion(text="관망", confidence="낮"),
            pipeline=ReportPipeline(stages=stages),
            diagnostics={"stage_errors": errors + [f"assemble: {exc}"],
                         "seams_empty": seams, "rejected_claims": []})


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--now")
    ap.add_argument("--window", type=int, default=12)
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--case-memory", action="store_true",
                    help="과거사례 지식층 연결(Plan4-c)")
    args = ap.parse_args(argv)
    now = _to_utc(datetime.fromisoformat(args.now) if args.now
                  else datetime.now(timezone.utc))
    root = Path(args.root)
    kst_date = now.astimezone(_KST).strftime("%Y-%m-%d")
    seq, path, token = alloc_report_slot(root, kst_date)       # ① 예약(토큰)
    from sector.store import SectorStore
    store = SectorStore(root)
    case_store = None
    if args.case_memory:
        from casemem.api import _get_store
        case_store = _get_store()
    report = asyncio.run(run_report_pipeline(
        store, now=now, window_hours=args.window, seq=seq,
        case_store=case_store))                                # ② 실행(순수)
    save_report(report, path, token)                           # ③ 예약 경로에 저장(토큰 대조)
    print(report.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
