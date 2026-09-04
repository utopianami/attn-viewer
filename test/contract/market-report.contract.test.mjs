import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { createTestRoot, requestJson, startTestServer } from "../helpers/test-server.mjs";

const REPORT = {
  id: "2026-07-21-1",
  seq: 1,
  generatedAt: "2026-07-21T09:00:00+09:00",
  title: "메모리 반도체 12시간 시황",
  window: { from: "2026-07-20T21:00:00+09:00", to: "2026-07-21T09:00:00+09:00" },
  overview: "검증된 주장 요약",
  finalOpinion: { text: "관망", confidence: "낮" },
  claims: [{
    claim_id: "c0", title: "환율發 수급 상충", confidence: "중", status: "verified",
    trigger: "원/달러 급등", mechanism: "환율→실적/수급 양가",
    evidence: ["원/달러 +12원 (연합)"],
    evidence_refs: [{ kind: "news", id: "n1", title: "원/달러 급등", ts: "", excerpt: "", source: "연합", url: "" }],
    anchor_refs: ["usdkrw:krw"], numeric_facts: [{ anchor_id: "usdkrw:krw", value: 1450 }],
    precedent: "", precedent_grounded: false, counter: "환율 되돌림", stance: "수급 확인",
    matched_rules: [], load_bearing: true, as_of: "2026-07-21T08:00:00+09:00",
  }],
  pipeline: { stages: [{ key: "f1", label: "1차 필터 — 관련성", note: "", items: ["원/달러 급등"], sources: [], io: { in_count: 2, out_count: 1, dropped: [] } }] },
  diagnostics: { seams_empty: ["price_reaction"], stage_errors: [], rejected_claims: [] },
  article: "# 헤드라인\n\n본문 문단. 〔계산: 1.18×0.85−1=+0.3%〕",
  article_meta: {
    core_question: "핵심 질문", governing_equation: "갭=수요-공급",
    skeleton: ["s1"], research_ok: 1, research_sourced: 1, research_failed: 0,
    unverified_numbers: [],
  },
};

const scenarios = () => ([
  {
    polarity: "positive", thesis: "수요가 확대된다", beneficiaries: [
      { name: "전력 인프라", kind: "sector", direction: "direct", polarity: "benefit", causalChain: "수요 증가 → 수주 증가", evidence: "전력 수요 전망" },
      { name: "산업재", kind: "sector", direction: "indirect", polarity: "benefit", causalChain: "수주 증가 → 투자 증가", evidence: "설비 투자 계획" },
    ],
  },
  {
    polarity: "negative", thesis: "투자가 지연된다", beneficiaries: [
      { name: "전력 인프라", kind: "sector", direction: "direct", polarity: "damage", causalChain: "금리 상승 → 발주 지연", evidence: "금리 민감도" },
      { name: "산업재", kind: "sector", direction: "indirect", polarity: "damage", causalChain: "발주 지연 → 가동률 하락", evidence: "가동률 자료" },
    ],
  },
]);

const OLD_FIXED_AXIS_REPORT = {
  ...REPORT,
  format: "axes",
  cards: [
    { axis: "macro", title: "거시" },
    { axis: "memory", title: "메모리" },
    { axis: "other", title: "기타" },
  ],
};

const TOPICS_V1_REPORT = {
  ...REPORT,
  format: "axes",
  axisModel: "topics_v1",
  leadAxis: "topic1",
  title: "AI 전력망이 시장을 이끈다",
  cards: [
    { axis: "macro", label: "거시", topicKey: "macro", title: "금리 경로", scenarios: scenarios() },
    { axis: "topic1", label: "AI 전력망", topicKey: "ai-power-grid", title: "AI 전력망이 시장을 이끈다", scenarios: scenarios() },
    { axis: "topic2", label: "방산 수출", topicKey: "defense-exports", title: "방산 수출의 재평가", scenarios: scenarios() },
  ],
};

