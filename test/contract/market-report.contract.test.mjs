import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
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
      takeaways: [{ axis: "macro", title: "거시", text: "핵심 신호" }],
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
