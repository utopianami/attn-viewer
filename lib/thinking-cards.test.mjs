import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { saveCard, loadCard, validateQuotes, needsReview, SEMIS_RE, buildTriagePrompt, sweepTriageCandidates, loadTriageMap, appendTriage } from "./thinking-cards.mjs";

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

test("sweepTriageCandidates: 키워드 매칭 + 미처리 글만, 최신순", async () => {
  const corpusRoot = await mkdtemp(join(tmpdir(), "cards-sweep-"));
  const FM = `---\nid: "x"\n---\n# 제목\n\n`;

  async function seedPost(blogId, logNo, { body, publishedAt }) {
    const id = `naver-${blogId}-${logNo}`;
    const root = join(corpusRoot, "naver", blogId);
    await mkdir(join(root, "articles"), { recursive: true });
    await writeFile(join(root, "articles", `${id}.md`), FM + body, "utf8");
    return JSON.stringify({ id, title: `post ${logNo}`, publishedAt, markdownPath: `articles/${id}.md` });
  }

  const rows = [
    await seedPost("b", 1, { body: "HBM 수요가 늘고 있다는 판단의 근거는 다음과 같다.", publishedAt: "2026-07-01T09:00:00+09:00" }),
    await seedPost("b", 2, { body: "오늘은 날씨 얘기만 하겠다.", publishedAt: "2026-07-02T09:00:00+09:00" }),
    await seedPost("b", 3, { body: "하이닉스 재고를 보면 사이클이 보인다.", publishedAt: "2026-07-03T09:00:00+09:00" }),
  ];
  await writeFile(join(corpusRoot, "naver", "b", "index.jsonl"), rows.join("\n") + "\n", "utf8");
  await appendTriage(corpusRoot, "b", { id: "naver-b-3", semis: true, reasoning: true, at: "2026-07-13T00:00:00Z" });

  const candidates = await sweepTriageCandidates(corpusRoot, ["b"]);
  assert.deepEqual(candidates.map((c) => c.id), ["naver-b-1"]); // 2는 키워드 미매칭, 3은 처리됨
  assert.ok(candidates[0].body.includes("HBM"));

  const map = await loadTriageMap(corpusRoot, "b");
  assert.equal(map.get("naver-b-3").semis, true);
});

test("buildTriagePrompt: 판정 기준과 본문 포함", () => {
  const p = buildTriagePrompt("본문입니다");
  assert.match(p, /semis/);
  assert.match(p, /reasoning/);
  assert.match(p, /스치듯/);
  assert.match(p, /본문입니다/);
});
