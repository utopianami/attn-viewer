"""v2 3축 카드 파이프라인 — 매크로 / 메모리 / 그 외 최중요 (2026-07-24 재설계).

사용자 지시: 기존 결과물(주장·최종의견·종합·완결 글) 제거, 카드 3장 교체.
각 축: 현상 분석 → (필요시) 주제 선정 후 추가 연구(웹) → 긍정/부정 시나리오
→ 시나리오별 직접/간접 수혜(피해) 섹터·종목 (+필요시 재무·현황).

설계: docs/superpowers/specs/2026-07-24-axes-report-redesign.md (codex r1 반영).
축별 never-raise — 실패 축은 error 카드로 발행, 전체 리포트는 죽지 않는다.
"""
from __future__ import annotations

import asyncio
import re
import time

from pydantic import BaseModel, Field

from sector.report_contracts import (AxisBeneficiary, AxisCard, AxisScenario,
                                     ResearchQuestion, StageIO, StageResult)
from sector.report_synthesis import _fmt_anchor  # 비교 종류(MoM/QoQ/YoY) 명시 — 감사 4.1 재발 차단

_AXES = ("macro", "memory", "other")
_AXIS_LABEL = {"macro": "매크로(거시)", "memory": "메모리 섹터", "other": "그 외 최중요 이슈"}

# 스테이지 상한(초) — 합계 최악 8,700s < 스케줄러 하드캡 3h (codex r1 H1)
_SPLIT_TIMEOUT = 1200.0   # 900s 실측 타임아웃(스모크 1회차) — CLI opus high 대형 프롬프트 여유
_PHENOMENON_TIMEOUT = 1200.0  # 800→1200: 수치 검증 재생성(+최악 360s) 수용 —
                              # 재시도 중 스테이지 타임아웃이 나면 폴백이 빈
                              # _PhenomenonOut이라 1차 결과까지 통째로 증발한다
_RESEARCH_TIMEOUT = 1000.0     # 축당 — 질문 ≤2 × 360s + 여유
_SCENARIOS_TIMEOUT = 800.0
# CLI 다리 몫(초) — report_article 체인은 CLI(기본 600s)→API 폴백 2단인데, CLI가
# 파싱 재시도까지 하면 혼자 스테이지 예산을 소진해 API 폴백이 아예 못 뛴다
# (07-26~27 5회 연속 axis_split 1200s·scen_other 800s 타임아웃 실측). 스테이지
# 예산의 절반 이하로 잘라 폴백 시간을 보장한다.
_SPLIT_CLI_S = 480.0
_PHENO_CLI_S = 360.0
_SCEN_CLI_S = 360.0

STYLE = """[스타일 규칙 — 전 카드 공통]
- 모든 수치에 〔근거: 출처〕/〔가정〕/〔계산: 식 = 결과〕 라벨. 증감률은 비교 기준
  (MoM/QoQ/YoY·기간)을 분모와 함께 병기.
- 내부 프레임 용어(국면N, 사례 축 이름 등) 금지 — 자연어로만. 업계 용어·티커·회사
  약칭은 첫 언급에서 한 줄 정의.
- 면책·투자 권유 고지 금지. 평서체("~다"). 문단 2~3문장, 초단문 펀치라인 허용.
- 추측 금지 — 확인 못 한 것은 〔가정〕 라벨로 정직하게. 없는 수치를 만들지 마라."""


# ── [1] axis_split — 관측을 3축으로 배정 ─────────────────────────────────────
class _AxisPlanItem(BaseModel):
    axis: str = ""                 # macro | memory | other
    focus: str = ""                # 이 축의 핵심 현상 후보(수치 포함 한두 문장)
    event_titles: list[str] = Field(default_factory=list)
    why_important: str = ""        # other 축: 왜 이게 나머지 중 최중요인가


class _AxisPlanOut(BaseModel):
    axes: list[_AxisPlanItem] = Field(default_factory=list)


async def axis_split(clusters, macro_block: str, anchors, f2_titles: list[str],
                     *, role) -> StageResult:
    io = StageIO(key="axis_split", label="축 배정 — 매크로/메모리/그 외")
    t0 = time.monotonic()
    parts = ["[이벤트 클러스터 (12시간)]"]
    parts += [f"- {c.title} ({c.axis})" for c in clusters]
    if macro_block:
        parts.append("\n" + macro_block)
    if f2_titles:
        # f1 관련성 필터가 비메모리 최중요 이슈를 걸렀을 수 있다 — 원시 뉴스 제목을
        # 보충 공급(codex r1 H2 → r2 H2: f2가 아니라 f1 이전 원시 제목이어야 복구 가능)
        parts.append("\n[원시 뉴스 제목(필터 이전) — '그 외' 축 후보 보충]")
        parts += [f"- {t}" for t in f2_titles[:60]]
    parts.append("\n[수치 앵커 요약]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors[:20]]
    parts.append("""
[할 일]
위 관측을 정확히 3개 축으로 배정하라:
1. axis="macro" — 거시(지수·금리·환율·유가·통화정책·무역)에 집중한 현상.
2. axis="memory" — 메모리 반도체 관점의 현상.
3. axis="other" — 위 둘에 안 담긴 이슈 중 **가장 중요한 것 1개**
   (why_important에 선정 근거 — 시장 영향·수치로).
각 축: focus(핵심 현상 후보 — 반드시 수치 포함), event_titles(배정 이벤트 제목,
위 목록의 표현 그대로). 같은 이벤트를 macro와 memory 두 축에 넣는 것은 허용하나
(관점이 다르면), other에는 두 축과 **겹치지 않는** 이벤트만 넣어라 — 거시 지표나
메모리 반도체가 주인공인 이슈를 other로 중복 선정하지 마라.
시장을 움직인 실적 발표·가이던스(특히 빅테크·클라우드 어닝 — AI 인프라 지출은
메모리 수요의 상류다)는 반드시 최소 한 축의 event_titles에 배정하라 — 배정에서
빠진 클러스터는 카드 어디에도 실리지 않는다.""")
    try:
        # effort medium — 편집(배정) 작업. high는 CLI 파싱 실패 재시도와 겹쳐
        # 1200s 스테이지 예산을 소진(스모크·21:00 회차 2연속 실측)
        res = await role.run("\n".join(parts), instructions="시황 편집장 — 축 배정.",
                             response_format=_AxisPlanOut, effort="medium",
                             timeout=_SPLIT_CLI_S)
        plans = {p.axis: p for p in res.axes if p.axis in _AXES}
        io.in_count, io.out_count = len(clusters), len(plans)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=plans, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output={}, io=io, error=str(exc))


