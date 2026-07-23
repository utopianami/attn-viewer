import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { savePlaybook, loadPlaybooks, validatePlaybook, loadAllCards, loadAllCardsWithReview, buildClusterPrompt, pickHoldout, buildPlaybookPrompt, synthesizePlaybook, buildPredictionPrompt, buildJudgePrompt, scorePlaybook, alignVerdicts, buildMatchKeysPrompt } from "./playbooks.mjs";

const basePlaybook = () => ({
  slug: "memory-cycle-direction",
  situation: "메모리 사이클 방향 판단",
  triggers: ["감산", "재고"],
  topics: ["DRAM"],
  conclusionType: "방향 판단",
  gates: [
    { order: 1, check: "재고 주수 확인", why: null, kill: "재고 20주 이상이면 회복 시나리오 기각",
      operationalization: "고객사 재고 주수 8주 미만", evidence: ["naver-ranto28-1"] },
  ],
  connection: "재고와 가격의 방향이 일치할 때만 결론",
  reservations: null,
  asOf: "2026-07",
  sources: { bloggers: ["ranto28"], articleCount: 3 },
  status: "draft",
});

test("savePlaybook/loadPlaybooks 왕복", async () => {
  const root = await mkdtemp(join(tmpdir(), "pb-"));
  await savePlaybook(root, basePlaybook());
  const list = await loadPlaybooks(root);
  assert.equal(list.length, 1);
  assert.equal(list[0].slug, "memory-cycle-direction");
  assert.ok(list[0].synthesizedAt);
});

test("validatePlaybook: 실존하지 않는 evidence 카드 id는 게이트 드롭", () => {
  const pb = basePlaybook();
  pb.gates.push({ order: 2, check: "x", why: null, kill: null,
    operationalization: "y", evidence: ["naver-ghost-999"] });
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 1);
  assert.deepEqual(dropped, ["gates[2]: evidence 미실존 naver-ghost-999"]);
});

test("validatePlaybook: operationalization 없는 게이트는 채택 보류(드롭)", () => {
  const pb = basePlaybook();
  pb.gates.push({ order: 2, check: "x", why: null, kill: null,
    operationalization: null, evidence: ["naver-ranto28-1"] });
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 1);
  assert.equal(dropped.length, 1);
});

test("validatePlaybook: 게이트 7개 초과는 8번째부터 드롭", () => {
  const pb = basePlaybook();
  pb.gates = Array.from({ length: 9 }, (_, i) => ({ order: i + 1, check: `c${i}`, why: null,
    kill: null, operationalization: "기준", evidence: ["naver-ranto28-1"] }));
  const { playbook } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 7);
});

test("validatePlaybook: 단일 블로거 3편 미만이면 전체 거부", () => {
  const pb = basePlaybook();
  pb.sources = { bloggers: ["ranto28"], articleCount: 2 };
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook, null);
  assert.ok(dropped[0].includes("단일 블로거"));
});

test("loadAllCards: needsReview 카드는 합성 입력에서 제외", async () => {
  const root = await mkdtemp(join(tmpdir(), "cards-"));
  const dir = join(root, "naver", "b1", "analysis");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "a1.json"), JSON.stringify({ id: "a1", situation: "s", needsReview: false, topics: [] }));
  await writeFile(join(dir, "a2.json"), JSON.stringify({ id: "a2", situation: "s", needsReview: true, topics: [] }));
  await writeFile(join(dir, "triage.jsonl"), "");
  const cards = await loadAllCards(root);
  assert.deepEqual(cards.map((c) => c.id), ["a1"]);
  assert.equal(cards[0].blogId, "b1");
});

test("buildClusterPrompt: 카드당 한 줄 + 최소 3편 규칙 명시", () => {
  const p = buildClusterPrompt([
    { id: "a1", blogId: "b1", situation: "메모리 사이클 판단", conclusionType: "방향 판단", topics: ["DRAM"] },
  ]);
  assert.ok(p.includes("a1"));
  assert.ok(p.includes("3편"));
});

