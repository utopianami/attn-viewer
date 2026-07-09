import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  extractBody,
  hasSummarizableText,
  buildPrompt,
  saveSummary,
  loadSummary,
  sweepCandidates,
  SUMMARY_SINCE,
} from "./summaries.mjs";

async function makeCorpus() {
  return mkdtemp(join(tmpdir(), "summaries-test-"));
}

const FRONTMATTER = `---\nid: "x"\ntitle: "t"\n---\n# 제목\n\n`;

async function seedArticle(corpusRoot, blogId, logNo, { body, publishedAt }) {
  const id = `naver-${blogId}-${logNo}`;
  const root = join(corpusRoot, "naver", blogId);
  await mkdir(join(root, "articles"), { recursive: true });
  await writeFile(join(root, "articles", `${id}.md`), FRONTMATTER + body, "utf8");
  return JSON.stringify({ id, title: `post ${logNo}`, publishedAt, markdownPath: `articles/${id}.md` });
}

test("extractBody strips frontmatter and title heading", () => {
  const md = `---\nid: "a"\n---\n# 제목입니다\n\n본문 첫 줄\n\n둘째 줄`;
  assert.equal(extractBody(md), "본문 첫 줄\n\n둘째 줄");
});

test("hasSummarizableText rejects image-only and tiny bodies", () => {
  assert.equal(hasSummarizableText("![image 1](assets/x/image-01)\n\n![image 2](assets/x/image-02)"), false);
  assert.equal(hasSummarizableText("짧음"), false);
  assert.equal(
    hasSummarizableText(
      "국민연금의 리밸런싱 매도 부담은 주가 하락으로 일단 끝난 듯하지만, 목표비중 조정과 유예가 반복된 점이 문제라는 내용의 충분히 긴 본문 텍스트입니다.",
    ),
    true,
  );
});

test("buildPrompt includes body and summary rules", () => {
  const prompt = buildPrompt("본문입니다");
  assert.match(prompt, /2~5문장/);
  assert.match(prompt, /핵심 주장/);
  assert.match(prompt, /본문입니다/);
});

test("saveSummary/loadSummary roundtrip", async () => {
  const corpusRoot = await makeCorpus();
  await saveSummary(corpusRoot, "blogx", "naver-blogx-1", { summary: "요약문.", engine: "codex-cli" });
  const loaded = await loadSummary(corpusRoot, "blogx", "naver-blogx-1");
  assert.equal(loaded.summary, "요약문.");
  assert.ok(loaded.createdAt);
  assert.equal(await loadSummary(corpusRoot, "blogx", "naver-blogx-2"), null);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("sweepCandidates picks only recent posts lacking summaries", async () => {
  const corpusRoot = await makeCorpus();
  const root = join(corpusRoot, "naver", "blogx");
  const lines = [
    await seedArticle(corpusRoot, "blogx", 1, { body: "옛날 글이지만 충분히 긴 본문 텍스트가 들어있는 글입니다. 요약 대상이 아니어야 합니다. 날짜 기준으로 걸러지는지 확인하는 용도의 본문입니다.", publishedAt: "2026-07-01T00:00:00.000Z" }),
    await seedArticle(corpusRoot, "blogx", 2, { body: "오늘 게시된 충분히 긴 본문 텍스트가 들어있는 글입니다. 요약 대상이어야 합니다. 내용이 이어지고 문장이 하나 더 붙어서 최소 길이 기준을 확실히 넘깁니다.", publishedAt: `${SUMMARY_SINCE}T03:00:00.000Z` }),
    await seedArticle(corpusRoot, "blogx", 3, { body: "![image 1](assets/x/image-01)", publishedAt: `${SUMMARY_SINCE}T04:00:00.000Z` }),
    await seedArticle(corpusRoot, "blogx", 4, { body: "이미 요약된 충분히 긴 본문 텍스트가 들어있는 글입니다. 후보에서 빠져야 합니다. 내용이 이어지고 문장이 하나 더 붙어 길이 기준을 확실히 넘깁니다.", publishedAt: `${SUMMARY_SINCE}T05:00:00.000Z` }),
  ];
  await writeFile(join(root, "index.jsonl"), `${lines.join("\n")}\n`, "utf8");
  await saveSummary(corpusRoot, "blogx", "naver-blogx-4", { summary: "이미 있음." });

  const candidates = await sweepCandidates(corpusRoot, ["blogx"]);
  const ids = candidates.map((c) => c.id).sort();
  // 2 = 요약 대상, 3 = 본문 없음(스킵 마킹 대상으로 포함하되 noText 플래그)
  assert.deepEqual(ids, ["naver-blogx-2", "naver-blogx-3"]);
  const noText = candidates.find((c) => c.id === "naver-blogx-3");
  assert.equal(noText.noText, true);
  const ok = candidates.find((c) => c.id === "naver-blogx-2");
  assert.equal(ok.noText, false);
  assert.ok(ok.body.includes("오늘 게시된"));
  await rm(corpusRoot, { recursive: true, force: true });
});

test("sweepCandidates skips posts already marked no_text", async () => {
  const corpusRoot = await makeCorpus();
  const root = join(corpusRoot, "naver", "blogx");
  const lines = [
    await seedArticle(corpusRoot, "blogx", 3, { body: "![image 1](a)", publishedAt: `${SUMMARY_SINCE}T04:00:00.000Z` }),
  ];
  await writeFile(join(root, "index.jsonl"), `${lines.join("\n")}\n`, "utf8");
  await saveSummary(corpusRoot, "blogx", "naver-blogx-3", { summary: null, reason: "no_text" });
  const candidates = await sweepCandidates(corpusRoot, ["blogx"]);
  assert.equal(candidates.length, 0);
  await rm(corpusRoot, { recursive: true, force: true });
});