# ── 수치 검증 스윕 — 재료에 없는 수치는 만든 수치다 ──────────────────────────
# 2026-07-31-1호 실측: 원문 "순수익률 439%"가 발췌 절단으로 입력에서 잘리자
# 현상 단계가 "+43%"를 창작〔근거〕 라벨까지 붙여 발행. 위험 수치(%·소수점)를
# 입력 재료와 결정적 대조한다 — "43%"는 "439%"의 부분열이 아니라서 잡힌다.
_NUM_TOKEN_RE = re.compile(r"[+\-]?\d[\d,]*(?:\.\d+)?%|[+\-]?\d[\d,]*\.\d+")
_LABEL_RE = re.compile(r"〔(근거|가정|계산)")
_BRACKET_RE = re.compile(r"〔[^〕]*〕")
# 라벨 면제는 수치 바로 뒤(60자 내) 라벨만 — 줄 끝 〔가정〕 하나로 줄 전체가
# 면제되는 우회 차단(codex r1)
_LABEL_NEAR = 60
# 잔존 미확인 수치를 의미론 감사로 넘기는 채널 — StageResult.error 문자열을
# 코드가 그대로 재파싱한다(우리가 만든 결정적 접두어)
_UNVERIFIED_PREFIX = "수치 미확인: "


def _plain_hit(tok: str, mat: str, *, forbid_pre: str = "") -> bool:
    """숫자 경계 존중 부분열 검사 — "1.7%"가 "-11.7%"에 매칭되면 오검증.

    forbid_pre: 직전 문자로 금지할 부호(부호 뒤집힘 검사용)."""
    i = mat.find(tok)
    while i != -1:
        pre = mat[i - 1] if i > 0 else ""
        pre_ok = not (pre.isdigit() or pre == "." or (pre and pre in forbid_pre))
        j = i + len(tok)
        post_ok = tok.endswith("%") or j >= len(mat) \
            or not (mat[j].isdigit() or mat[j] == ".")
        if pre_ok and post_ok:
            return True
        i = mat.find(tok, i + 1)
    return False


def _num_in_material(tok: str, mat: str) -> bool:
    """부호 존중 검사 — 재료가 "-1.7%"뿐인데 생성문이 "+1.7%"면 미스(방향
    뒤집힘, codex r1). 부호 있는 토큰: 부호째 일치 우선, 없으면 반대 부호가
    직전에 붙지 않은 무부호 표기(산문 "1.7% 하락")만 인정."""
    if tok[0] in "+-":
        if _plain_hit(tok, mat):
            return True
        flip = "-" if tok[0] == "+" else "+"
        return _plain_hit(tok[1:], mat, forbid_pre=flip)
    return _plain_hit(tok, mat)


def sweep_unverified_numbers(gen: str, material: str) -> list[str]:
    """생성문 속 위험 수치(%·소수점) 중 입력 재료 어디에도 없는 것.

    제외: 〔…〕라벨 괄호 안(출처 표기·계산식·가정 설명), 수치 바로 뒤 60자 내
    라벨이 〔가정〕/〔계산〕인 수치(파생·미확인을 스스로 선언한 값).
    범위 밖(의도적): 정수 금액·통화·배수("$43bn"·"3배") — 날짜·개수류 오탐이
    지배해 재생성 루프가 상시 발화한다. 단위 없는 창작은 의미론 감사 소관."""
    mat = material.replace(",", "")
    misses: list[str] = []
    for line in gen.split("\n"):
        spans = [(m.start(), m.end()) for m in _BRACKET_RE.finditer(line)]
        for m in _NUM_TOKEN_RE.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            nxt = _LABEL_RE.search(line, m.end())
            if nxt and nxt.group(1) in ("가정", "계산") \
                    and nxt.start() - m.end() <= _LABEL_NEAR:
                continue
            tok = m.group().replace(",", "")
            if tok not in misses and not _num_in_material(tok, mat):
                misses.append(tok)
    return misses


# ── [2a] phenomenon — 축별 현상 분석 + 추가 연구 판단 ────────────────────────
class _PhenoQuestion(BaseModel):
    """자유형 dict 금지 — anthropic 구조화 출력 400(codex H1과 동일 계열)."""
    question: str = ""
    why_needed: str = ""
    expected_form: str = ""
    search_hint: str = ""


class _PhenomenonOut(BaseModel):
    title: str = ""                # 수치 포함 카드 헤드라인
    phenomenon_md: str = ""        # 현상 분석 markdown
    deep_dive_topic: str = ""      # 추가 연구가 필요하면 주제 한 줄, 아니면 ""
    research_questions: list[_PhenoQuestion] = Field(default_factory=list)
    watch_signals: list[str] = Field(default_factory=list)


