import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { savePlaybook, loadPlaybooks, validatePlaybook, loadAllCards, loadAllCardsWithReview, buildClusterPrompt, pickHoldout, buildPlaybookPrompt, synthesizePlaybook, buildPredictionPrompt, buildJudgePrompt, scorePlaybook } from "./playbooks.mjs";

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
    { covered: true, killCovered: true, hasKill: true },
    { covered: true, killCovered: false, hasKill: true },
    { covered: false, killCovered: false, hasKill: false },
  ];
  const s = scorePlaybook(verdicts);
  assert.equal(s.coverage.toFixed(2), '0.67');   // 2/3
  assert.equal(s.killRecall.toFixed(2), '0.50'); // 킬 있는 check 2개 중 1개
});