test("pickHoldout: 4편 이상 클러스터에서 최신 20%(최소 1장)를 뽑고, 3편 클러스터는 비움", () => {
  const mk = (id, at) => ({ id, publishedAt: at });
  const cards = [mk("a1", "2026-01"), mk("a2", "2026-02"), mk("a3", "2026-03"),
    mk("a4", "2026-04"), mk("b1", "2026-01"), mk("b2", "2026-02"), mk("b3", "2026-03")];
  const clusters = [
    { slug: "big", cardIds: ["a1", "a2", "a3", "a4"] },
    { slug: "small", cardIds: ["b1", "b2", "b3"] },
  ];
  const holdout = pickHoldout(clusters, cards);
  assert.deepEqual(holdout.get("big"), ["a4"]); // 최신 1장
  assert.deepEqual(holdout.get("small"), []);   // 3편은 남기면 3편 미만 — holdout 없음(draft 유지)
});

test("buildPlaybookPrompt: 카드 checks·kill 포함, 평균화 금지 명시", () => {
  const clusterCards = [
    { id: "a1", blogId: "b1", publishedAt: "2026-01", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "재고 주수", why: "선행지표", kill: "20주 이상이면 기각", quote: "원문" }],
      connection: { logic: "재고→가격", quote: "원문" }, reservations: { text: "환율 변수는 유보", quote: null } },
    { id: "a2", blogId: "b2", publishedAt: "2026-02", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "가격 방향", why: null, kill: null, quote: "원문" }],
      connection: { logic: "가격→실적", quote: "원문" }, reservations: { text: null, quote: null } },
    { id: "a3", blogId: "b1", publishedAt: "2026-03", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "CAPEX", why: null, kill: null, quote: "원문" }],
      connection: { logic: "CAPEX→공급", quote: "원문" }, reservations: { text: null, quote: null } },
  ];
  const p = buildPlaybookPrompt({ slug: "s", situation: "메모리 사이클 판단", cardIds: ["a1", "a2", "a3"] }, clusterCards);
  assert.ok(p.includes("재고 주수"));
  assert.ok(p.includes("20주 이상이면 기각"));
  assert.ok(p.includes("evidence"));
});

test("synthesizePlaybook: codex 응답 → 검증 → draft 저장, sources는 코드가 계산", async () => {
  const root = await mkdtemp(join(tmpdir(), "pb-syn-"));
  const clusterCards = [
    { id: "a1", blogId: "b1", publishedAt: "2026-01", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "재고 주수", why: "선행지표", kill: "20주 이상이면 기각", quote: "원문" }],
      connection: { logic: "재고→가격", quote: "원문" }, reservations: { text: "환율 변수는 유보", quote: null } },
    { id: "a2", blogId: "b2", publishedAt: "2026-02", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "가격 방향", why: null, kill: null, quote: "원문" }],
      connection: { logic: "가격→실적", quote: "원문" }, reservations: { text: null, quote: null } },
    { id: "a3", blogId: "b1", publishedAt: "2026-03", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "CAPEX", why: null, kill: null, quote: "원문" }],
      connection: { logic: "CAPEX→공급", quote: "원문" }, reservations: { text: null, quote: null } },
  ];
  const fake = JSON.stringify({
    situation: "메모리 사이클 방향 판단", triggers: ["감산"], conclusionType: "방향 판단",
    gates: [{ order: 1, check: "재고 주수", why: null, kill: "20주 이상 기각",
      operationalization: "재고 8주 미만", evidence: ["a1"] }],
    connection: "재고와 가격 방향 일치 시 결론", reservations: null, asOf: "2026-07",
  });
  const rec = await synthesizePlaybook(root,
    { slug: "memory-cycle", situation: "메모리 사이클 판단", cardIds: ["a1", "a2", "a3"] },
    clusterCards, { runCodex: async () => fake });
  assert.equal(rec.status, "draft");
  assert.deepEqual(rec.sources, { bloggers: ["b1", "b2"], articleCount: 3 });
  assert.deepEqual(rec.topics, ["DRAM"]);
  const list = await loadPlaybooks(root);
  assert.equal(list[0].slug, "memory-cycle");
});