async def phenomenon(axis: str, plan: _AxisPlanItem, clusters, anchors,
                     macro_block: str, cases, *, role,
                     f2_titles: list[str] | None = None,
                     prev_card: dict | None = None,
                     unassigned=None) -> StageResult:
    io = StageIO(key=f"pheno_{axis}", label=f"현상 분석 — {_AXIS_LABEL[axis]}")
    t0 = time.monotonic()
    titles = set(plan.event_titles)
    parts = [STYLE, f"\n[담당 축] {_AXIS_LABEL[axis]}",
             f"[핵심 현상 후보] {plan.focus}"]
    if axis == "other" and plan.why_important:
        parts.append(f"[선정 근거] {plan.why_important}")
    if axis == "other":
        # 방어선 — axis_split 실패 시 f1(메모리 관련성) 통과 클러스터만 남아
        # 메모리·거시 주제가 '기타'로 새는 운영 실측(07-25~28 '기타' 카드 7건 중
        # 6건이 DDR/SK하이닉스/CXMT/환율). 배정 유무와 무관하게 상시 주입.
        parts.append(
            "[축 경계] 거시(지수·금리·환율·유가·통화정책)와 메모리 반도체(DRAM·"
            "NAND·HBM, 메모리 제조사·장비·소재)는 별도 카드가 다룬다 — 그 주제가"
            " 주인공인 이슈는 이 축에서 제외하고, 나머지 이슈 중 시장 영향이 가장"
            " 큰 것 1개에 집중하라.")
    parts.append("\n[배정 관측 — 제목·발췌]")
    hit = 0
    for c in clusters:
        members = list(getattr(c, "members", []))
        if plan.event_titles and c.title not in titles \
                and not any(getattr(m, "title", "") in titles for m in members):
            continue
        hit += 1
        parts.append(f"- {c.title}")
        for m in members[:3]:
            # 400자 — 200자 절단이 원문 핵심 수치(439%)를 잘라내 창작 수치 오독을
            # 유발한 2026-07-31-1호 실측. 카드 경로 발췌는 상류가 전문을 준다.
            ex = (getattr(m, "excerpt", "") or "")[:400]
            parts.append(f"    · {getattr(m, 'title', '')} — {ex}")
    if not hit:                                   # 배정 제목 미매칭 — 전체 제공
        for c in clusters:
            parts.append(f"- {c.title} ({c.axis})")
    elif unassigned:
        # 미배정 백스톱 — 07-31-3호 실측: 아마존 실적 클러스터가 f1~f3을 다
        # 통과하고도 axis_split이 어느 축에도 안 넣어 전 카드에서 증발.
        # 배정 밖 관측을 보여주되 채택 판단은 담당 분석가에게 맡긴다.
        parts.append("\n[미배정 관측 — 축 배정에서 빠진 클러스터. 이 축 현상과"
                     " 직접 관련되면 반영하고, 아니면 무시하라]")
        for c in unassigned[:10]:
            parts.append(f"- {c.title}")
            for m in list(getattr(c, "members", []))[:1]:
                ex = (getattr(m, "excerpt", "") or "")[:200]
                parts.append(f"    · {ex}")
    if axis == "other" and f2_titles:
        # 원시 제목 보충 — 위 클러스터는 f1 통과분(메모리 중심)이라 비메모리
        # 최중요 이슈가 없을 수 있다(axis_split의 r2 H2와 같은 논리, 여기도 적용)
        parts.append("\n[원시 뉴스 제목(필터 이전) — 후보 보충]")
        parts += [f"- {t}" for t in f2_titles[:60]]
    if prev_card:
        # 연재 연속성 — 07-28~30 5회차 연속 동일 헤드라인(DDR4 +41.1% 반복) 실측.
        # 월간 앵커는 한 달 내내 같은 델타라 직전 회차를 모르면 매번 같은 수치가
        # 헤드라인 주인공이 된다.
        when = str(prev_card.get("generatedAt", ""))[:16]
        parts.append(f"\n[직전 회차 카드 — {prev_card.get('id', '')}({when}) 같은 축]")
        parts.append(f"제목: {prev_card.get('title', '')}")
        ws = [w for w in prev_card.get("watch_signals") or [] if w]
        if ws:
            parts.append("관찰 신호: " + " / ".join(ws[:4]))
        if prev_card.get("deep_dive_topic"):
            parts.append(f"직전 연구 주제: {prev_card['deep_dive_topic']}")
        parts.append(
            "이 리포트는 12시간마다 이어지는 연재다. 같은 주제가 여전히 최중요면"
            " '지속' 관점으로 다루되 직전 제목의 재탕을 금지한다 — title은 직전"
            " 회차 이후 **달라진 것**(새 사건·새 수치·신호 변화)을 앞세워라."
            " 직전과 같은 값(예: 월간 지표의 동일 MoM)은 헤드라인 주인공으로 다시"
            " 쓰지 말고 본문에서 '지속 중'으로만 언급하라. 위 관찰 신호의 현재"
            " 상태를 phenomenon_md에 업데이트하고, 직전 회차 대비 달라진 게 거의"
            " 없으면 그 사실 자체를 정직하게 써라.")
    if macro_block and axis == "macro":
        parts.append("\n" + macro_block)
        parts.append("⚠중요 표시 항목은 팩트 불릿에 반드시 포함하라.")
    parts.append("\n[수치 앵커 — 본문 수치는 여기 값·명시적 〔계산〕/〔가정〕만."
                 " 증감률 인용 시 괄호의 비교 종류(MoM/QoQ/YoY)를 그대로 표기]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors]
    if cases and axis == "memory":
        parts.append("\n[과거 유사 국면 참고]")
        for cs in cases[:3]:
            parts.append(f"- {cs.get('title', '')}: {str(cs.get('summary', ''))[:150]}")
    parts.append("""
[할 일]
1. phenomenon_md — 현상 분석 markdown:
   ① 첫 부분: 팩트 불릿 3~5개("무슨 일이 있었나" — 등락·수치가 먼저, 결과론이어도
      기본으로 깔린다) ② 이어서 해석 2~4문단(왜 움직였나, 무엇이 설명 안 되나).
2. title — 수치가 든 카드 헤드라인 한 문장.
3. 이 현상을 제대로 이해하는 데 지금 재료에 **없는** 정보가 필요하면:
   deep_dive_topic(주제 한 줄 — 예: "키미3 아키텍처가 학습 개선인지 인퍼런스
   개선인지, AI 지출 구조에 어떤 의미인지")과 research_questions 1~2개
   (question/why_needed/expected_form/search_hint). 필요 없으면 둘 다 비워라.
4. watch_signals — 이 현상의 다음 전개를 가르는 관찰 신호 2~4개(현재 상태 포함).""")
    prompt = "\n".join(parts)
    # 검증 재료 — plan.focus·선정 근거는 제외: axis_split(LLM)의 생성물이라
    # 그 단계의 오독 수치가 검증 근거로 인정되는 우회가 생긴다(codex r2).
    # prev_card 블록은 발행된 과거 기록이라 인용 허용(연재 참조 오탐 방지).
    material = "\n".join(p for p in parts
                         if not p.startswith(("[핵심 현상 후보]", "[선정 근거]")))
    try:
        res = await role.run(prompt,
                             instructions="시황 분석가 — 팩트 먼저, 숫자로 따진다.",
                             response_format=_PhenomenonOut, effort="high",
                             timeout=_PHENO_CLI_S)
        # 수치 검증 게이트 — 미확인 수치는 피드백과 함께 1회 재생성, 그래도
        # 남으면 본문에 검증 주석을 달고 진단에 기록(게이트지 생성자가 아니다).
        misses = sweep_unverified_numbers(
            f"{res.title}\n{res.phenomenon_md}", material)
        err = ""
        # 재시도는 스테이지 잔여 예산 안에서만 — 외부 wait_for 취소는
        # CancelledError라 아래 except를 우회, 1차 결과까지 통째로 증발한다
        # (codex r1). 잔여가 빠듯하면 재시도를 포기하고 1차+주석으로 간다.
        remain = _PHENOMENON_TIMEOUT - (time.monotonic() - t0) - 30.0
        if misses and remain > 60.0:
            fb = (prompt + "\n\n[수치 검증 실패 — 재작성]\n직전 초안의 다음 수치는"
                  " 위 재료 어디에도 없다: " + ", ".join(misses[:8])
                  + "\n재료에 실재하는 수치만 인용하라. 재료에 없는 값은 쓰지"
                  " 말고, 꼭 필요하면 〔가정〕 라벨을 붙여라. 전체를 다시 써라.")
            try:
                res2 = await asyncio.wait_for(role.run(
                    fb, instructions="시황 분석가 — 팩트 먼저, 숫자로 따진다.",
                    response_format=_PhenomenonOut, effort="high",
                    timeout=min(_PHENO_CLI_S, remain)), timeout=remain)
                m2 = sweep_unverified_numbers(
                    f"{res2.title}\n{res2.phenomenon_md}", material)
                if res2.phenomenon_md.strip() and len(m2) < len(misses):
                    res, misses = res2, m2
            except Exception:  # noqa: BLE001 — 재시도 실패는 1차 결과 유지
                pass
        if misses:
            # 예산 부족으로 재시도를 못 했어도 주석·진단은 남긴다
            res.phenomenon_md += ("\n\n〔수치 검증: 다음 수치는 수집 재료에서"
                                  " 확인되지 않았다 — "
                                  + ", ".join(misses[:8]) + "〕")
            err = _UNVERIFIED_PREFIX + ", ".join(misses[:8])
            io.note = f"수치 검증 미해소 {len(misses)}건"
        io.out_count = 1
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=res, io=io, error=err)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=_PhenomenonOut(), io=io, error=str(exc))


