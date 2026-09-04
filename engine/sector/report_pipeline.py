"""오케스트레이션(순수) + 영속화(예약 필수) + CLI 엔트리포인트.

싱글턴 시스템 리포트 — AGENTS.md '시스템 리포트 예외' 참조. 스펙 v3 · 계획 v2 T10.
저장 순서: ① alloc_report_slot(.reserve 예약) → ② run_report_pipeline(seq 주입, 순수)
→ ③ save_report(예약 검증 후 최종 JSON 원자 발행). 예약은 1회용(codex NB7).
과거사례(Plan4-c): case_store 주입 시 external_knowledge를 심화·합성에 전달."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sector.report_anchors import build_anchors
from sector.report_assemble import assemble_report
from sector.report_contracts import (EvidenceRef, FinalOpinion, PipelineStage,
                                     Report, ReportPipeline, StageIO, StageResult)
from sector.report_filters import cluster_events, filter_importance, filter_relevance
from sector.report_input import _to_utc, assemble_report_input
from sector.report_rules import derive_topics, rank_playbooks
from sector.report_synthesis import deepen, revise_claims, synthesize_claims
from sector.report_verify import verify_claims

_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "memory_sector"
_ALLOWED_TYPES = {"방향 판단", "종목 비교", "시점 판단", "리스크 점검"}
_KST = timezone(timedelta(hours=9))


def alloc_report_slot(root: Path, date_str: str) -> tuple[int, Path, str]:
    """flat reports/에 .reserve를 배타 생성해 최종 JSON 노출 없이 예약한다.

    반환 (seq, final_path, token). 토큰(uuid)은 별도 예약 파일에 기록되며
    save_report가 대조한다(빈 파일 위조 차단 — code review B7)."""
    import uuid
    d = root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    archive = d.parent / "report-archive"
    prefix = f"{date_str}-"

    def _sequence(path: Path) -> int | None:
        name = path.name
        for suffix in (".json", ".reserve"):
            if name.startswith(prefix) and name.endswith(suffix):
                raw = name[len(prefix):-len(suffix)]
                return int(raw) if raw.isdigit() else None
        return None

    consumed = {
        seq for path in (*d.glob(f"{date_str}-*.json"),
                         *d.glob(f"{date_str}-*.reserve"))
        if (seq := _sequence(path)) is not None
    }
    if archive.is_dir():
        consumed.update(
            seq for path in archive.rglob(f"{date_str}-*.json")
            if (seq := _sequence(path)) is not None
        )
    token = f"__reserved__{uuid.uuid4().hex}"
    seq = 1
    while True:
        if seq in consumed:
            seq += 1
            continue
        p = d / f"{date_str}-{seq}.json"
        if p.exists():
            seq += 1
            continue
        reservation = p.with_suffix(".reserve")
        try:
            fd = os.open(reservation, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as reserved:
                reserved.write(token)
            return seq, p, token
        except FileExistsError:
            seq += 1


def save_report(report: Report, path: Path, token: str) -> Path:
    """예약 경로에만 저장 — 토큰 대조로 예약 진위 확인(B7). 이름 불일치 거부."""
    reservation = path.with_suffix(".reserve")
    if not reservation.exists():
        raise ValueError(f"예약되지 않은 경로: {path} — alloc_report_slot 먼저")
    if reservation.read_text(encoding="utf-8", errors="replace") != token:
        raise ValueError(f"예약 토큰 불일치(위조/기저장): {path}")
    if path.exists():
        raise ValueError(f"이미 저장된 경로: {path}")
    if path.name != f"{report.id}.json":
        raise ValueError(f"report.id({report.id})와 예약 파일명({path.name}) 불일치")
    tmp = path.with_suffix(f".{token[-12:]}.tmp")             # 토큰별 tmp — 공유 tmp 레이스 방지
    tmp.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    validator = Path(__file__).resolve().parents[2] / "scripts" / "validate_market_report.py"
    checked = subprocess.run(
        [sys.executable, str(validator), str(tmp)],
        cwd=str(validator.parent.parent),
        text=True,
        capture_output=True,
        check=False,
    )
    if checked.returncode != 0:
        tmp.unlink(missing_ok=True)
        detail = (checked.stderr or checked.stdout or "unknown contract failure").strip()
        raise ValueError(f"OpenAPI 저장 계약 검증 실패: {detail}")
    os.replace(tmp, path)
    reservation.unlink(missing_ok=True)
    return path


def load_prev_cards(root: Path, exclude_id: str) -> dict:
    """직전 회차 axes 리포트의 정상 카드 요약 — {topicKey: {id, generatedAt, title,
    watch_signals, deep_dive_topic}}. 연재 연속성용(07-28~30 5회차 연속 동일
    헤드라인 실측 — 월간 앵커는 한 달 내내 같은 델타라 직전 회차를 모르면 매번
    같은 수치가 헤드라인 주인공이 된다). 과거 예약 토큰 파일·legacy·error 카드는
    건너뛰고, 실패 시 빈 dict(연속성은 부가 기능 — 리포트 생성을 막지 않는다)."""
    def _key(stem: str):
        date, _, seq = stem.rpartition("-")
        return (date, int(seq) if seq.isdigit() else 0)

    try:
        d = root / "reports"
        stems = sorted((p.stem for p in d.glob("*.json") if p.stem != exclude_id),
                       key=_key)
        for stem in reversed(stems):
            try:
                data = json.loads((d / f"{stem}.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 예약 토큰 등 비JSON
                continue
            if not isinstance(data, dict) or data.get("format") != "axes":
                continue
            out = {}
            for c in data.get("cards") or []:
                if not isinstance(c, dict) or c.get("error"):
                    continue
                # topics_v1의 topic1/topic2는 표시 슬롯일 뿐이다. 과거 고정축은
                # topicKey가 없으므로 기존 axis 키를 유지해 하위 호환한다.
                identity = (c.get("topicKey") or c.get("axis") or "").strip()
                if not identity:
                    continue
                out[identity] = {
                    "id": data.get("id", stem),
                    "generatedAt": data.get("generatedAt", ""),
                    "title": c.get("title", ""),
                    "watch_signals": c.get("watch_signals") or [],
                    "deep_dive_topic": (c.get("deep_dive") or {}).get("topic", ""),
                }
            if out:
                return out
    except Exception:  # noqa: BLE001
        pass
    return {}


def _stage(io, items: list[str]) -> PipelineStage:
    flow = f"in {io.in_count} → out {io.out_count}"
    if io.dropped:
        flow += f" (drop {len(io.dropped)})"
    note = f"{io.note} · {flow}" if io.note else flow
    return PipelineStage(key=io.key, label=io.label, note=note,
                         items=items, io=io.model_dump())   # 전량 — 뷰어가 더보기로 접음


class _Recorder:
    """CLI 프롬프트·응답·실패를 스테이지 provenance에 빠짐없이 기록한다."""

    def __init__(self, inner, stage: str, llm_log: dict[str, list[dict]]):
        self._inner, self._stage, self._llm_log = inner, stage, llm_log

    async def run(self, prompt, instructions="", *, response_format=None, effort=None,
                  **kw):
        # **kw 투과 — Role.run 키워드(예: timeout=CLI 다리 데드라인)가 늘 때
        # 래퍼가 기록 없이 깨지는 결합을 끊는다(07-27 axes timeout 전달 실측).
        entry = {"instructions": instructions, "prompt": prompt}
        try:
            res = await self._inner.run(prompt, instructions=instructions,
                                        response_format=response_format, effort=effort,
                                        **kw)
            entry["response"] = (res.model_dump() if hasattr(res, "model_dump")
                                 else str(res))
            return res
        except asyncio.CancelledError:
            entry["error"] = "cancelled"
            raise
        except Exception as exc:
            entry["error"] = str(exc).strip() or type(exc).__name__
            raise
        finally:
            self._llm_log.setdefault(self._stage, []).append(entry)


def _default_roles(overrides=None):
    from providers import Role
    fil = Role("report_filter", overrides)
    return {"filter": fil, "importance": fil, "cluster": fil,
            "deepen": Role("report_deepen", overrides),
            "synth": Role("report_synth", overrides),
            "article": Role("report_article", overrides),
            "verifier": Role("verifier", overrides),
            "cross": Role("verifier_cross", overrides)}


async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12,
                              seq: int, playbook_corpus: str = "ryze_yn",
                              roles: dict | None = None,
                              case_store=None,
                              live_research: bool | None = None,
                              report_format: str | None = None) -> Report:
    """live_research: None=자동(eff가 벽시계 2h 이내일 때만 웹 조사 — replay 가드),
    True/False=강제(테스트 주입용)."""
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

    llm_log: dict[str, list[dict]] = {}          # 스테이지별 LLM 콜 전문(투명성)

    def _role(name, stage=None):
        return _Recorder(roles.get(name) or _NoRole(), stage or name, llm_log)

    _STAGE_TIMEOUT_S = 1800    # never-hang: 스테이지당 30분 상한(3호 6시간 행 실측)

    async def _timed(coro, name, fallback, seconds=None):
        limit = seconds or _STAGE_TIMEOUT_S
        try:
            return await asyncio.wait_for(coro, limit)
        except asyncio.TimeoutError:
            errors.append(f"{name}: 스테이지 타임아웃({limit}s)")
            return fallback

    try:
        ri = assemble_report_input(store, window_hours=window_hours, now=eff)
        ri_diag_obj = ri.diagnostics
        ri_diag = ri.diagnostics.model_dump()
        raw_news, cards = ri.raw_news, ri.cards
    except Exception as exc:  # noqa: BLE001 — never-raise(B5): 진단 리포트라도 발행
        errors.append(f"input: {exc}")
        raw_news, cards, ri_diag = [], [], {"error": str(exc)}
        ri_diag_obj = None
    try:
        anchors = build_anchors(store, now=eff)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"anchors: {exc}")
        anchors = []
    def _health():
        """수집 건강 — 비어있는 것/안 온 것 가시화(GIGO 1차 방어)."""
        import collections as _c
        empty_content = sum(1 for d in raw_news if not (getattr(d, "content", "") or "").strip())
        by_src = _c.Counter((getattr(d, "source", "") or "?") for d in raw_news)
        last_ing = max((getattr(d, "ingested_at", "") or "" for d in raw_news), default="")
        late = ri_diag.get("raw_late_rescued", 0) or 0
        return {
            "raw_news_in_window": len(raw_news),
            "raw_event_in_window": len(raw_news) - late,   # 발생시각이 진짜 창 안
            "raw_late_rescued": late,                      # 창 밖 발생·창 안 수집 구제(36h 지평선)
            "raw_content_empty": empty_content,
            "raw_content_empty_pct": round(empty_content / len(raw_news) * 100, 1) if raw_news else 0,
            "raw_by_source": dict(by_src.most_common(10)),
            "raw_last_ingested": last_ing,
            "cards_in_window": len(cards),
            "anchors": len(anchors),
            "metrics_missing": list(getattr(ri_diag_obj, "metrics_missing", [])
                                    if ri_diag_obj else ri_diag.get("metrics_missing", [])),
        }

    stages.append(PipelineStage(
        key="raw", label="raw",
        sources=[{"name": f"SectorCard ({len(cards)}건)",
                  "items": [c.title for c in cards]},
                 {"name": f"SaveTicker raw ({len(raw_news)}건)",
                  "items": [d.title for d in raw_news]},
                 {"name": f"anchors ({len(anchors)}건)",
                  "items": [f"{a.anchor_id}={a.value}{a.unit} @{a.as_of} ← {a.source}"
                            for a in anchors]}],
        io=dict(ri_diag, collection_health=_health(),
                anchor_details=[a.model_dump() for a in anchors])))

    # 교차 스트림 중복 정규화(codex F7): SaveTicker 원문(id X)과 그 판정 카드(st-X)가
    # 둘 다 있으면 뉴스 쪽을 제거 — 같은 문서가 출처 2건으로 부풀지 않게
    card_ids = {c.id for c in cards}
    canon_dupes = [d for d in raw_news if f"st-{d.id}" in card_ids or d.id in card_ids]
    if canon_dupes:
        dup_ids = {d.id for d in canon_dupes}
        raw_news = [d for d in raw_news if d.id not in dup_ids]

    f1 = await _timed(filter_relevance(raw_news, cards, role=_role("filter", "f1")),
                      "f1", StageResult(output=[], io=StageIO(key="f1", label="1차 필터 — 관련성"), error="timeout"))
    if f1.error:
        errors.append(f"f1: {f1.error}")
    if canon_dupes:
        f1.io.note = ((f1.io.note + " · ") if f1.io.note else "") + \
            f"교차중복 정규화 {len(canon_dupes)}건(카드 우선)"
    stages.append(_stage(f1.io, [e.title for e in f1.output]))

    f2 = await _timed(filter_importance(f1.output, role=_role("importance", "f2"),
                                        window_hours=window_hours),
                      "f2", StageResult(output=f1.output, io=StageIO(key="f2", label="2차 필터 — 중요도"), error="timeout"))
    if f2.error:
        errors.append(f"f2: {f2.error}")
    stages.append(_stage(f2.io, [e.title for e in f2.output]))

    f3 = await _timed(cluster_events(f2.output, role=_role("cluster", "f3")),
                      "f3", StageResult(output=[], io=StageIO(key="f3", label="3차 필터 — 이벤트 dedup"), error="timeout"))
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
            from casemem.async_query import query_case_memory_async
            signals = [t for c in clusters for t in derive_topics(c, anchors)]
            rerank_role = None
            try:
                from providers import Role
                rerank_role = Role("casemem_rerank")   # 구조 정합 리랭크(Plan4-a)
            except Exception:  # noqa: BLE001 — 리랭크 불가 시 표면 매칭만
                pass
            res = await query_case_memory_async(
                case_store, signals=signals, as_of=eff.isoformat(),
                sector="memory", k=5, role=rerank_role)
            cases = [m.model_dump() for m in res.matches]
            case_diag = {"case_memory_matches": len(cases),
                         "case_memory_scanned": res.scanned,
                         "case_memory_reranked": res.rerank_used and not res.rerank_failed}
            case_ok = True
        except Exception as exc:  # noqa: BLE001
            errors.append(f"case_memory: {exc}")
    if not case_ok:
        seams.append("case_memory")     # 질의 실패/미주입이면 seam 유지(SF2 — 정직 표기)

    # ── v2 3축 카드 분기 (2026-07-24 재설계) — 매크로/메모리/그 외 카드 3장.
    # legacy(주장→완결 글) 경로는 REPORT_FORMAT=legacy 롤백용으로 유지.
    from app.settings import settings as _settings_axes
    fmt = (report_format or _settings_axes.report_format or "axes").strip().lower()
    if fmt == "axes":
        from sector.report_article import audit_article
        from sector.report_axes import run_axes_flow
        try:
            from sector.report_macro import macro_brief
            macro_block, macro_hot = macro_brief(store, cutoff=eff)
        except Exception:  # noqa: BLE001
            macro_block, macro_hot = "", []
        _live = (live_research if live_research is not None
                 else (datetime.now(timezone.utc) - eff) < timedelta(hours=2))
        # F1 이전의 원시 후보를 전체 provenance와 함께 보존한다. 제목만 넘기면
        # selector가 복구한 후보가 후검증에서 근거 없는 주제로 강등되고, 신선도와
        # 출처 품질을 실제로 비교할 수도 없다.
        raw_candidates = [EvidenceRef(
            kind="news", id=d.id, title=d.title, ts=d.created_at,
            excerpt=d.content or "", source=d.source or "", url=d.url or "")
            for d in raw_news[-60:] if d.title]
        # 연재 연속성 — 직전 회차 카드를 축별 pheno에 주입(같은 주제 지속 시
        # 제목·수치 재탕 대신 '달라진 것' 중심으로)
        kst_date_axes = eff.astimezone(_KST).strftime("%Y-%m-%d")
        prev_cards = load_prev_cards(store.root, exclude_id=f"{kst_date_axes}-{seq}")
        axis_cards, axes_errors, lead_axis = await run_axes_flow(
            clusters=clusters, anchors=anchors, macro_block=macro_block,
            f2_titles=[e.title for e in raw_candidates],
            raw_candidates=raw_candidates, cases=cases,
            role_factory=lambda st: _role("article", st),
            model=_settings_axes.model_claude, eff=eff, live_research=_live,
            stage_cb=lambda sr, items: stages.append(_stage(sr.io, items)),
            prev_cards=prev_cards)
        errors.extend(axes_errors)
        # 수치 스윕 — 라벨·앵커·연구 어디에도 없는 수치에 ⚠각주(정직성 게이트).
        # 신뢰 풀은 '근거' 라벨 연구만(가정 라벨 답변을 넣으면 미확인 수치가 경고를
        # 우회 — codex r2 M1). 현상·시나리오·전이·재무·연구 결론 전부 스윕(r2 H5).
        extra = [getattr(m, "excerpt", "") or "" for c in clusters
                 for m in list(getattr(c, "members", []))]
        extra += [str(f.get("answer", "")) for c in axis_cards
                  for f in (c.deep_dive.get("findings") or [])
                  if f.get("label") == "근거"]

        calc_bad: list[str] = []

        def _sweep(txt: str) -> str:
            try:
                out, _ = audit_article(txt, anchors, extra, [])
                # 계산 라벨 재계산 — 스윕이 저자 선언으로 면제하는 유일한 통로 검증
                from sector.report_article import audit_calc_labels
                out, bad = audit_calc_labels(out)
                calc_bad.extend(bad)
                return out
            except Exception as exc:  # noqa: BLE001
                errors.append(f"sweep: {exc}")
                return txt

        for c in axis_cards:
            if c.phenomenon:
                c.phenomenon = _sweep(c.phenomenon)
            if c.deep_dive.get("conclusion"):
                c.deep_dive["conclusion"] = _sweep(c.deep_dive["conclusion"])
            for s in c.scenarios:
                s.thesis = _sweep(s.thesis)
                for b in s.beneficiaries:
                    if b.rationale:
                        b.rationale = _sweep(b.rationale)
                    if b.financials:
                        b.financials = _sweep(b.financials)

        # 영구 읽기 계층 — 수동 JSON overlay가 아니라 정규 topics_v1 산출물의
        # 같은 id에 editorial + 카드별 brief를 붙인다. CLI/검증 실패도 감사된
        # 카드에서만 만든 결정적 폴백으로 강등해 발행 자체는 막지 않는다.
        from sector.report_readability import (fallback_report_readability,
                                               generate_report_readability)
        kst = eff.astimezone(_KST)
        report_id = f"{kst.strftime('%Y-%m-%d')}-{seq}"
        generated_at = kst.isoformat()
        fallback_readability = fallback_report_readability(
            report_id=report_id, generated_at=generated_at,
            lead_axis=lead_axis, cards=axis_cards)
        readability = await _timed(
            generate_report_readability(
                report_id=report_id, generated_at=generated_at,
                lead_axis=lead_axis, cards=axis_cards,
                role=_role("article", "readability"),
                audit_role=_role("cross", "readability")),
            "readability",
            StageResult(
                output=fallback_readability,
                io=StageIO(key="readability", label="읽기 편집",
                           note="결정적 폴백 · timeout",
                           in_count=len(axis_cards), out_count=3),
                error="timeout"),
            seconds=1200)
        if readability.error:
            message = f"readability: {readability.error}"
            timed_out = (readability.error == "timeout"
                         and any(item.startswith("readability: 스테이지 타임아웃")
                                 for item in errors))
            if not timed_out and message not in errors:
                errors.append(message)
        reading_layer = readability.output
        for card in axis_cards:
            card.brief = reading_layer.briefs.get(card.axis)
            for scenario in card.scenarios:
                for index, beneficiary in enumerate(scenario.beneficiaries):
                    beneficiary.readerCopy = reading_layer.beneficiaryCopies[
                        f"{card.axis}:{scenario.polarity}:{index}"]
        stages.append(_stage(
            readability.io,
            [reading_layer.editorial.headline]
            + [reading_layer.briefs[axis].headline for axis in ("macro", "topic1", "topic2")],
        ))
        for st in stages:
            if st.key in llm_log:
                st.io = dict(st.io or {}, llm_calls=llm_log[st.key])
        ok_cards = [c for c in axis_cards if not c.error]
        title_card = next((c for c in axis_cards if c.axis == lead_axis), None)
        # 강등 표기 — 축 스테이지 실패(특히 axis_split)가 publish_status=ok 뒤에
        # 무표시로 숨는 구멍(codex 시스템 리뷰). 재시도로 살아난 건 제외하고
        # 끝까지 남은 실패만: axis_split(전 카드가 축 배정 없이 생성) + error 카드
        degraded_set = {f"card_{c.axis}" for c in axis_cards if c.error}
        if any(e.startswith("axis_split") for e in axes_errors):
            degraded_set.add("axis_split")
        degraded_axes = sorted(degraded_set)
        report = Report(
            id=report_id, seq=seq,
            generatedAt=generated_at,
            title=(title_card.title if title_card
                   else f"3축 시황 (전 축 실패) — {kst.strftime('%m-%d %H:%M')}"),
            window={"from": (eff - timedelta(hours=window_hours)).astimezone(_KST).isoformat(),
                    "to": kst.isoformat()},
            overview=("⚠ 강등 모드: " + ", ".join(degraded_axes) + " 실패 — 카드 일부는 "
                      "축 배정·시나리오 없이 생성" if degraded_axes else ""),
            finalOpinion=FinalOpinion(text="3축 카드 참조", confidence="낮"),
            claims=[], pipeline=ReportPipeline(stages=stages),
            diagnostics={"stage_errors": errors, "seams_empty": seams,
                         "degraded": degraded_axes,
                         "readability": {
                             "mode": reading_layer.mode,
                             "error": readability.error or "",
                         },
                         "calc_mismatches": list(dict.fromkeys(calc_bad)),
                         "rejected_claims": [], "macro_hot": macro_hot, **case_diag},
            publish_status="ok" if ok_cards else "hold",
            format="axes", axisModel="topics_v1", leadAxis=lead_axis,
            readerModel="brief_v1",
            editorial=reading_layer.editorial, cards=axis_cards)
        return report

    dp = await _timed(deepen(clusters, rules, anchors, cases=cases, role=_role("deepen", "deepen")),
                      "deepen", StageResult(output="", io=StageIO(key="deepen", label="심화"), error="timeout"),
                      seconds=1500)   # effort medium 강하와 함께 실패 비용 축소(-1·-2호 연속 타임아웃)
    if dp.error:
        errors.append(f"deepen: {dp.error}")
    stages.append(_stage(dp.io, [r["slug"] for r in rules]
                         + [f"case:{c.get('episode_id')}" for c in cases]))

    sy = await _timed(synthesize_claims(dp.output, clusters, anchors, rules, cases=cases,
                                        role=_role("synth", "synth")),
                      "synth", StageResult(output=[], io=StageIO(key="synth", label="합성"), error="timeout"))
    if sy.error:
        errors.append(f"synth: {sy.error}")
    stages.append(_stage(sy.io, [c.title for c in sy.output]))

    vf = await _timed(verify_claims(sy.output, anchors, clusters, cutoff=eff,
                                    verifier=_role("verifier", "verify"),
                                    cross=_role("cross", "verify")),
                      "verify", StageResult(output=[], io=StageIO(key="verify", label="검증"), error="timeout"))
    if vf.error:
        errors.append(f"verify: {vf.error}")
    vstage = _stage(vf.io, [f"{v.claim_id}:{v.status}" for v in vf.output])
    vstage.io = dict(vstage.io or {},
                     verdicts=[v.model_dump() for v in vf.output])  # 사유 직렬화(SF7)
    stages.append(vstage)

    # REFLECT 라운드(최대 1회): 반증당한 주장을 수정시켜 재검증 — 반증 흡수(6호 실측:
    # A2가 정당한 논리 비판을 하는데 되먹임이 없어 항상 보류로 종결)
    final_claims, final_verdicts = sy.output, vf.output
    if any(v.status == "unverified" and v.reasons for v in vf.output):
        rv = await _timed(revise_claims(sy.output, vf.output, clusters, anchors, rules,
                                        cases=cases, role=_role("synth", "revise")),
                          "revise", StageResult(output=sy.output,
                                                io=StageIO(key="revise", label="수정"),
                                                error="timeout"))
        if rv.error:
            errors.append(f"revise: {rv.error}")
        stages.append(_stage(rv.io, [c.title for c in rv.output]))
        if rv.output is not sy.output:
            vf2 = await _timed(verify_claims(rv.output, anchors, clusters, cutoff=eff,
                                             verifier=_role("verifier", "verify2"),
                                             cross=_role("cross", "verify2")),
                               "verify2", StageResult(output=[],
                                                      io=StageIO(key="verify2", label="재검증"),
                                                      error="timeout"))
            if vf2.error:
                errors.append(f"verify2: {vf2.error}")
            v2stage = _stage(vf2.io, [f"{v.claim_id}:{v.status}" for v in vf2.output])
            v2stage.io = dict(v2stage.io or {},
                              verdicts=[v.model_dump() for v in vf2.output])
            stages.append(v2stage)
            final_claims, final_verdicts = rv.output, vf2.output

    # ── Phase 4: 드래프트 → 추가 조사(웹) → 완결 글 (2026-07-23 사용자) ──
    # 전 단계 never-raise — 어떤 실패든 article 없이 기존 리포트로 강등.
    article_text, article_meta, article_headline = "", {}, ""
    article_audit_ok, article_safe_title = False, ""
    forced_hold = False
    hold = not any(v.status == "verified" for v in final_verdicts)
    try:
        from sector.report_article import (_SemanticAuditOut, audit_article, audit_semantics,
                                           compose_article, draft_skeleton,
                                           headline_from_article, run_research)
        from sector.report_contracts import ArticleDraft
        # F1/F3(2026-07-24): 거시 관측 브리프 — 중요도 게이트 통과분은 팩트로 강제
        try:
            from sector.report_macro import macro_brief
            macro_block, macro_hot = macro_brief(store, cutoff=eff)
        except Exception:  # noqa: BLE001
            macro_block, macro_hot = "", []
        dr = await _timed(draft_skeleton(final_claims, final_verdicts, clusters, anchors,
                                         cases, role=_role("article", "draft"),
                                         macro_block=macro_block),
                          "draft", StageResult(output=ArticleDraft(core_question=""),
                                               io=StageIO(key="draft", label="드래프트"),
                                               error="timeout"),
                          seconds=2400)   # Claude CLI 600s 실패 후 Codex CLI 폴백 여유 —
                                          # 1800s로는 다음 레그가 잘려 article 통째 강등
        if dr.error:
            errors.append(f"draft: {dr.error}")
        stages.append(_stage(dr.io, [q.question for q in dr.output.research_questions]))
        findings = []
        # replay 가드(codex P4 B3): eff가 벽시계보다 2h 이상 과거면 live 웹 조사가
        # 미래 정보를 흡수 — 조사 생략(과거 재실행은 article 미생성 강등)
        _live = (live_research if live_research is not None
                 else (datetime.now(timezone.utc) - eff) < timedelta(hours=2))
        if dr.output.research_questions and not dr.error and _live:
            from app.settings import settings as _settings
            rs = await _timed(run_research(dr.output.research_questions,
                                           model=_settings.model_claude, now=eff),
                              "research", StageResult(output=[],
                                                      io=StageIO(key="research",
                                                                 label="추가 조사"),
                                                      error="timeout"),
                              seconds=2400)
            if rs.error:
                errors.append(f"research: {rs.error}")
            findings = rs.output
            rstage = _stage(rs.io, [f"{f.qid}: {(f.answer or f.error)[:120]}" for f in findings])
            rstage.io = dict(rstage.io or {},
                             findings=[f.model_dump() for f in findings])   # 출처 포함 전문
            stages.append(rstage)
        elif dr.output.research_questions and not _live:
            errors.append("research: replay 가드 — eff가 과거라 웹 조사 생략")
        sourced = sum(1 for f in findings if f.label == "근거" and not f.error)
        # A1(2026-07-24 리뷰): 조사 흡수 — 조사가 주장 전제를 반박/지지하면 되먹여
        # 수정하고 재검증. 이전엔 verify가 research보다 앞이라 되먹임이 없었다
        # (실측: q4가 c1의 CapEx 둔화 전제를 반박했는데 c1이 그대로 실림).
        ok_findings = [f for f in findings if not f.error]
        if ok_findings and final_claims:
            rv2 = await _timed(revise_claims(final_claims, final_verdicts, clusters,
                                             anchors, rules, cases=cases,
                                             findings=ok_findings,
                                             role=_role("synth", "revise2")),
                               "revise2", StageResult(output=final_claims,
                                                      io=StageIO(key="revise2",
                                                                 label="수정 — 조사 흡수"),
                                                      error="timeout"))
            if rv2.error:
                errors.append(f"revise2: {rv2.error}")
            stages.append(_stage(rv2.io, [c.title for c in rv2.output]))
            if rv2.output is not final_claims:
                vf3 = await _timed(verify_claims(rv2.output, anchors, clusters, cutoff=eff,
                                                 verifier=_role("verifier", "verify3"),
                                                 cross=_role("cross", "verify3")),
                                   "verify3", StageResult(output=[],
                                                          io=StageIO(key="verify3",
                                                                     label="재검증 — 조사 반영"),
                                                          error="timeout"))
                if vf3.error:
                    errors.append(f"verify3: {vf3.error}")
                vf3.io.key, vf3.io.label = "verify3", "재검증 — 조사 반영"
                v3stage = _stage(vf3.io, [f"{v.claim_id}:{v.status}" for v in vf3.output])
                v3stage.io = dict(v3stage.io or {},
                                  verdicts=[v.model_dump() for v in vf3.output])
                stages.append(v3stage)
                if vf3.output or not rv2.output:   # 수정기가 전량 폐기한 것도 채택
                    final_claims, final_verdicts = rv2.output, vf3.output
                elif vf3.error:
                    # 재검증 실패 시 이전 verified를 낙관적으로 신뢰하면 hold 우회
                    # (codex 리뷰 H2) — 보수적으로 이번 회차는 hold 강제
                    forced_hold = True
        # A2: 검증 통과 주장 0건 = hold — 제목·결론 단정 금지(compose 제약 + 제목 게이트)
        hold = (not any(v.status == "verified" for v in final_verdicts)) or forced_hold
        # 추가 수집은 필수(사용자) — 출처 있는 조사 0건이면 완결 글 강등(codex P4 M1)
        if dr.output.core_question and sourced > 0:
            cp = await _timed(compose_article(dr.output, findings, final_claims,
                                              final_verdicts, clusters, anchors, cases,
                                              role=_role("article", "compose"), hold=hold,
                                              macro_block=macro_block),
                              "compose", StageResult(output="",
                                                     io=StageIO(key="compose",
                                                                label="완결 글"),
                                                     error="timeout"),
                              seconds=2400)   # draft와 동일 사유 — CLI 폴백 여유
            if cp.error:
                errors.append(f"compose: {cp.error}")
            stages.append(_stage(cp.io, ([headline_from_article(cp.output)]
                                         if cp.output.strip() else [])))
            if cp.output.strip():
                extra = [getattr(m, "excerpt", "") or "" for c in clusters
                         for m in list(getattr(c, "members", []))]
                extra += [e for cl in final_claims for e in cl.evidence]
                article_text, unverified = audit_article(cp.output, anchors, extra, findings)
                article_headline = headline_from_article(article_text)
                article_meta = {
                    "core_question": dr.output.core_question,
                    "governing_equation": dr.output.governing_equation,
                    "skeleton": dr.output.skeleton,
                    "research_ok": sum(1 for f in findings if not f.error),
                    "research_sourced": sourced,
                    "research_failed": sum(1 for f in findings if f.error),
                    "unverified_numbers": unverified,
                    "macro_hot": macro_hot,        # ⚠중요 게이트 통과 거시 항목
                }
                # A4: 의미론 감사 — 제목·결론이 검증 범위 안인가. 실패/위반이면
                # 제목 게이트가 안전 제목으로 폴백(아래 조립부)
                sa = await _timed(audit_semantics(article_text, final_claims,
                                                  final_verdicts, hold=hold,
                                                  role=_role("article", "semantic_audit")),
                                  "semantic_audit",
                                  StageResult(output=_SemanticAuditOut(ok=False),
                                              io=StageIO(key="semantic_audit",
                                                         label="의미론 감사"),
                                              error="timeout"))
                if sa.error:
                    errors.append(f"semantic_audit: {sa.error}")
                stages.append(_stage(sa.io, (sa.output.problems if sa.output else [])))
                article_audit_ok = bool(sa.output and sa.output.ok)
                article_safe_title = ((sa.output.safe_title or "").strip()
                                      if sa.output else "")
                article_meta["semantic_audit"] = {
                    "ok": article_audit_ok,
                    "problems": list(sa.output.problems) if sa.output else [],
                }
        elif dr.output.core_question:
            errors.append("compose: 출처 있는 추가 조사 0건 — 완결 글 강등")
    except Exception as exc:  # noqa: BLE001 — Phase 4 어떤 예외도 리포트를 못 죽인다
        errors.append(f"article: {exc}")

    # LLM 콜 전문을 각 스테이지 io에 부착 — 프롬프트/사고 과정 투명(2026-07-22 사용자)
    for st in stages:
        if st.key in llm_log:
            st.io = dict(st.io or {}, llm_calls=llm_log[st.key])

    try:
        report = assemble_report(final_claims, final_verdicts, stages=stages, now=eff,
                                 window_hours=window_hours, seq=seq,
                                 title=f"메모리 반도체 {window_hours}시간 시황",
                                 stage_errors=errors, seams_empty=seams)
        report.diagnostics.update(case_diag)
        # A2: 발행 상태 — 검증 통과 주장 있어야 ok (제목·UI가 이 상태를 따른다).
        # forced_hold: 조사 반영 재검증(verify3) 실패 시 보수적 hold(codex H2)
        report.publish_status = ("ok" if (any(v.status == "verified"
                                              for v in final_verdicts)
                                          and not forced_hold) else "hold")
        if article_text:
            report.article = article_text
            report.article_meta = article_meta
            # A3+A4 제목 게이트: 글 제목은 의미론 감사를 통과했을 때만 헤드라인 승격.
            # 위반이면 감사가 준 안전 제목, 그것도 없으면 조립기 제목 유지(단정 방지)
            if article_headline and article_audit_ok:
                report.title = article_headline
            elif article_safe_title:
                report.title = article_safe_title + (" (미검증)" if hold else "")
        return report
    except Exception as exc:  # noqa: BLE001 — 최후 안전망: 진단만 담은 리포트
        from datetime import timedelta as _td
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


def infra_wiped(report: Report) -> bool:
    """주장 0개 + LLM 전 공급자 실패 = 인프라 전멸(2026-07-23 04:39 DNS 다운 실측).

    주장이 하나라도 있으면(전부 미검증이어도) 게이트가 일한 것 — 정상 종료.
    axes(v2) 리포트는 claims가 없으므로 카드 기준(codex r1 H3 — claims 기준을
    그대로 쓰면 모든 axes 회차가 인프라 전멸로 오판돼 재시도)."""
    if report.format == "axes":
        if any(not c.error for c in report.cards):
            return False
        errors = report.diagnostics.get("stage_errors", [])
        return any("all providers failed" in e for e in errors)
    if report.claims:
        return False
    errors = report.diagnostics.get("stage_errors", [])
    return any("all providers failed" in e for e in errors)


def main(argv: list[str]) -> int:
    import argparse
    import logging
    # 스케줄러가 stdout/stderr를 report-pipeline.log로 보존한다 — cli_run 계측
    # (모델·elapsed·성패)이 여기 안 찍히면 타임아웃 원인 규명이 불가(07-27 실측)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
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
    async def _run():
        # SIGTERM → 태스크 취소: 각 스테이지의 CancelledError 정리 경로가 CLI
        # 프로세스그룹까지 죽인다(스케줄러 하드캡 우아 종료 — codex P4 B2)
        import signal as _sig
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        try:
            loop.add_signal_handler(_sig.SIGTERM, task.cancel)
        except (NotImplementedError, RuntimeError):
            pass
        return await run_report_pipeline(
            store, now=now, window_hours=args.window, seq=seq,
            case_store=case_store)
    report = asyncio.run(_run())                               # ② 실행(순수)
    save_report(report, path, token)                           # ③ 예약 경로에 저장(토큰 대조)
    print(report.id)
    # 기록은 남기되 종료코드로 실패를 알린다 — 스케줄러가 재시도 판단
    return 2 if infra_wiped(report) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