const readingBrief = (label) => ({
  headline: `${label} 핵심을 먼저 읽는다`,
  summary: `${label} 사건과 시장 전이 경로를 짧게 설명한다.`,
  keyNumbers: [{ label: "핵심 신호", value: "정성", context: "원문 카드", tone: "neutral" }],
  flow: [
    { label: "사건", detail: "핵심 변화가 발생했다", tone: "neutral" },
    { label: "전이", detail: "관련 시장으로 영향이 번진다", tone: "warning" },
  ],
  scenarioGuide: [
    { polarity: "positive", condition: "상방 조건이 이어진다", outcome: "긍정 전이가 유지된다" },
    { polarity: "negative", condition: "하방 조건이 커진다", outcome: "부정 전이가 확대된다" },
  ],
  watchlist: [{ label: "다음 신호", current: "확인 중", trigger: "방향 전환 여부" }],
  bottomLine: `${label}의 다음 확인점을 본다.`,
});

const READABLE_TOPICS_V1_REPORT = {
  ...structuredClone(TOPICS_V1_REPORT),
  readerModel: "brief_v1",
  editorial: {
    label: "읽기 편집본",
    baseReportId: TOPICS_V1_REPORT.id,
    baseGeneratedAt: TOPICS_V1_REPORT.generatedAt,
    editedAt: TOPICS_V1_REPORT.generatedAt,
    headline: "AI 전력망과 금리 경로를 먼저 읽는다",
    deck: "거시와 당일 핵심 토픽의 직접·간접 전이를 함께 확인한다.",
    takeaways: [
      { axis: "macro", title: "거시", text: "금리 경로를 확인한다." },
      { axis: "topic1", title: "AI 전력망", text: "전력 수요 전이를 확인한다." },
      { axis: "topic2", title: "방산 수출", text: "수출 사이클을 확인한다." },
    ],
  },
};
READABLE_TOPICS_V1_REPORT.cards = READABLE_TOPICS_V1_REPORT.cards.map((card) => ({
  ...card,
  brief: readingBrief(card.label),
  scenarios: card.scenarios.map((scenario) => ({
    ...scenario,
    beneficiaries: scenario.beneficiaries.map((beneficiary) => ({
      ...beneficiary,
      readerCopy: {
        displayName: beneficiary.name,
        rationale: "핵심 사건이 해당 대상의 실적에 영향을 준다.",
        causalChain: "핵심 사건의 변화가 관련 공급망을 거쳐 해당 대상까지 전달된다.",
        evidence: beneficiary.evidence ? "카드에 수록된 근거를 자연어로 확인했다." : "",
        financials: beneficiary.financials ? "카드에 수록된 재무 수치를 자연어로 확인했다." : "",
      },
    })),
  })),
}));