# ── [2c] scenarios — 긍정/부정 + 직접/간접 수혜 ──────────────────────────────
class _ScenarioItem(BaseModel):
    polarity: str = "positive"     # positive | negative
    thesis: str = ""
    beneficiaries: list[AxisBeneficiary] = Field(default_factory=list)


class _CorrectionItem(BaseModel):
    """연구가 현상 분석의 오류를 잡았을 때의 역반영 계약 — 2026-07-31-1호에서
    심층이 '+43%는 원문 오독, 실제 +439%'를 알아내고도 결론에만 쓰고 앞 섹션은
    그대로 발행된 실측. 코드가 wrong 실재 여부를 검증 후 정정 블록을 단다."""
    wrong: str = ""    # 현상 분석 본문/제목에 실제로 등장하는 문자열 그대로
    right: str = ""    # 연구로 확인된 올바른 값
    basis: str = ""    # 확인 출처


class _ScenariosOut(BaseModel):
    scenarios: list[_ScenarioItem] = Field(default_factory=list)
    deep_dive_conclusion: str = ""  # 연구 결과 종합 결론(연구 없으면 "")
    corrections: list[_CorrectionItem] = Field(default_factory=list)


async def scenarios(axis: str, pheno: _PhenomenonOut, findings, anchors,
                    *, role, research_failed: str = "") -> StageResult:
    io = StageIO(key=f"scen_{axis}", label=f"시나리오 — {_AXIS_LABEL[axis]}")
    t0 = time.monotonic()
    parts = [STYLE, f"\n[담당 축] {_AXIS_LABEL[axis]}",
             "\n[현상 분석 — 이 위에서 시나리오를 세운다]", pheno.phenomenon_md]
    ok_findings = [f for f in (findings or []) if not getattr(f, "error", None)]
    if ok_findings:
        parts.append(f"\n[추가 연구 결과 — 주제: {pheno.deep_dive_topic}]"
                     "\n('근거' 라벨은 출처 확인됨, '가정'은 미확인)")
        for f in ok_findings:
            src = "; ".join(s.url for s in getattr(f, "sources", [])[:3]) or "출처 없음"
            parts.append(f"- [{f.label}] {f.answer[:500]}\n  출처: {src}")
    elif pheno.deep_dive_topic:
        # 연구가 필요하다고 판정됐는데 실패/생략 — 침묵하면 미확인 논점이 단정으로
        # 발행된다(codex r2 H3)
        parts.append(f"\n[추가 연구 실패/생략 — 주제: {pheno.deep_dive_topic}"
                     + (f" / 사유: {research_failed}" if research_failed else "") + "]"
                     "\n이 주제와 관련된 논점은 확인되지 않았다 — 반드시 〔가정〕으로"
                     " 서술하고 시나리오 확신을 그만큼 낮춰라. 확인 못 한 사실을"
                     " 근거처럼 쓰지 마라.")
    parts.append("\n[수치 앵커 — 증감률 인용 시 괄호의 비교 종류(MoM/QoQ/YoY)를 그대로 표기]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors[:25]]
    parts.append("""
[할 일]
1. (연구 결과가 있으면) deep_dive_conclusion — 연구가 현상 해석을 어떻게 바꾸는지
   결론 2~3문장(예: "키미3는 단기 가격을 낮췄지만 딥시크 때와 달리 메모리 수요는
   오히려 늘린다").
2. scenarios — positive / negative 각 1개. thesis는 전개 + **성립 조건**을 명시한
   조건부 서술(단정 금지 — "~면 ~다" 구조).
3. 각 시나리오의 beneficiaries 2~4개 — 직접(direct)/간접(indirect) 구분, 수혜
   (benefit)/피해(damage) 구분, 섹터(sector)/종목(stock) 구분. stock의 name은
   반드시 "회사명 (티커)" 형식 — 티커 단독 금지(예: "005930.KS" ✗,
   "삼성전자 (005930.KS)" ✓).
   1차 수혜만 나열하지 말고 **2차 전이 인사이트**를 반드시 포함하라
   (예: 클라우드 CAPEX 증액은 메모리에도 좋지만 전력 인프라에 더 좋다).
   rationale에 전이 경로를 수치 라벨과 함께. 비중 큰 항목은 financials에
   재무·현황 미니 분석(밸류에이션·실적 수치 — 근거 있는 것만, 없으면 빈 값).
4. corrections — 연구 결과가 [현상 분석]의 특정 수치·사실이 **틀렸음을 직접
   보여줄 때만**: wrong=현상 분석에 실제로 등장하는 문자열 그대로(수치 포함,
   80자 이내), right=올바른 값, basis=확인 출처. 뉘앙스 차이·추가 정보는 정정이
   아니다 — 넣지 마라. 연구 결과가 없거나 정정할 게 없으면 빈 배열.""")
    try:
        res = await role.run("\n".join(parts),
                             instructions="시나리오 전략가 — 조건부 서술, 전이 경로 중심.",
                             response_format=_ScenariosOut, effort="high",
                             timeout=_SCEN_CLI_S)
        io.out_count = len(res.scenarios)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=res, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=_ScenariosOut(), io=io, error=str(exc))


