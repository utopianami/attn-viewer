import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { saveCard, loadCard, validateQuotes, needsReview } from "./thinking-cards.mjs";

test("saveCard/loadCard roundtrip", async () => {
  const corpusRoot = await mkdtemp(join(tmpdir(), "cards-test-"));
  await saveCard(corpusRoot, "blogx", "naver-blogx-1", { situation: "메모리 사이클 판단" });
  const loaded = await loadCard(corpusRoot, "blogx", "naver-blogx-1");
  assert.equal(loaded.situation, "메모리 사이클 판단");
  assert.ok(loaded.extractedAt);
  assert.equal(await loadCard(corpusRoot, "blogx", "naver-blogx-2"), null);
});

test("validateQuotes: 원문에 있는 인용은 통과, 없는 인용은 null + 기록", () => {
  const body = "재고가   3개월치를 넘으면\n나는 상승 시나리오를 접는다.";
  const card = {
    checks: [
      { order: 1, what: "재고", why: "선행", kill: "3개월치 초과", quote: "재고가 3개월치를 넘으면 나는 상승 시나리오를 접는다" },
      { order: 2, what: "가격", why: null, kill: null, quote: "존재하지 않는 문장이다" },
    ],
    connection: { logic: "재고→가격", quote: null },
    reservations: { text: null, quote: null },
  };
  const { card: out, quoteFailures } = validateQuotes(card, body);
  assert.equal(out.checks[0].quote.includes("재고가"), true);   // 공백 차이는 정규화로 통과
  assert.equal(out.checks[1].quote, null);
  assert.deepEqual(quoteFailures, ["checks[1].quote"]);
});

test("needsReview: 인용 실패 또는 summaries 분류 불일치", () => {
  assert.equal(needsReview({ quoteFailures: ["checks[0].quote"] }, "reasoning"), true);
  assert.equal(needsReview({ quoteFailures: [] }, "info"), true);   // triage는 추론글이라 했는데 요약은 info
  assert.equal(needsReview({ quoteFailures: [] }, "reasoning"), false);
  assert.equal(needsReview({ quoteFailures: [] }, null), false);    // 요약 없으면 판단 보류
});
