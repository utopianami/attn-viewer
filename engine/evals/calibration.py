"""저지 calibration — 튜닝 fixture(공개) / 봉인 metamorphic 셋(버전당 1회) 분리 (r3-B8)."""
from __future__ import annotations

import json
from pathlib import Path

_FIX = Path(__file__).parent / "fixtures" / "chain_judge"


def load_tuning_fixtures() -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted((_FIX / "tuning").glob("*.json"))]


async def run_selftest(judge_fn) -> list[str]:
    failures: list[str] = []
    for f in load_tuning_fixtures():
        res = await judge_fn(f["id"], f["answer_md"], f["rubric"], f["bundle_text"])
        if res is None:
            failures.append(f"{f['id']}: judge invalid")
            continue
        for ax, want in f["expected"].items():
            got = res.axes[ax].score
            ok = got is not None and (got == float(want) if want in (0, 1)
                                      else abs(got - want) < 0.26)
            if not ok:
                failures.append(f"{f['id']}: {ax} expected {want} got {got}")
    return failures


# ── Task 3: 봉인 metamorphic 셋 ──────────────────────────────────────────────
import hashlib
import re

_FLIPS = [("긍정적", "부정적"), ("부정적", "긍정적"), ("위협적이지 않다", "위협적이다"),
          ("위협적이다", "위협적이지 않다"), ("강하다", "약하다"), ("약하다", "강하다")]


def _flip_verdict(md: str) -> str:
    head, _, rest = md.partition("\n\n")               # 결론 절만 반전
    for a, b in _FLIPS:
        if a in head:
            return head.replace(a, b, 1) + "\n\n" + rest
    return "## 결론\n앞선 근거와 반대로 판단한다.\n\n" + rest


def _strip_countercase(md: str) -> str:
    return re.sub(r"## 위험·반대 시나리오.*", "", md, flags=re.S).strip()


def _ghost_citations(md: str) -> str:
    return re.sub(r"\[근거:[^\]]+\]", "[근거:ghost-999]", md)


def _tamper_numbers(md: str) -> str:
    """인용 span([근거:...]) 보호 후 본문 수치만 변조 (r2-B7 — 인용 ID 손상 금지)."""
    parts = re.split(r"(\[근거:[^\]]+\])", md)
    out = []
    for p in parts:
        if p.startswith("[근거:"):
            out.append(p)
        else:
            out.append(re.sub(r"[+-]?\d+(?:\.\d+)?%?",
                              lambda m: "97.3%" if "%" in m.group() else "973", p))
    return "".join(out)


TRANSFORMS = {"flip_verdict": _flip_verdict, "strip_countercase": _strip_countercase,
              "ghost_citations": _ghost_citations, "tamper_numbers": _tamper_numbers,
              "identity": lambda md: md}

_EXPECT = {"flip_verdict": ("verdict", "zero"),
           "strip_countercase": ("countercase", "zero"),
           "ghost_citations": ("evidence", "lower"),
           "tamper_numbers": ("evidence", "lower"),
           "identity": ("verdict", "same")}


def make_sealed_set(base_records: list[dict], version: str) -> list[dict]:
    """생성 시 검증 (r2-B7): base가 변형 대상(수치·countercase 절·인용)을 실제로
    포함하고 변형이 텍스트를 실제로 바꿨는지 강제 — 아니면 ValueError (다른 base 답변
    을 고르라는 뜻)."""
    sealed = []
    for rec in base_records:
        md = rec["answer_md"]
        if "## 위험·반대 시나리오" not in md:
            raise ValueError(f"{rec['id']}: countercase 절 없음 — sealed base 부적합")
        if not re.search(r"\[근거:[^\]]+\]", md):
            raise ValueError(f"{rec['id']}: 인용 없음 — sealed base 부적합")
        stripped_cites = re.sub(r"\[근거:[^\]]+\]", "", md)
        if not re.search(r"\d", stripped_cites):
            raise ValueError(f"{rec['id']}: 본문 수치 없음 — sealed base 부적합")
        for name, fn in TRANSFORMS.items():
            out_md = fn(md)
            if name != "identity" and out_md == md:
                raise ValueError(f"{rec['id']}::{name}: 변형이 텍스트를 못 바꿈")
            ax, rel = _EXPECT[name]
            sealed.append({"id": f"{rec['id']}::{name}", "base_id": rec["id"],
                           "transform": name, "answer_md": out_md,
                           "base_answer_md": md, "rubric": rec["rubric"],
                           "bundle_text": rec["bundle_text"], "version": version,
                           "expectation": {"axis": ax, "relation": rel}})
    return sealed


def sealed_hash(sealed: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sealed, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def sealed_structure_errors(sealed: list[dict]) -> list[str]:
    """구조 게이트 (r3-B6): 서로 다른 base 2개 × 변형 5종 = 정확히 10개."""
    errs = []
    bases = {s["base_id"] for s in sealed}
    if len(sealed) != 10:
        errs.append(f"sealed 셋은 정확히 10개여야 함 (현재 {len(sealed)})")
    if len(bases) != 2:
        errs.append(f"서로 다른 base 2개 필요 (현재 {len(bases)})")
    for b in bases:
        got = {s["transform"] for s in sealed if s["base_id"] == b}
        if got != set(TRANSFORMS):
            errs.append(f"base {b}: 변형 누락 {set(TRANSFORMS) - got}")
    return errs


async def run_sealed(judge_fn, sealed: list[dict]) -> list[str]:
    failures = sealed_structure_errors(sealed)
    if failures:
        return failures
    base_cache: dict = {}
    for s in sealed:
        if s["base_id"] not in base_cache:
            base_cache[s["base_id"]] = await judge_fn(
                s["base_id"], s["base_answer_md"], s["rubric"], s["bundle_text"])
        base, var = base_cache[s["base_id"]], await judge_fn(
            s["id"], s["answer_md"], s["rubric"], s["bundle_text"])
        # r3-B7: base 전제조건 — verdict·countercase=1, evidence>0. 항상-0 저지처럼
        # 방향에 무감한 저지는 여기서 걸린다 (변형 기대만으론 통과 가능했음).
        if base is not None and s["transform"] == "identity":
            if base.axes["verdict"].score != 1.0 or base.axes["countercase"].score != 1.0 \
                    or not (base.axes["evidence"].score or 0) > 0:
                failures.append(f"{s['base_id']}: base 전제조건 미달 "
                                f"(verdict/countercase=1·evidence>0 필요)")
        if base is None or var is None:
            failures.append(f"{s['id']}: judge invalid")
            continue
        ax, rel = s["expectation"]["axis"], s["expectation"]["relation"]
        b, v = base.axes[ax].score, var.axes[ax].score
        if b is None or v is None:
            failures.append(f"{s['id']}: null score")
        elif rel == "zero" and v != 0.0:
            failures.append(f"{s['id']}: {ax} expected 0 got {v}")
        elif rel == "lower" and not (v < b):
            failures.append(f"{s['id']}: {ax} expected < {b} got {v}")
        elif rel == "same" and v != b:
            failures.append(f"{s['id']}: {ax} expected {b} got {v}")
    return failures