# ── 수혜 종목명 백스톱 — 티커 단독 name을 "회사명 (티커)"로 (2026-08-03) ─────
# 실측: 같은 회차 안에 "삼성전자 (005930.KS)"와 "005930.KS"·"GOOGL" 혼재 —
# 프롬프트 형식 강제가 1차 방어, 여기는 LLM이 어겨도 주요 종목을 잡는 2차.
_TICKER_ONLY_RE = re.compile(r"^(?:[A-Z]{1,5}(?:\.[A-Z]{1,2})?|\d{6}\.(?:KS|KQ))$")


def _ticker_names() -> dict[str, str]:
    from sector.prices import TICKERS   # 코어 매핑 재사용(단일 출처)
    names = {sym: nm for sym, nm in TICKERS if not sym.startswith("^")}
    names.update({
        "AAPL": "애플", "MSFT": "마이크로소프트", "AMZN": "아마존",
        "GOOGL": "알파벳", "GOOG": "알파벳", "META": "메타", "QCOM": "퀄컴",
        "AVGO": "브로드컴", "AMD": "AMD", "INTC": "인텔", "ASML": "ASML",
        "AMAT": "어플라이드 머티어리얼즈", "LRCX": "램리서치", "KLAC": "KLA",
        "TSLA": "테슬라", "ORCL": "오라클", "MRVL": "마벨", "MPWR": "모놀리식 파워",
        "000990.KS": "DB하이텍", "042700.KS": "한미반도체",
    })
    return names


def _fix_beneficiary_name(name: str) -> str:
    base = (name or "").strip()
    if not _TICKER_ONLY_RE.fullmatch(base):
        return name
    known = _ticker_names().get(base)
    return f"{known} ({base})" if known else name


# ── [3] audit — 카드 의미론 감사 (legacy audit_semantics의 v2 이식) ───────────
class _CardAuditOut(BaseModel):
    ok: bool = False
    problems: list[str] = Field(default_factory=list)
    safe_title: str = ""      # ok=False일 때만 — 팩트 범위 안의 대체 제목


_AUDIT_TIMEOUT = 400.0
_AUDIT_CLI_S = 240.0


