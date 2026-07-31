import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_article import (audit_article, compose_article, draft_skeleton,
                                   headline_from_article, run_research)
from sector.report_contracts import (Anchor, ArticleDraft, ResearchFinding,
                                     ResearchQuestion, ResearchSource)

_NOW = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)


class _FakeRole:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        self.calls.append(prompt)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _anchor(aid="m:x", value=10.0, delta=None):
    return Anchor(anchor_id=aid, metric="m", entity="x", value=value,
                  delta_pct=delta, as_of="2026-07", source="테스트 원천 (test.org)")


# ── draft ──────────────────────────────────────────────────────────────────
def test_draft_parses_questions_and_drops_bad_ones():
    from sector.report_article import _DraftOut
    out = _DraftOut(core_question="Q", one_line="L", governing_equation="E",
                    skeleton=["s1", "s2"],
                    research_questions=[
                        {"qid": "q1", "question": "DDR5 Q3 계약가?"},
                        {"question": "qid 없음 — 자동 부여"},
                        {"qid": "q3"}])                    # question 누락 — 드롭
    r = asyncio.run(draft_skeleton([], [], [], [_anchor()], [], role=_FakeRole(out)))
    assert r.error is None
    assert r.output.core_question == "Q"
    assert len(r.output.research_questions) == 2          # 불량 1건 드롭
    assert [q.qid for q in r.output.research_questions] == ["q0", "q1"]  # 위치 재부여 — 충돌 불가


def test_draft_failure_never_raises():
    r = asyncio.run(draft_skeleton([], [], [], [], [], role=_FakeRole(RuntimeError("down"))))
    assert r.error and r.output.core_question == ""


# ── research ───────────────────────────────────────────────────────────────
def test_research_labels_and_per_question_isolation():
    from sector.report_article import _ResearchOut
    calls = {"n": 0}

    async def fake_cli(model, instr, prompt, *, response_format=None, tools=None,
                       timeout=None):
        calls["n"] += 1
        assert tools == ["WebSearch", "WebFetch"]
        if calls["n"] == 1:
            return _ResearchOut(answer="DDR5 +25%", numbers=["25"],
                                sources=[{"url": "https://x.com/a", "title": "t"}])
        if calls["n"] == 2:
            return _ResearchOut(answer="출처 못 찾음", numbers=[], sources=[])
        raise RuntimeError("cli died")

    qs = [ResearchQuestion(qid=f"q{i}", question=f"질문{i}") for i in range(3)]
    r = asyncio.run(run_research(qs, model="m", now=_NOW, cli=fake_cli))
    f = r.output
    assert f[0].label == "근거" and f[0].sources[0].url == "https://x.com/a"
    assert f[1].label == "가정"                            # 출처 없음 → 코드 강등
    assert f[2].error and f[2].qid == "q2"                 # 개별 실패 격리
    assert r.io.out_count == 2


def test_research_drops_non_http_sources():
    from sector.report_article import _ResearchOut

    async def fake_cli(*a, **k):
        return _ResearchOut(answer="a", sources=[{"url": "javascript:void(0)"},
                                                 {"url": "https://ok.com"}])

    r = asyncio.run(run_research([ResearchQuestion(qid="q0", question="?")],
                                 model="m", now=_NOW, cli=fake_cli))
    assert [s.url for s in r.output[0].sources] == ["https://ok.com"]


# ── compose ────────────────────────────────────────────────────────────────
def test_compose_includes_frame_research_and_refutations():
    role = _FakeRole("# 제목\n본문")
    draft = ArticleDraft(core_question="CQ", skeleton=["s"])
    from sector.report_contracts import ClaimVerdict, ReportClaim
    claims = [ReportClaim(claim_id="c0", title="주장")]
    verdicts = [ClaimVerdict(claim_id="c0", status="unverified",
                             reasons=["A2 반증 내용"], adjusted_confidence="낮")]
    f = ResearchFinding(qid="q1", answer="답", label="근거",
                        sources=[ResearchSource(url="https://s.com", title="src")])
    r = asyncio.run(compose_article(draft, [f], claims, verdicts, [], [_anchor()], [],
                                    role=role))
    assert r.output == "# 제목\n본문"
    p = role.calls[0]
    assert "사고의 틀" in p and "A2 반증 내용" in p and "https://s.com" in p


def test_compose_flags_all_research_failed():
    role = _FakeRole("글")
    draft = ArticleDraft(core_question="CQ")
    fails = [ResearchFinding(qid="q1", error="timeout")]
    asyncio.run(compose_article(draft, fails, [], [], [], [], [], role=role))
    assert "추가 조사가 전부 실패" in role.calls[0]