async function validateFixture(t, report) {
  const dir = await mkdtemp(join(tmpdir(), "attn-market-contract-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, "report.json");
  await writeFile(path, JSON.stringify(report));
  return spawnSync(
    resolve("engine/.venv/bin/python"),
    [resolve("scripts/validate_market_report.py"), path],
    { cwd: resolve("."), encoding: "utf8" },
  );
}

test("OpenAPI accepts legacy fixed axes and topics_v1 but rejects a mixed set", async (t) => {
  const oldResult = await validateFixture(t, OLD_FIXED_AXIS_REPORT);
  assert.equal(oldResult.status, 0, oldResult.stderr);

  const newResult = await validateFixture(t, TOPICS_V1_REPORT);
  assert.equal(newResult.status, 0, newResult.stderr);

  const mixed = structuredClone(TOPICS_V1_REPORT);
  mixed.cards[2].axis = "other";
  const mixedResult = await validateFixture(t, mixed);
  assert.notEqual(mixedResult.status, 0, "mixed topic/fixed axes must be rejected");

  for (const [name, fixture] of [
    ["legacy article", REPORT],
    ["fixed-axis report", OLD_FIXED_AXIS_REPORT],
  ]) {
    const marked = structuredClone(fixture);
    marked.readerModel = "brief_v1";
    const markedResult = await validateFixture(t, marked);
    assert.notEqual(markedResult.status, 0,
      `${name} cannot claim the integrated reader contract`);
  }
});

test("brief_v1 makes the integrated reading template an executable contract", async (t) => {
  const valid = await validateFixture(t, READABLE_TOPICS_V1_REPORT);
  assert.equal(valid.status, 0, valid.stderr);

  for (const [name, mutate] of [
    ["missing editorial", (report) => { delete report.editorial; }],
    ["missing card brief", (report) => { delete report.cards[1].brief; }],
    ["missing beneficiary readerCopy", (report) => {
      delete report.cards[1].scenarios[0].beneficiaries[0].readerCopy;
    }],
    ["different base report", (report) => { report.editorial.baseReportId = "2026-07-21-0"; }],
    ["later edit timestamp", (report) => { report.editorial.editedAt = "2026-07-21T10:00:00+09:00"; }],
  ]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    mutate(report);
    const result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${name} must be rejected for brief_v1`);
  }
});

test("brief_v1 rejects internal analysis syntax in reader-facing beneficiary copy", async (t) => {
  for (const [name, mutate] of [
    ["ticker suffix", (beneficiary) => { beneficiary.readerCopy.displayName = "SK하이닉스 (000660.KS)"; }],
    ["compact lowercase ticker suffix", (beneficiary) => { beneficiary.readerCopy.displayName = "SK하이닉스(000660.ks)"; }],
    ["metric in display name", (beneficiary) => { beneficiary.readerCopy.displayName = "memory_capex"; }],
    ["comparison abbreviation in display name", (beneficiary) => { beneficiary.readerCopy.displayName = "QoQ"; }],
    ["raw billion-won value in display name", (beneficiary) => { beneficiary.readerCopy.displayName = "7,865.37b원"; }],
    ["numeric-prefix snake unit", (beneficiary) => {
      beneficiary.readerCopy.evidence = "설비투자 18,176.96b_local이다.";
    }],
    ["metric row", (beneficiary) => {
      beneficiary.readerCopy.evidence = "memory_capex 000660.KS 7,865.37b원(+42.5% QoQ, 2026-03)";
    }],
    ["standalone source ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "램리서치 LRCX 실적 근거다.";
    }],
    ["dynamic-topic company ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "NVIDIA (NVDA) 실적 근거다.";
    }],
    ["unknown parenthesized ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "NewCo (ZZZZ) 공시 근거다.";
    }],
    ["lowercase explanatory acronym", (beneficiary) => {
      beneficiary.readerCopy.evidence = "인공지능(ai) 수요를 확인했다.";
    }],
    ["contextual unknown ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "NewCo 종목코드 ZZZZ 공시 근거다.";
    }],
    ["hyphenated ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "버크셔 해서웨이 (BRK-B) 공시 근거다.";
    }],
    ["qualified peer ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "NewCo ZZZZ.O 공시 근거다.";
    }],
    ["hyphenated peer ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "Berkshire Hathaway BRK-B 공시 근거다.";
    }],
    ["exchange-suffixed ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "엔비디아 NVDA.O 실적 근거다.";
    }],
    ["alphanumeric Reuters ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "Embraer EMBJ3.S 공시 근거다.";
    }],
    ["equals Reuters ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "JP10YTN=JBTC 시장 근거다.";
    }],
    ["mixed-case known ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "마이크론 Mu 실적 근거다.";
    }],
    ["meta ticker", (beneficiary) => {
      beneficiary.readerCopy.evidence = "메타 META 실적 근거다.";
    }],
    ["bare mixed-case Reuters RIC", (beneficiary) => {
      beneficiary.readerCopy.evidence = "유가 선물 LCOc1 움직임을 확인했다.";
    }],
    ["lowercase Reuters RIC", (beneficiary) => {
      beneficiary.readerCopy.evidence = "유가 선물 lcoc1 움직임을 확인했다.";
    }],
    ["lowercase comparison abbreviations", (beneficiary) => {
      beneficiary.readerCopy.financials = "매출은 12% qoq, 3% wow 늘었다.";
    }],
    ["comparison abbreviation before Korean particle", (beneficiary) => {
      beneficiary.readerCopy.financials = "매출은 12% qoq가 늘었다.";
    }],
    ["blank sentence", (beneficiary) => { beneficiary.readerCopy.rationale = "   "; }],
    ["renamed impact subject", (beneficiary) => { beneficiary.readerCopy.displayName = "테슬라"; }],
    ["omitted original evidence", (beneficiary) => { beneficiary.readerCopy.evidence = ""; }],
    ["omitted original financials", (beneficiary) => {
      beneficiary.financials = "수주잔고는 12% 늘었다.";
      beneficiary.readerCopy.financials = "";
    }],
    ["omitted multiline original evidence", (beneficiary) => {
      beneficiary.evidence = "첫 줄\n둘째 줄";
      beneficiary.readerCopy.evidence = "";
    }],
    ["omitted multiline original financials", (beneficiary) => {
      beneficiary.financials = "\n수주잔고는 12% 늘었다.\n";
      beneficiary.readerCopy.financials = "";
    }],
  ]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    mutate(report.cards[0].scenarios[0].beneficiaries[0]);
    const result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${name} must be rejected from readerCopy`);
  }
});

test("brief_v1 binds alphanumeric source tickers to a ticker-free reader copy", async (t) => {
  for (const ticker of ["EMBJ3.S", "LCOc1", "GCcv1", "JP10YTN=JBTC"]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    const beneficiary = report.cards[0].scenarios[0].beneficiaries[0];
    Object.assign(beneficiary, {
      kind: "stock",
      name: `테스트 기업 (${ticker})`,
      evidence: "회사 공시를 확인했다.",
    });
    beneficiary.readerCopy.displayName = "테스트 기업";
    let result = await validateFixture(t, report);
    assert.equal(result.status, 0, `${ticker} source form must validate: ${result.stderr}`);

    beneficiary.readerCopy.evidence = `테스트 기업 ${ticker} 공시를 확인했다.`;
    result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${ticker} must not leak into readerCopy`);
  }
});

test("brief_v1 preserves explanatory parentheses on sector names", async (t) => {
  const report = structuredClone(READABLE_TOPICS_V1_REPORT);
  const beneficiary = report.cards[0].scenarios[0].beneficiaries[0];
  beneficiary.name = "미국 달러·달러현금(머니마켓)";
  Object.assign(beneficiary.readerCopy, {
    displayName: "미국 달러·달러현금(머니마켓)",
    rationale: "달러와 머니마켓이 방어 자산 역할을 한다.",
  });
  const result = await validateFixture(t, report);
  assert.equal(result.status, 0, result.stderr);
});

test("brief_v1 applies clean prose rules to editorial and card briefs", async (t) => {
  for (const [name, mutate] of [
    ["editorial metric", (report) => { report.editorial.deck = "equip_revenue가 늘었다."; }],
    ["brief ticker", (report) => { report.cards[1].brief.summary = "램리서치 LRCX 매출을 본다."; }],
    ["brief comparison token", (report) => { report.cards[1].brief.bottomLine = "QoQ를 확인한다."; }],
    ["brief meta ticker", (report) => { report.cards[1].brief.summary = "메타 META 실적을 본다."; }],
    ["brief mixed-case Reuters RIC", (report) => {
      report.cards[1].brief.summary = "유가 선물 LCOc1 움직임을 본다.";
    }],
  ]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    mutate(report);
    const result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${name} must be rejected from scan-first prose`);
  }
});