test("synthesizePlaybook: holdout 카드(클러스터에만 있고 전달된 배열에 없음)에 대한 evidence는 드롭", async () => {
  const root = await mkdtemp(join(tmpdir(), "pb-holdout-"));
  const clusterCards = [
    { id: "a1", blogId: "b1", publishedAt: "2026-01", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "재고 주수", why: "선행지표", kill: "20주 이상이면 기각", quote: "원문" }],
      connection: { logic: "재고→가격", quote: "원문" }, reservations: { text: "환율 변수는 유보", quote: null } },
    { id: "a2", blogId: "b2", publishedAt: "2026-02", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "가격 방향", why: null, kill: null, quote: "원문" }],
      connection: { logic: "가격→실적", quote: "원문" }, reservations: { text: null, quote: null } },
    { id: "a3", blogId: "b1", publishedAt: "2026-03", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
      topics: ["DRAM"], checks: [{ order: 1, what: "CAPEX", why: null, kill: null, quote: "원문" }],
      connection: { logic: "CAPEX→공급", quote: "원문" }, reservations: { text: null, quote: null } },
  ];
  const fake = JSON.stringify({
    situation: "메모리 사이클 방향 판단", triggers: ["감산"], conclusionType: "방향 판단",
    gates: [{ order: 1, check: "재고 주수", why: null, kill: "20주 이상 기각",
      operationalization: "재고 8주 미만", evidence: ["a-holdout"] }],
    connection: "재고와 가격 방향 일치 시 결론", reservations: null, asOf: "2026-07",
  });
  const rec = await synthesizePlaybook(root,
    { slug: "memory-holdout", situation: "메모리 사이클 판단", cardIds: ["a1", "a2", "a3", "a-holdout"] },
    clusterCards, { runCodex: async () => fake });
  assert.equal(rec, null);
});

test('buildPredictionPrompt: 플레이북 있으면 절차 포함+사실 사용 금지, 없으면(대조군) 미포함', () => {
  const pb = basePlaybook();
  const withPb = buildPredictionPrompt('메모리 사이클 판단', pb);
  assert.ok(withPb.includes('재고 주수 확인'));
  assert.ok(withPb.includes('사실'));               // 절차로만 쓰라는 경계 문구
  const control = buildPredictionPrompt('메모리 사이클 판단', null);
  assert.ok(!control.includes('재고 주수 확인'));
});

test('scorePlaybook: 실제 check 커버율과 킬 조건 재현율 집계', () => {
  const verdicts = [ // 심판 출력: holdout 카드의 check 하나당 한 항목
    { covered: true, killCovered: true, hasKill: true, predictedOrder: 1 },
    { covered: true, killCovered: false, hasKill: true, predictedOrder: 2 },
    { covered: false, killCovered: false, hasKill: false, predictedOrder: null },
  ];
  const s = scorePlaybook([verdicts]);
  assert.equal(s.coverage.toFixed(2), '0.67');   // 2/3
  assert.equal(s.killRecall.toFixed(2), '0.50'); // 킬 있는 check 2개 중 1개
  assert.equal(s.orderScore, 1);                 // predictedOrder 1<2 → 정순
});

test('scorePlaybook: orderScore — 역순 예측은 0, 정순은 1, covered 2개 미만이면 1', () => {
  // 역순: 실제 순서 idx 0,1 이지만 predictedOrder 2,1 → 역순 쌍 → orderScore 0
  const reversed = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 2 },
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 1 },
    { covered: false, killCovered: false, hasKill: false, predictedOrder: null },
  ];
  assert.equal(scorePlaybook([reversed]).orderScore, 0);

  // 정순: predictedOrder 1,2 → orderScore 1
  const forward = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 1 },
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 2 },
    { covered: false, killCovered: false, hasKill: false, predictedOrder: null },
  ];
  assert.equal(scorePlaybook([forward]).orderScore, 1);

  // covered 1개만: orderScore 1 (쌍 없음)
  const one = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 3 },
    { covered: false, killCovered: false, hasKill: false, predictedOrder: null },
  ];
  assert.equal(scorePlaybook([one]).orderScore, 1);
});

test('scorePlaybook: 두 완벽한 카드는 경계 혼합 없이 orderScore 1', () => {
  const card1 = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 1 },
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 2 },
  ];
  const card2 = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 1 },
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 2 },
  ];
  const s = scorePlaybook([card1, card2]);
  assert.equal(s.orderScore, 1);  // each card: 1 pair, 1 correct → pool 2/2=1
  assert.equal(s.coverage, 1);
});

test('scorePlaybook: covered=true + predictedOrder null은 분모에 포함(잘못된 쌍)', () => {
  // card with 2 items: first covered+null, second covered+2
  // pairs: (null, 2) → null cannot be < 2, so NOT correctly ordered → 0/1
  const group = [
    { covered: true, killCovered: false, hasKill: false, predictedOrder: null },
    { covered: true, killCovered: false, hasKill: false, predictedOrder: 2 },
  ];
  const s = scorePlaybook([group]);
  assert.equal(s.orderScore, 0);
});