# ── audit ──────────────────────────────────────────────────────────────────
def test_audit_passes_sourced_numbers_and_flags_unknown():
    art = ("DDR4는 8.4달러다.\n엉뚱하게 77.7%가 올랐다.\n"
           "매출 변화는 〔계산: 1.18 × 0.85 − 1 = 약 +0.3%〕 수준이다.")
    out, unverified = audit_article(art, [_anchor(value=8.4)], [], [])
    assert "⚠미확인" not in out.splitlines()[0]            # 앵커 일치
    assert "⚠미확인" in out.splitlines()[1]                # 출처 없는 77.7%
    assert "⚠미확인" not in out.splitlines()[2]            # 괄호 안 저자 선언은 면제
    assert any("77.7" in u for u in unverified)


def test_audit_label_does_not_exempt_whole_line():
    # codex P4 M2 exploit: 라벨 하나로 같은 줄 전체가 면제되면 안 됨
    art = "〔계산: 1+1=2〕지만 목표가는 999달러다."
    out, unverified = audit_article(art, [], [], [])
    assert any("999" in u for u in unverified)


def test_audit_accepts_research_numbers_and_evidence_text():
    f = ResearchFinding(qid="q", answer="계약가 25% 인상", numbers=["25%"],
                        label="근거",
                        sources=[ResearchSource(url="https://s.com")])
    art = "Q3 계약가는 25% 오른다.\n재고는 3.3주다."
    out, unverified = audit_article(art, [], ["유통 재고 3.3주 기록"], [f])
    assert "⚠미확인" not in out


def test_audit_ignores_assumption_research_numbers():
    # codex P4 M3: '가정' 조사 수치가 풀에 들어가면 무라벨 본문 수치를 세탁한다
    f = ResearchFinding(qid="q", answer="아마 77.7%쯤", numbers=["77.7%"], label="가정")
    out, unverified = audit_article("증가율은 77.7%다.", [], [], [f])
    assert any("77.7" in u for u in unverified)


# ── headline ───────────────────────────────────────────────────────────────
def test_headline_from_article():
    assert headline_from_article("서문\n# 제목이다 (feat. X)\n본문") == "제목이다 (feat. X)"
    assert headline_from_article("h1 없음") == ""


def test_calc_label_recompute_passes_rounding_and_percent_scale():
    """〔계산: 식=결과〕 재계산 — 표기 반올림·% 스케일(0.411 vs 41.1%)은 통과."""
    from sector.report_article import audit_calc_labels
    txt = ("증가율은 〔계산: 8.40625/5.95812-1 = +41.1%〕이고 "
           "합계는 〔계산: 100×1.5 = 150억원〕이다.")
    out, bad = audit_calc_labels(txt)
    assert bad == []
    assert "⚠계산 불일치" not in out


def test_calc_label_recompute_flags_mismatch():
    from sector.report_article import audit_calc_labels
    txt = "틀린 계산 〔계산: 10×2 = 30〕이 섞였다.\n맞는 계산 〔계산: 3+4 = 7〕도 있다."
    out, bad = audit_calc_labels(txt)
    assert len(bad) == 1 and "10×2" in bad[0]
    lines = out.splitlines()
    assert "⚠계산 불일치" in lines[0]          # 틀린 줄에만 각주
    assert "⚠계산 불일치" not in lines[1]


def test_calc_label_recompute_skips_unparseable():
    """식이 산술이 아니면(자연어·미지수) 판정 불가 — 오탐 대신 침묵."""
    from sector.report_article import audit_calc_labels
    txt = "〔계산: 컨센서스 대비 갭 = 5%〕와 〔계산: x×2 = 10〕은 판정 불가."
    out, bad = audit_calc_labels(txt)
    assert bad == [] and "⚠계산 불일치" not in out


def test_calc_label_unicode_minus_not_false_positive():
    """07-31-1호 실측 오탐: 결과의 유니코드 마이너스(−0.6%p)를 부호로 못 읽어
    -0.6 계산을 0.6과 비교 — 정상 계산이 ⚠계산 불일치로 발행됐다."""
    from sector.report_article import audit_calc_labels
    txt = "GDP는 컨센을 〔계산: 1.5−2.1 = −0.6%p 하회〕했다."
    out, bad = audit_calc_labels(txt)
    assert bad == [] and "⚠계산 불일치" not in out
