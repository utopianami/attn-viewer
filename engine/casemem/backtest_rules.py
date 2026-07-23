"""규칙 후보 백테스트 v2 (Plan 5 1단계) — 사례 국면 시퀀스와 2단계 대조.

§7 + codex 교차리뷰(2026-07-23) 반영 하드 가드레일:
- **2단계 판정(선택 편향 차단)**: A단계는 트리거만(귀결 connection 미제공, 전 국면 제시),
  B단계는 트리거 국면 **이후** 국면만 제시하고 귀결을 판정 — 결과를 보고 트리거를
  고르는 경로를 구조적으로 차단.
- **마스킹 다이제스트**: 사례 id·제목·날짜·사후 국면 라벨(crash 등) 제거, 익명 키(E01…).
  판정 LLM의 파라메트릭 역사지식 누수를 줄인다(완전 제거는 불가 — 가설 등급에 머무는 이유).
- **인용=국면 귀속**: 트리거 국면은 LLM 주장이 아니라 **인용이 실재하는 국면**을 코드가
  역산. 인용은 정규화 10자 이상 + 해당 구간 원문대조(환각 폐기).
- **커버리지 강제(fail-open 차단)**: A단계 응답이 전 사례를 정확히 1회씩 다루지 않으면
  그 규칙은 승격 불가(coverage_ok=False).
- **출처 사례 제외(순환 차단)**: provenance/evidence에서 유래 사례를 결정적으로 뽑아
  지지 집계에서 제외(out_supports). 반증은 출처 사례여도 유효.
- 확신도·승격은 코드 집계: coverage_ok ∧ out_supports≥2 ∧ contradicts=0 →
  historically_supported. 리포트 주입 자격(holdout_passed)은 불변 — 이건 가설 서열화다.

실행:
  드라이런:  .venv/bin/python -m casemem.backtest_rules [--limit N] [--json 경로]
  반영:      .venv/bin/python -m casemem.backtest_rules --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.store import CaseStore

_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "case_memory"
_RULES = _ROOT / "rules.jsonl"
_RUNLOG = _ROOT / "rules_backtest.jsonl"          # append-only 실행 기록
_SECTORS = ("memory", "finance", "tech")
_MIN_SUPPORTS = 2                                  # 출처 제외 독립 지지 문턱
_MIN_QUOTE = 10                                    # 정규화 후 최소 인용 길이
_EP_ID = re.compile(r"(?:mem|fin)-[a-z0-9-]+")


class _TrigVerdict(BaseModel):
    model_config = {"extra": "forbid"}
    episode_key: str                               # E01…
    triggered: bool
    quote: str = ""                                # 트리거 근거 — 국면 신호 원문 인용


class _TrigOut(BaseModel):
    model_config = {"extra": "forbid"}
    verdicts: list[_TrigVerdict] = Field(default_factory=list)


class _OutVerdict(BaseModel):
    model_config = {"extra": "forbid"}
    episode_key: str
    outcome: Literal["followed", "contradicted", "unclear"] = "unclear"
    quote: str = ""                                # 귀결 근거 — 이후 국면 원문 인용


class _OutOut(BaseModel):
    model_config = {"extra": "forbid"}
    verdicts: list[_OutVerdict] = Field(default_factory=list)


def _norm(t: str) -> str:
    return " ".join(str(t).split())


class MaskedCases:
    """익명 키 ↔ 사례 매핑 + 마스킹 국면 라인(신호만)."""

    def __init__(self, store: CaseStore, sectors=_SECTORS):
        eps = []
        for sector in sectors:
            eps.extend(store.read_episodes(sector=sector))
        eps.sort(key=lambda e: e.id)               # 결정적 키 부여
        self.key_to_id: dict[str, str] = {}
        self.phases: dict[str, list[tuple[int, str]]] = {}   # key → [(order, 신호라인)]
        self.evidence: dict[str, dict[int, str]] = {}        # key → {order: 근거 인용}
        for i, ep in enumerate(eps, 1):
            key = f"E{i:02d}"
            self.key_to_id[key] = ep.id
            self.phases[key] = [
                (p.order, _norm(" / ".join(p.identifying_signals)))
                for p in sorted(ep.phases, key=lambda x: x.order)]
            self.evidence[key] = {
                p.order: _norm(" / ".join(e.quote[:200] for e in p.evidence[:4]))
                for p in ep.phases}

    def digest(self, key: str, *, after: int | None = None,
               with_evidence: bool = False) -> str:
        """마스킹 다이제스트 — after 지정 시 그 국면 이후만(B단계용).

        with_evidence: 국면별 근거 인용 포함 — B단계 판정 가능성 확보용.
        트리거 이후 자료라 룩어헤드 아님(A단계엔 절대 미포함 — 선택 편향 가드 유지)."""
        lines = [f"사례 {key}"]
        for order, sig in self.phases[key]:
            if after is not None and order <= after:
                continue
            lines.append(f"국면{order}: {sig}")
            if with_evidence and self.evidence[key].get(order):
                lines.append(f"국면{order} 근거: {self.evidence[key][order]}")
        return "\n".join(lines)

    def all_digest(self) -> str:
        return "\n\n".join(self.digest(k) for k in sorted(self.phases))

    def locate_quote(self, key: str, quote: str) -> int | None:
        """인용이 실재하는 국면 order — 트리거 국면은 이걸로 확정(주장 불신)."""
        q = _norm(quote)
        if len(q) < _MIN_QUOTE:
            return None
        for order, sig in self.phases.get(key, []):
            if q in sig:
                return order
        return None

    def max_order(self, key: str) -> int:
        return max((o for o, _ in self.phases.get(key, [])), default=0)


def source_episode_ids(rule: dict, masked: MaskedCases,
                       episode_evidence: dict[str, str]) -> set[str]:
    """규칙의 유래 사례 — provenance 명시 id + evidence 인용이 사례 근거와 겹치는 것."""
    out = set(_EP_ID.findall(rule.get("provenance", "")))
    for ev in rule.get("evidence", []) or []:
        q = _norm(ev.get("quote", ""))
        if len(q) < _MIN_QUOTE:
            continue
        for ep_id, hay in episode_evidence.items():
            if q in hay:
                out.add(ep_id)
    return out


_INSTR_TRIG = """너는 투자 규칙 백테스트의 1단계(트리거 탐지) 판정자다.
규칙의 상황·트리거와, 익명화된 과거 사례들의 국면별 관찰 신호가 주어진다.
각 사례에 대해: 규칙의 트리거/상황이 어느 국면 신호에서 명확히 관찰되면 triggered=true,
quote에 그 국면 신호 문구를 **그대로**(변형 금지) 짧게 인용하라. 억지 매칭 금지 —
명확할 때만 true. **모든 사례에 대해 정확히 하나씩** verdict를 내라(해당 없으면 false).
제공된 신호 텍스트만 근거로 판단하고, 네가 아는 역사 지식으로 채우지 마라."""

_INSTR_OUT = """너는 투자 규칙 백테스트의 2단계(귀결 판정) 판정자다.
규칙의 귀결(connection)과, 각 사례에서 트리거가 관찰된 **이후 국면들의** 신호만 주어진다.
각 사례에 대해: 이후 국면에서 귀결이 실제로 전개됐으면 followed, 명백히 반대로
전개됐으면 contradicted, 판단이 어려우면 unclear. quote에 근거 문구를 **그대로** 인용.
제공된 텍스트만 근거로 판단하라. 모든 사례에 대해 verdict를 내라."""


def _stage_a_parse(raw_a, masked: MaskedCases,
                   keys: list[str]) -> tuple[bool, dict[str, int]]:
    """커버리지 검사(전 사례 정확히 1회 — 코덱스 F3) + 인용 실재 국면 역산."""
    coverage_ok = sorted(v.episode_key for v in raw_a) == keys
    triggered: dict[str, int] = {}
    for v in raw_a:
        if not v.triggered or v.episode_key not in masked.phases:
            continue
        order = masked.locate_quote(v.episode_key, v.quote)   # 주장 불신, 인용 역산
        if order is None:
            coverage_ok = False                    # 환각 인용 → 판정 불신뢰
            continue
        triggered[v.episode_key] = order
    return coverage_ok, triggered


async def backtest_rule(rule: dict, masked: MaskedCases, role,
                        sources: set[str] | None = None) -> dict:
    """규칙 1개 — A단계(트리거, connection 미제공) → B단계(이후 국면만). never-raise."""
    keys = sorted(masked.phases)
    prompt_a = (f"[규칙]\nsituation: {rule.get('situation', '')}\n"
                f"triggers: {json.dumps(rule.get('triggers', []), ensure_ascii=False)}\n\n"
                f"위 트리거를 아래 사례들과 대조하라. 사례 키 전체 목록: "
                f"{', '.join(keys)} — 각각 정확히 하나의 verdict.")
    coverage_ok, triggered = False, {}
    for _attempt in range(2):                      # 커버리지 미달 시 1회 재시도
        try:
            res_a = await role.run(prompt_a, instructions=_INSTR_TRIG,
                                   response_format=_TrigOut,
                                   cache_prefix="[사례 다이제스트]\n\n" + masked.all_digest())
            raw_a = res_a.verdicts if isinstance(res_a, _TrigOut) else \
                _TrigOut.model_validate(res_a).verdicts
        except Exception as exc:  # noqa: BLE001 — fail-closed
            return {"rule_id": rule["id"], "ok": False, "coverage_ok": False,
                    "error": f"A단계: {exc}", "verdicts": []}
        coverage_ok, triggered = _stage_a_parse(raw_a, masked, keys)
        if coverage_ok:
            break

    # B단계 대상: 트리거 국면 뒤에 국면이 남아있는 사례만 (마지막 국면 → unclear)
    judgeable = {k: o for k, o in triggered.items() if o < masked.max_order(k)}
    outcomes: dict[str, tuple[str, str]] = {
        k: ("unclear", "") for k in triggered}     # 기본 unclear(보수)
    b_rejected = 0                                 # 인용 불량으로 기각된 판정(관측성)

    if judgeable:
        sections = "\n\n".join(
            f"[사례 {k} — 트리거 이후 전개]\n"
            f"{masked.digest(k, after=o, with_evidence=True)}"
            for k, o in sorted(judgeable.items()))
        prompt_b = (f"[규칙의 귀결]\nsituation: {rule.get('situation', '')}\n"
                    f"connection: {rule.get('connection', '')}\n\n{sections}")
        try:
            res_b = await role.run(prompt_b, instructions=_INSTR_OUT,
                                   response_format=_OutOut)
            raw_b = res_b.verdicts if isinstance(res_b, _OutOut) else \
                _OutOut.model_validate(res_b).verdicts
            for v in raw_b:
                if v.episode_key not in judgeable:
                    continue
                if v.outcome == "unclear":
                    outcomes[v.episode_key] = ("unclear", v.quote)
                    continue
                q = _norm(v.quote)
                hay = _norm(masked.digest(v.episode_key,
                                          after=judgeable[v.episode_key],
                                          with_evidence=True))
                if len(q) >= _MIN_QUOTE and q in hay:          # 이후 구간 원문대조
                    outcomes[v.episode_key] = (v.outcome, v.quote)
                else:
                    b_rejected += 1
                # 인용 불량 → 기본 unclear 유지(보수 — followed/contradicted 미인정)
        except Exception:  # noqa: BLE001 — B단계 실패 → 전부 unclear(보수)
            pass

    sources = sources or set()
    verdicts = []
    for k, order in sorted(triggered.items()):
        ep_id = masked.key_to_id[k]
        oc, quote = outcomes[k]
        verdicts.append({"episode_id": ep_id, "trigger_phase": order,
                         "outcome": oc, "quote": quote,
                         "is_source": ep_id in sources})
    return {"rule_id": rule["id"], "ok": True, "coverage_ok": coverage_ok,
            "b_rejected": b_rejected, "verdicts": verdicts}


def aggregate(result: dict) -> dict:
    vs = result.get("verdicts", [])
    supports = [v for v in vs if v["outcome"] == "followed"]
    return {
        "fired": len(vs),
        "supports": len(supports),
        "out_supports": sum(1 for v in supports if not v.get("is_source")),
        "contradicts": sum(1 for v in vs if v["outcome"] == "contradicted"),
        "unclear": sum(1 for v in vs if v["outcome"] == "unclear"),
        "coverage_ok": bool(result.get("ok") and result.get("coverage_ok")),
    }


def decide_status(t: dict) -> str:
    """코드 집계 승격 — LLM 자가확신도 없음(§7)."""
    if t["coverage_ok"] and t["out_supports"] >= _MIN_SUPPORTS \
            and t["contradicts"] == 0:
        return "historically_supported"
    if t["coverage_ok"] and t["contradicts"] >= 2 \
            and t["contradicts"] > t["supports"]:
        return "historically_contradicted"
    return "candidate"


async def run_backtest(rules: list[dict], masked: MaskedCases, role,
                       sources_by_rule: dict[str, set[str]],
                       concurrency: int = 4) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(rule):
        nonlocal done
        async with sem:
            r = await backtest_rule(rule, masked, role,
                                    sources=sources_by_rule.get(rule["id"]))
        done += 1
        t = aggregate(r)
        print(f"[{done}/{len(rules)}] {r['rule_id']}: fired={t['fired']} "
              f"+{t['supports']}(독립 {t['out_supports']}) -{t['contradicts']} "
              f"?{t['unclear']}{'' if t['coverage_ok'] else '  [커버리지 실패]'}",
              flush=True)
        return r

    return list(await asyncio.gather(*(one(r) for r in rules)))


def _apply(rules: list[dict], results: dict[str, dict], run_at: str) -> int:
    """rules.jsonl status·backtest 주석 갱신(원자 교체) + 실행 기록 append."""
    import os
    changed = 0
    lines = []
    for r in rules:
        res = results.get(r["id"])
        if res is not None:
            t = aggregate(res)
            new_status = decide_status(t)
            if r.get("status") == "holdout_passed":    # 상위 등급 강등 금지
                new_status = "holdout_passed"
            if new_status != r.get("status"):
                changed += 1
            r = dict(r, status=new_status,
                     backtest=dict(t, run_at=run_at,
                                   episodes={v["episode_id"]:
                                             v["outcome"] + ("(출처)" if v["is_source"] else "")
                                             for v in res["verdicts"]}))
        lines.append(json.dumps(r, ensure_ascii=False))
    tmp = _RULES.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, _RULES)
    with _RUNLOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"run_at": run_at, "results": list(results.values())},
                           ensure_ascii=False) + "\n")
    return changed


def _episode_evidence_haystacks(store: CaseStore) -> dict[str, str]:
    """사례별 근거 인용 원문 뭉치 — 규칙 evidence와 겹침 검사용."""
    out = {}
    for sector in _SECTORS:
        for ep in store.read_episodes(sector=sector):
            parts = []
            for p in ep.phases:
                parts.extend(_norm(e.quote) for e in p.evidence)
                parts.extend(_norm(s) for s in p.identifying_signals)
            out[ep.id] = " ".join(parts)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rules.jsonl에 반영")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", help="쉼표구분 rule id — 승격/강등 후보 재검용")
    ap.add_argument("--json", help="결과 저장 경로")
    args = ap.parse_args(argv)

    from providers import Role
    role = Role("rule_backtest")
    store = CaseStore(_ROOT)
    masked = MaskedCases(store)
    ep_ev = _episode_evidence_haystacks(store)
    rules = [json.loads(x) for x in _RULES.read_text(encoding="utf-8").splitlines()
             if x.strip()]
    if args.only:
        want = set(args.only.split(","))
        rules = [r for r in rules if r["id"] in want]
    if args.limit:
        rules = rules[:args.limit]
    sources_by_rule = {r["id"]: source_episode_ids(r, masked, ep_ev) for r in rules}

    results = asyncio.run(run_backtest(rules, masked, role, sources_by_rule))
    by_id = {r["rule_id"]: r for r in results}
    run_at = datetime.now(timezone.utc).isoformat()

    tally: dict[str, int] = {}
    for r in rules:
        res = by_id.get(r["id"])
        st = decide_status(aggregate(res)) if res else "판정실패"
        tally[st] = tally.get(st, 0) + 1
    print(json.dumps(tally, ensure_ascii=False))

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"run_at": run_at, "results": results,
             "sources": {k: sorted(v) for k, v in sources_by_rule.items()}},
            ensure_ascii=False, indent=2), encoding="utf-8")
    if args.apply:
        changed = _apply(rules, by_id, run_at)
        print(f"반영 완료: status 변경 {changed}건 → {_RULES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