async def audit_card(axis: str, title: str, pheno_md: str, scen_models, findings,
                     *, role, unverified: list[str] | None = None) -> StageResult:
    """제목·시나리오가 카드의 팩트·근거 범위 안인지 LLM 판정.

    수치 스윕(audit_article)은 숫자의 존재만 본다 — 여기서는 의미를 본다:
    제목이 미확인 인과를 단정하는가, 시점·분모 다른 수치를 인과 근거로 병치했는가,
    thesis가 조건부가 아닌 단정인가. legacy 완결 글 경로에만 있던 감사의 카드 경로
    부재(07-30 사용자 지적) 이식. never-raise — 실패 시 카드 원형 유지."""
    io = StageIO(key=f"audit_{axis}", label=f"의미론 감사 — {_AXIS_LABEL[axis]}")
    t0 = time.monotonic()
    ok_f = [f for f in (findings or []) if not getattr(f, "error", None)
            and getattr(f, "label", "") == "근거"]
    parts = [f"[카드 제목]\n{title}",
             f"\n[현상 분석 — 이 카드의 팩트·해석 전문]\n{pheno_md[:3000]}"]
    if scen_models:
        parts.append("\n[시나리오 thesis]")
        parts += [f"- ({s.polarity}) {s.thesis}" for s in scen_models]
    if ok_f:
        parts.append("\n['근거' 라벨 연구 결과]")
        parts += [f"- {f.answer[:300]}" for f in ok_f]
    if unverified:
        # 결정적 스윕이 재생성으로도 못 지운 창작 의심 수치 — 본문은 검증 주석이
        # 달렸지만 제목은 텍스트 그대로다(codex r1). 제목 정화는 감사 소관.
        parts.append("\n[결정적 수치 검증 실패 — 다음 수치는 수집 재료 어디에도"
                     " 없다: " + ", ".join(unverified[:8]) + "]\n제목에 이 수치가"
                     " 있으면 반드시 ok=false로 하고 safe_title에서 해당 수치를"
                     " 빼거나 〔가정〕임을 명시하라.")
    parts.append("""
[판정하라]
1. 제목이 위 팩트·근거 범위를 넘어 원인·방향을 확정 어조로 단정하는가?
   (팩트가 현상 병치까지만 말하는데 제목이 인과를 확정하면 위반)
2. 시점·대상·비교 기준(분모)이 다른 수치를 같은 저울에 올려 인과 결론의 근거로
   단정했는가? (조건부 서술로 명시했다면 허용)
3. 시나리오 thesis가 성립 조건 없는 단정인가? ("~면 ~다" 구조면 통과)
전부 통과면 ok=true. 위반이면 ok=false + problems에 각 위반 한 문장 +
safe_title에 팩트 범위 안에서 성립하는 대체 제목(수치 포함 문장형 유지).""")
    try:
        res = await role.run("\n".join(parts),
                             instructions="발행 안전성 감사관 — 근거 범위 검사.",
                             response_format=_CardAuditOut, effort="medium",
                             timeout=_AUDIT_CLI_S)
        io.out_count = 1
        io.note = "ok" if res.ok else f"위반 {len(res.problems)}건"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=res, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=_CardAuditOut(ok=True), io=io, error=str(exc))


