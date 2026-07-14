import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { saveCard, loadCard, validateQuotes, needsReview, SEMIS_RE, buildTriagePrompt, sweepTriageCandidates, loadTriageMap, appendTriage, buildExtractPrompt, extractCard } from "./thinking-cards.mjs";

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

test("buildExtractPrompt: 4층 요구 + 인용 규칙 + 킬 조건 캐묻기", () => {
  const p = buildExtractPrompt("제목", "본문입니다");
  assert.match(p, /situation/);
  assert.match(p, /kill/);
  assert.match(p, /원문에서 그대로 복사/);
  assert.match(p, /일반론/);
  assert.match(p, /본문입니다/);
});

test("validateQuotes: 목록 번호·이미지가 끼어도 문장 단위로 통과, 지어낸 문장은 실패", () => {
  const body = "일본은 버틸수 있다고 생각했었음. 4. 생각하지 못한 곳에서 문제가 터짐. ![image 1](assets/x) 5. 중국의 고순도 텅스텐 분말이 문제였음.";
  const okCard = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "일본은 버틸수 있다고 생각했었음. 생각하지 못한 곳에서 문제가 터짐. 중국의 고순도 텅스텐 분말이 문제였음." }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  const r1 = validateQuotes(okCard, body);
  assert.deepEqual(r1.quoteFailures, []);
  assert.ok(r1.card.checks[0].quote); // 원문 유지

  const badCard = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "일본은 버틸수 있다고 생각했었음. 이 문장은 원문에 없는 지어낸 문장임." }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  const r2 = validateQuotes(badCard, body);
  assert.deepEqual(r2.quoteFailures, ["checks[0].quote"]);
  assert.equal(r2.card.checks[0].quote, null);
});

test("validateQuotes: 문장 재배열 합성 인용은 실패", () => {
  const body = "먼저 재고를 봤다. 4. 그 다음 가격을 봤다. 5. 결론은 유보다.";
  const card = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "결론은 유보다. 먼저 재고를 봤다." }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  assert.deepEqual(validateQuotes(card, body).quoteFailures, ["checks[0].quote"]);
});

test("validateQuotes: 5자 미만 지어낸 조각도 잡는다 (마커만 스킵)", () => {
  const body = "먼저 재고를 봤다. 4. 그 다음 가격을 봤다.";
  const card = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "없는말. 먼저 재고를 봤다." }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  assert.deepEqual(validateQuotes(card, body).quoteFailures, ["checks[0].quote"]);
});

test("validateQuotes: 종결 부호 없는 문단 + 사이 이미지도 문단 단위로 통과", () => {
  // tosoha1 실측 오탐 (2026-07-14): "~같음"처럼 마침표 없이 끝난 문단 뒤에 이미지가 끼면
  // 문장부호 분할만으로는 두 문단이 한 조각으로 붙어 실패했었다.
  const body = "FCF를 비교해보면 다음과 같음(최근 4개분기 합산으로)\n\n![image 3](assets/x)\n\n브로드컴이 2배가 좀 넘는 FCF 창출 중.";
  const card = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "FCF를 비교해보면 다음과 같음(최근 4개분기 합산으로)\n\n브로드컴이 2배가 좀 넘는 FCF 창출 중." }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  const r = validateQuotes(card, body);
  assert.deepEqual(r.quoteFailures, []);

  // 문단 재배열은 여전히 실패해야 한다
  const swapped = { checks: [{ order: 1, what: "w", why: null, kill: null,
    quote: "브로드컴이 2배가 좀 넘는 FCF 창출 중.\n\nFCF를 비교해보면 다음과 같음(최근 4개분기 합산으로)" }],
    connection: { logic: null, quote: null }, reservations: { text: null, quote: null } };
  assert.deepEqual(validateQuotes(swapped, body).quoteFailures, ["checks[0].quote"]);
});

test("extractCard: 인용 검증·검수 플래그·해시 포함 저장", async () => {
  const corpusRoot = await mkdtemp(join(tmpdir(), "cards-extract-"));
  const body = "재고가 3개월치를 넘으면 나는 상승 시나리오를 접는다.";
  const fakeRun = async () => JSON.stringify({
    situation: "메모리 사이클 판단",
    checks: [{ order: 1, what: "재고", why: "선행 지표", kill: "3개월치 초과", quote: "재고가 3개월치를 넘으면" },
             { order: 2, what: "환율", why: null, kill: null, quote: "본문에 없는 문장" }],
    connection: { logic: "재고→시나리오 유지 여부", quote: null },
    reservations: { text: null, quote: null },
    conclusionType: "방향 판단",
    topics: ["재고"],
  });
  const record = await extractCard(corpusRoot,
    { blogId: "b", id: "naver-b-9", title: "t", body, publishedAt: "2026-07-01T00:00:00+09:00" },
    { summaryType: "reasoning", runCodex: fakeRun });
  assert.equal(record.checks[1].quote, null);
  assert.deepEqual(record.quoteFailures, ["checks[1].quote"]);
  assert.equal(record.needsReview, true);           // 인용 실패 1건
  assert.equal(record.engine, "codex-cli");
  assert.ok(record.sourceContentHash);
  assert.equal((await loadCard(corpusRoot, "b", "naver-b-9")).situation, "메모리 사이클 판단");
});