test("brief_v1 preserves technical generations and source domains", async (t) => {
  for (const term of ["PCIe5", "CXL2.0", "Reuters.com", "Node.js", "Xe2", "Gen2"]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    report.cards[1].brief.summary = `${term} 관련 신호를 확인한다.`;
    const result = await validateFixture(t, report);
    assert.equal(result.status, 0, `${term}: ${result.stderr}`);
  }
});

test("brief_v1 rejects a dynamic source ticker from scan-first prose", async (t) => {
  const report = structuredClone(READABLE_TOPICS_V1_REPORT);
  const stock = report.cards[0].scenarios[0].beneficiaries[1];
  Object.assign(stock, {
    kind: "stock",
    name: "팔란티어 (PLTR)",
    evidence: "회사 공시를 확인했다.",
  });
  stock.readerCopy.displayName = "팔란티어";
  report.cards[1].brief.summary = "PLTR 계약 확대를 확인한다.";
  const result = await validateFixture(t, report);
  assert.notEqual(result.status, 0, "dynamic source ticker must not leak");
});

test("brief_v1 accepts canonical aliases and ticker-named companies", async (t) => {
  for (const [rawName, displayName] of [
    ["퀄컴 (QCOM)", "퀄컴"], ["AMD (AMD)", "AMD"], ["IBM (IBM)", "IBM"],
    ["SAP (SAP)", "SAP"], ["ARM (ARM)", "ARM"],
    ["Meta Platforms (META.O)", "메타"],
    ["Lam Research Corporation (LRCX.O)", "램리서치"],
    ["Applied Materials Inc (AMAT.O)", "어플라이드 머티어리얼즈"],
  ]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    const stock = report.cards[0].scenarios[0].beneficiaries[1];
    Object.assign(stock, { kind: "stock", name: rawName, evidence: "회사 공시를 확인했다." });
    Object.assign(stock.readerCopy, {
      displayName,
      rationale: `${displayName}은 핵심 사건의 영향을 받는다.`,
      causalChain: `핵심 사건이 ${displayName}에 전달된다.`,
      evidence: `${displayName}의 회사 공시를 확인했다.`,
    });
    const result = await validateFixture(t, report);
    assert.equal(result.status, 0, `${rawName}: ${result.stderr}`);
  }
});

