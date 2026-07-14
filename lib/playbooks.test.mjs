import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { savePlaybook, loadPlaybooks, validatePlaybook, loadAllCards, buildClusterPrompt, pickHoldout } from "./playbooks.mjs";

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