test('alignVerdicts: order 정렬, 누락 항목은 covered=false, hasKill은 카드에서 결정, 중복은 첫 번째', () => {
  const card = {
    checks: [
      { order: 1, what: '재고 주수', kill: '20주 이상 기각' }, // hasKill=true
      { order: 2, what: '가격 방향', kill: null },             // hasKill=false
      { order: 3, what: 'CAPEX', kill: '감소세면 기각' },      // hasKill=true, verdict 없음
    ],
  };
  const items = [
    { order: 1, covered: true, killCovered: true, hasKill: false, predictedOrder: 2 },  // hasKill 무시 — 코드가 결정
    { order: 1, covered: false, killCovered: false, hasKill: true, predictedOrder: 1 }, // 중복 order 1 — 무시
    { order: 2, covered: false, killCovered: false, hasKill: true, predictedOrder: null }, // hasKill 무시
    // order 3 없음 — 누락 처리
  ];
  const result = alignVerdicts(card, items);
  assert.equal(result.length, 3);
  assert.deepEqual(result[0], { covered: true, killCovered: true, hasKill: true, predictedOrder: 2 });   // order 1, kill있음
  assert.deepEqual(result[1], { covered: false, killCovered: false, hasKill: false, predictedOrder: null }); // order 2, kill없음, uncovered→null
  assert.deepEqual(result[2], { covered: false, killCovered: false, hasKill: true, predictedOrder: null }); // order 3, 누락→false, kill있음
});

test('loadPlaybooks: holdout-report.json은 로드하지 않음', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pb-report-'));
  await savePlaybook(root, basePlaybook());
  // holdout-report.json을 playbooks 디렉터리에 직접 씀
  const { playbooksDir: pbDir } = await import('./playbooks.mjs');
  await writeFile(join(pbDir(root), 'holdout-report.json'),
    JSON.stringify({ judgedAt: new Date().toISOString(), report: [] }), 'utf8');
  const list = await loadPlaybooks(root);
  assert.equal(list.length, 1);
  assert.equal(list[0].slug, 'memory-cycle-direction');
});

test("buildPlaybookPrompt는 구조 게이트 필드 지시와 metric 메뉴를 포함한다", () => {
  const prompt = buildPlaybookPrompt({ slug: "s", situation: "x", cardIds: [] }, []);
  assert.match(prompt, /metric_id/);
  assert.match(prompt, /memory_price_usd_per_gb/);   // ENGINE_METRIC_IDS 메뉴
  assert.match(prompt, /max_age_days/);
});

test("validatePlaybook은 완전한 구조 게이트를 보존하고 불완전분은 strip한다", () => {
  const base = { order: 1, check: "c", operationalization: "o", evidence: ["k1"] };
  const full = { ...base, metric_id: "memory_price_usd_per_gb",
    selector: { meta_filter: { category: "DRAM" } }, aggregation: "last",
    comparator: ">=", threshold: 0.05, unit: "USD/GB", max_age_days: 45 };
  const partial = { ...base, order: 2, metric_id: "memory_price_usd_per_gb" };
  const badId = { ...full, order: 3, metric_id: "no_such_metric" };
  const { playbook, dropped } = validatePlaybook(
    { gates: [full, partial, badId] }, new Set(["k1"]));
  assert.equal(playbook.gates[0].metric_id, "memory_price_usd_per_gb"); // 완전 → 보존
  assert.equal(playbook.gates[1].metric_id, undefined);   // 일부만 → strip (all-or-none)
  assert.equal(playbook.gates[2].metric_id, undefined);   // 미등록 id → strip
  assert.ok(dropped.some((d) => d.includes("구조 필드")));
});

test("playbook.schema.json: 게이트 항목 스키마가 구조 게이트 필드 8종을 opt-in으로 허용한다", async () => {
  const schemaPath = fileURLToPath(new URL("../schemas/playbook.schema.json", import.meta.url));
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const gateItemSchema = schema.properties.gates.items;
  const structuralFields = [
    "metric_id", "selector", "aggregation", "window_days",
    "comparator", "threshold", "unit", "max_age_days",
  ];
  for (const field of structuralFields) {
    assert.ok(field in gateItemSchema.properties, `${field}는 gate 항목 properties에 있어야 함`);
    assert.ok(!gateItemSchema.required.includes(field), `${field}는 required에 없어야 함(opt-in)`);
  }
});