test("unmarked self-integrated editorial keeps provenance timestamps exact", async (t) => {
  const report = structuredClone(READABLE_TOPICS_V1_REPORT);
  delete report.readerModel;
  report.editorial.editedAt = "2026-07-21T10:00:00+09:00";
  const result = await validateFixture(t, report);
  assert.notEqual(result.status, 0, "self-integrated editorial cannot claim a later edit");
});

test("topics_v1 stock evidence and permanent reading prose reject whitespace-only strings", async (t) => {
  for (const [name, mutate] of [
    ["stock evidence", (report) => {
      Object.assign(report.cards[0].scenarios[0].beneficiaries[1], {
        kind: "stock", name: "가상기업 (ZZZZ)", evidence: "   ",
      });
    }],
    ["editorial headline", (report) => { report.editorial.headline = "   "; }],
    ["editorial takeaway", (report) => { report.editorial.takeaways[0].text = "   "; }],
    ["brief summary", (report) => { report.cards[0].brief.summary = "   "; }],
    ["scenario thesis", (report) => { report.cards[0].scenarios[0].thesis = " \n "; }],
    ["beneficiary name", (report) => {
      report.cards[0].scenarios[0].beneficiaries[0].name = " \n ";
    }],
    ["error reason", (report) => {
      report.cards[2].scenarios = [];
      report.cards[2].error = " \n ";
    }],
  ]) {
    const report = structuredClone(READABLE_TOPICS_V1_REPORT);
    mutate(report);
    const result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${name} must contain visible prose`);
  }
});

for (const [name, mutate] of [
  ["duplicate topicKey", (report) => { report.cards[2].topicKey = "ai-power-grid"; }],
  ["lead-title mismatch", (report) => { report.title = "리드 카드와 다른 제목"; }],
  ["absent card title", (report) => { delete report.cards[2].title; }],
  ["absent beneficiary kind", (report) => { delete report.cards[0].scenarios[0].beneficiaries[0].kind; }],
  ["absent beneficiary direction", (report) => { delete report.cards[0].scenarios[0].beneficiaries[0].direction; }],
  ["absent beneficiary polarity", (report) => { delete report.cards[0].scenarios[0].beneficiaries[0].polarity; }],
  ["absent beneficiary causalChain", (report) => { delete report.cards[0].scenarios[0].beneficiaries[0].causalChain; }],
  ["absent beneficiary evidence", (report) => { delete report.cards[0].scenarios[0].beneficiaries[0].evidence; }],
  ["error card with scenarios", (report) => { report.cards[2].error = "generation timeout"; }],
]) {
  test(`transport contract rejects ${name}`, async (t) => {
    const report = structuredClone(TOPICS_V1_REPORT);
    mutate(report);
    const result = await validateFixture(t, report);
    assert.notEqual(result.status, 0, `${name} must be rejected`);
  });
}

test("market report round-trips through real list/detail handlers", async (t) => {
  const root = await createTestRoot();
  const dir = join(root, "storage", "rag", "memory_sector", "reports");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, `${REPORT.id}.json`), JSON.stringify(REPORT, null, 2));
  const edited = {
    ...REPORT,
    id: "2026-07-21-2",
    seq: 2,
    editorial: {
      label: "읽기 편집본",
      baseReportId: REPORT.id,
      baseGeneratedAt: REPORT.generatedAt,
      editedAt: "2026-07-21T14:30:00+09:00",
      headline: "핵심을 먼저 읽는 편집 제목",
      deck: "원문 근거는 보존한다.",
      takeaways: [
        { axis: "macro", title: "거시", text: "핵심 신호" },
        { axis: "memory", title: "메모리", text: "핵심 신호" },
        { axis: "other", title: "기타", text: "핵심 신호" },
      ],
    },
  };
  await writeFile(join(dir, `${edited.id}.json`), JSON.stringify(edited, null, 2));
  const app = await startTestServer({ root });
  t.after(() => app.stop({ removeRoot: true }));

  const list = await requestJson(app.baseUrl, "/api/market-reports");
  assert.equal(list.response.status, 200);
  assert.equal(list.body.ok, true);
  const meta = list.body.reports.find((r) => r.id === REPORT.id);
  assert.ok(meta, "saved report appears in list");
  assert.equal(meta.claimCount, 1);
  assert.equal(meta.title, REPORT.title);
  assert.equal(list.body.reports[0].id, edited.id, "later editorial work sorts ahead of its source report");
  assert.deepEqual(list.body.reports[0].editorial, {
    label: edited.editorial.label,
    baseReportId: edited.editorial.baseReportId,
    editedAt: edited.editorial.editedAt,
    headline: edited.editorial.headline,
  });

  const detail = await requestJson(app.baseUrl, `/api/market-reports/${REPORT.id}`);
  assert.equal(detail.response.status, 200);
  const rep = detail.body.report;
  assert.equal(rep.finalOpinion.confidence, "낮");
  assert.ok(Array.isArray(rep.pipeline.stages));
  // 뷰어 렌더 안전: claims[].evidence와 stages[].items는 전부 문자열
  assert.ok(rep.claims.every((c) => c.evidence.every((e) => typeof e === "string")));
  assert.ok(rep.pipeline.stages.every((s) => (s.items || []).every((i) => typeof i === "string")));
  // rejected는 claims에 없어야 함(스펙 v3 — 뷰어가 status 무시)
  assert.ok(rep.claims.every((c) => c.status !== "rejected"));
});