# ── 오케스트레이션 — 축별 순차, never-raise ──────────────────────────────────
async def run_axes_flow(*, clusters, anchors, macro_block: str, f2_titles: list[str],
                        cases, role_factory, model: str, eff, live_research: bool,
                        stage_cb=None,
                        prev_cards: dict | None = None) -> tuple[list[AxisCard], list[str]]:
    """카드 3장 생성. stage_cb(StageResult, items)로 사고흐름 기록.

    실패 격리: 축 하나가 죽어도 나머지 축은 진행 — 죽은 축은 error 카드."""
    errors: list[str] = []

    def _rec(sr: StageResult, items: list[str]):
        if stage_cb is not None:
            try:
                stage_cb(sr, items)
            except Exception:  # noqa: BLE001
                pass

    async def _bounded(coro, seconds: float, fallback: StageResult, name: str):
        try:
            return await asyncio.wait_for(coro, seconds)
        except asyncio.TimeoutError:
            errors.append(f"{name}: 스테이지 타임아웃({int(seconds)}s)")
            fallback.error = "timeout"
            return fallback

    t_flow = time.monotonic()
    # 전역 예산(codex r2 H1): 선행 필터 최악 소요와 스케줄러 하드캡(3h) 사이 여유 —
    # 예산 소진 시 남은 축은 즉시 error 카드로 강등해 리포트 저장을 보장.
    # 6600→6000: 시나리오 타임아웃 재시도 추가로 축당 최악이 +800s 늘어난 보정.
    # axis_split 재시도(+최악 1200s)·의미론 감사(+축당 최악 400s)는 예산 증액 없이
    # 흡수 — 축별 예산 검사가 남은 시간을 지키고, 배정 없는 3장보다 배정 있는
    # 2장이 낫다.
    _FLOW_BUDGET_S = 6000.0

    sp = await _bounded(
        axis_split(clusters, macro_block, anchors, f2_titles,
                   role=role_factory("axis_split")),
        _SPLIT_TIMEOUT,
        StageResult(output={}, io=StageIO(key="axis_split", label="축 배정")),
        "axis_split")
    if sp.error:
        errors.append(f"axis_split: {sp.error}")
    if not (sp.output or {}):
        # 배정 실패는 사유 불문 1회 재시도 — 운영 10/10 회차 타임아웃 실측
        # (07-24~28). 배정 없이 내려가면 '기타' 축이 메모리 주제를 중복 선정한다.
        errors.append("axis_split: "
                      f"{'타임아웃' if sp.error == 'timeout' else '빈 배정'} — 재시도")
        sp2 = await _bounded(
            axis_split(clusters, macro_block, anchors, f2_titles,
                       role=role_factory("axis_split_retry")),
            _SPLIT_TIMEOUT,
            StageResult(output={}, io=StageIO(key="axis_split_retry",
                                              label="축 배정 재시도")),
            "axis_split_retry")
        if sp2.output:
            sp = sp2
    plans = sp.output or {}
    _rec(sp, [f"{k}: {v.focus[:80]}" for k, v in plans.items()])

    cards: list[AxisCard] = []
    # 미배정 클러스터 — 배정 밖 = 무언의 탈락(07-31-3호 아마존 실적 증발 실측).
    # pheno에 보충 공급해 담당 분석가가 채택 여부를 판단하게 한다.
    assigned_titles = {t for p in plans.values() for t in p.event_titles}
    unassigned = [c for c in clusters if c.title not in assigned_titles] \
        if assigned_titles else []
    for axis in _AXES:
        plan = plans.get(axis) or _AxisPlanItem(axis=axis, focus="", event_titles=[])
        if time.monotonic() - t_flow > _FLOW_BUDGET_S:
            errors.append(f"axis_{axis}: 시간 예산 소진 — 축 생략")
            cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis],
                                  error="시간 예산 소진"))
            continue
        try:
            ph = await _bounded(
                phenomenon(axis, plan, clusters, anchors, macro_block, cases,
                           role=role_factory(f"pheno_{axis}"),
                           f2_titles=f2_titles,
                           prev_card=(prev_cards or {}).get(axis),
                           unassigned=unassigned),
                _PHENOMENON_TIMEOUT,
                StageResult(output=_PhenomenonOut(),
                            io=StageIO(key=f"pheno_{axis}", label="현상 분석")),
                f"pheno_{axis}")
            if ph.error:
                errors.append(f"pheno_{axis}: {ph.error}")
            pheno: _PhenomenonOut = ph.output
            _rec(ph, [pheno.title] if pheno.title else [])
            if not pheno.phenomenon_md.strip():
                cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis],
                                      error=ph.error or "현상 분석 실패"))
                continue

            findings = []
            research_failed = ""
            questions = []
            for i, q in enumerate(pheno.research_questions[:2]):
                if (q.question or "").strip():
                    questions.append(ResearchQuestion(
                        qid=f"{axis}-q{i}", question=q.question,
                        why_needed=q.why_needed, expected_form=q.expected_form,
                        search_hint=q.search_hint))
            if questions and live_research:
                from sector.report_article import run_research
                rs = await _bounded(
                    run_research(questions, model=model, now=eff),
                    _RESEARCH_TIMEOUT,
                    StageResult(output=[],
                                io=StageIO(key=f"research_{axis}", label="추가 연구")),
                    f"research_{axis}")
                if rs.error:
                    errors.append(f"research_{axis}: {rs.error}")
                    research_failed = rs.error
                findings = rs.output
                if findings and all(getattr(f, "error", None) for f in findings):
                    research_failed = research_failed or "전 질문 실패"
                rs.io.key = f"research_{axis}"
                rs.io.label = f"추가 연구 — {_AXIS_LABEL[axis]}"
                _rec(rs, [f"{f.qid}: {(f.answer or f.error or '')[:100]}"
                          for f in findings])
            elif questions:
                research_failed = "웹 조사 비활성(replay 가드)"

            sc = await _bounded(
                scenarios(axis, pheno, findings, anchors,
                          role=role_factory(f"scen_{axis}"),
                          research_failed=research_failed),
                _SCENARIOS_TIMEOUT,
                StageResult(output=_ScenariosOut(),
                            io=StageIO(key=f"scen_{axis}", label="시나리오")),
                f"scen_{axis}")
            if sc.error:
                errors.append(f"scen_{axis}: {sc.error}")
            so: _ScenariosOut = sc.output
            if not so.scenarios:
                # 빈 시나리오는 사유 불문 1회 재시도 — CLI 구조화 출력 간헐 결함
                # (21:00 회차 memory 축 실측)뿐 아니라 타임아웃(07-27 저녁 scen_other
                # 실측)도 재시도 없이는 그대로 error 카드가 된다.
                errors.append(f"scen_{axis}: "
                              f"{'타임아웃' if sc.error == 'timeout' else '빈 시나리오'}"
                              " — 재시도")
                sc2 = await _bounded(
                    scenarios(axis, pheno, findings, anchors,
                              role=role_factory(f"scen_{axis}_retry"),
                              research_failed=research_failed),
                    _SCENARIOS_TIMEOUT,
                    StageResult(output=_ScenariosOut(),
                                io=StageIO(key=f"scen_{axis}_retry",
                                           label="시나리오 재시도")),
                    f"scen_{axis}_retry")
                if sc2.output.scenarios:
                    so = sc2.output
                    _rec(sc2, [f"{s.polarity}: {s.thesis[:80]}"
                               for s in so.scenarios])
            # 오염 방어: 구조화 출력 결함 시 결론에 XML 조각이 섞임 — 절단
            for marker in ("<parameter", "</deep_dive", "</parameter"):
                if marker in so.deep_dive_conclusion:
                    so.deep_dive_conclusion = \
                        so.deep_dive_conclusion.split(marker)[0].rstrip()
            _rec(sc, [f"{s.polarity}: {s.thesis[:80]}" for s in so.scenarios])

            scen_models = []
            for s in so.scenarios[:3]:
                # 불량 polarity·빈 thesis는 드롭 — positive로 보정하면 "긍정/부정
                # 각 1개" 요구가 조용히 깨진다(codex r2 H4)
                if s.polarity not in ("positive", "negative") or not s.thesis.strip():
                    continue
                bens = s.beneficiaries[:4]
                for b in bens:
                    b.name = _fix_beneficiary_name(b.name)
                scen_models.append(AxisScenario(polarity=s.polarity, thesis=s.thesis,
                                                beneficiaries=bens))
            pols = {s.polarity for s in scen_models}
            if scen_models and (pols != {"positive", "negative"}
                                or not any(s.beneficiaries for s in scen_models)):
                errors.append(f"scen_{axis}: 시나리오 불완전 — "
                              f"극성 {sorted(pols)}, 수혜 "
                              f"{sum(len(s.beneficiaries) for s in scen_models)}건")
            ok_f = [f for f in findings if not getattr(f, "error", None)]
            deep = {}
            if pheno.deep_dive_topic or ok_f:
                deep = {"topic": pheno.deep_dive_topic,
                        "conclusion": so.deep_dive_conclusion,
                        "findings": [f.model_dump() for f in ok_f]}
                if research_failed:
                    deep["research_failed"] = research_failed
            srcs = [s.model_dump() for f in ok_f for s in f.sources][:8]
            # 연구 정정 역반영 — 심층이 앞 섹션 오류를 잡으면 본문에 정정 블록,
            # 제목은 문자열 치환(헤드라인의 틀린 수치가 최악). 게이트(codex r1):
            # '근거' 라벨 연구가 있을 때만, wrong은 **원본** 본문·제목에 실재하고
            # 3~80자, 제목 치환은 유일 일치일 때만 — 환각·재치환·전역 오염 차단.
            card_title = pheno.title or _AXIS_LABEL[axis]
            pheno_md = pheno.phenomenon_md
            orig_title, orig_md = card_title, pheno_md
            grounded = [f for f in ok_f if getattr(f, "label", "") == "근거"]
            if grounded:
                # right 속 위험 수치는 '근거' 연구 텍스트에 실재해야 한다 —
                # 연구와 무관한 환각 정정의 역반영 차단(codex r2). basis 필수.
                research_mat = "\n".join(
                    f"{f.answer} {' '.join(getattr(f, 'numbers', []))}"
                    for f in grounded).replace(",", "")
                notes = []
                for co in so.corrections[:3]:
                    w = co.wrong.strip()
                    r = " ".join(co.right.split())[:120]
                    if not w or not r or w == r or not 3 <= len(w) <= 80 \
                            or not co.basis.strip():
                        continue
                    if not (w in orig_md or w in orig_title):
                        continue
                    # right는 '연구 확인 값'으로 발행된다 — 라벨 면제 없이
                    # 모든 위험 수치가 연구 텍스트에 실재해야 한다(codex r3)
                    r_toks = [m.group().replace(",", "")
                              for m in _NUM_TOKEN_RE.finditer(r)]
                    if any(not _num_in_material(t, research_mat)
                           for t in r_toks):
                        continue
                    if orig_title.count(w) == 1:
                        card_title = card_title.replace(w, r, 1)
                    notes.append(f"- “{w}” → {r} 〔근거: {co.basis.strip()}〕")
                if notes:
                    pheno_md += ("\n\n**추가 연구 후 정정** — 아래는 현상 분석"
                                 " 시점 재료의 오류로, 연구에서 확인된 값이다.\n"
                                 + "\n".join(notes))
                    if deep:
                        deep["corrections_applied"] = len(notes)
            # 의미론 감사 — 위반이면 safe_title로 강등(카드는 산다: 감사는
            # 게이트지 생성자가 아니다). 실패/타임아웃 시 원형 유지. 결정적
            # 스윕의 잔존 미확인 수치는 감사에 강제 전달(제목 정화).
            unverified = []
            if ph.error and ph.error.startswith(_UNVERIFIED_PREFIX):
                unverified = ph.error[len(_UNVERIFIED_PREFIX):].split(", ")
            au = await _bounded(
                audit_card(axis, card_title, pheno_md, scen_models,
                           findings, role=role_factory(f"audit_{axis}"),
                           unverified=unverified),
                _AUDIT_TIMEOUT,
                StageResult(output=_CardAuditOut(ok=True),
                            io=StageIO(key=f"audit_{axis}", label="의미론 감사")),
                f"audit_{axis}")
            if au.error:
                errors.append(f"audit_{axis}: {au.error}")
            ao: _CardAuditOut = au.output
            _rec(au, [] if ao.ok else ao.problems)
            if not ao.ok:
                errors.append(f"audit_{axis}: " + "; ".join(ao.problems[:3]))
                if ao.safe_title.strip():
                    card_title = ao.safe_title.strip()
            if any(_num_in_material(tok, card_title.replace(",", ""))
                   for tok in unverified):
                # 스윕과 동일한 정규화·경계 검사 — "43%"가 "143%"에 오매칭되거나
                # 콤마 표기("24,442.94") 잔존을 놓치는 일 방지(codex r3)
                # 결정적 폴백 — 감사가 ok를 주든 죽든, 재료에 없는 수치가 제목에
                # 남았으면 표식은 코드가 단다(codex r2). 제거는 LLM 소관이지만
                # 무표식 발행은 금지.
                card_title += " 〔수치 미확인〕"
                errors.append(f"audit_{axis}: 제목 미확인 수치 잔존 — 표식 강제")
            cards.append(AxisCard(
                axis=axis, title=card_title,
                phenomenon=pheno_md, deep_dive=deep,
                scenarios=scen_models, watch_signals=pheno.watch_signals[:4],
                sources=srcs,
                error="" if scen_models else (sc.error or "시나리오 생성 실패")))
        except Exception as exc:  # noqa: BLE001 — 축 격리
            errors.append(f"axis_{axis}: {exc}")
            cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis], error=str(exc)))
    return cards, errors
