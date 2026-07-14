import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { savePlaybook, loadPlaybooks, validatePlaybook } from "./playbooks.mjs";

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
