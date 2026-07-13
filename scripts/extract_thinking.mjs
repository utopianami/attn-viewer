// scripts/extract_thinking.mjs — 사고 카드 추출 배치 (재개 가능)
// 사용: node scripts/extract_thinking.mjs --user ryze_yn --stage all --limit 30 [--blogId ranto28] [--skip-after 2026-06-01]
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  sweepTriageCandidates, appendTriage, loadTriageMap, loadCard, extractCard, buildTriagePrompt,
} from "../lib/thinking-cards.mjs";
import { runCodexSummary, loadSummary, extractBody } from "../lib/summaries.mjs";

const args = process.argv.slice(2);
function flag(name, fallback = null) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
}
const user = flag("user");
if (!user) {
  console.error("--user 필수");
  process.exit(1);
}
const stage = flag("stage", "all");
const onlyBlog = flag("blogId");
const limit = Number(flag("limit", "0")) || Infinity;
const skipAfter = flag("skip-after"); // 이 날짜(KST) 이후 게시 글은 추출 제외 — holdout 보존용
const corpusRoot = join(process.cwd(), "storage", "users", user, "corpus");
const TRIAGE_SCHEMA = join(process.cwd(), "schemas", "thinking-triage.schema.json");

async function activeBlogIds() {
  const registry = JSON.parse(await readFile(join(corpusRoot, "blogs.json"), "utf8"));
  return registry.blogs.filter((b) => b.active).map((b) => b.id);
}

function kstDay(iso) {
  const ts = Date.parse(iso || "");
  return Number.isFinite(ts) ? new Date(ts + 9 * 3600 * 1000).toISOString().slice(0, 10) : null;
}

const job = { startedAt: new Date().toISOString(), stage, triaged: 0, passed: 0, extracted: 0, failed: 0, reviewQueue: [], errors: [], done: false };

async function runTriage(blogIds) {
  const candidates = (await sweepTriageCandidates(corpusRoot, blogIds)).slice(0, limit);
  console.log(`triage 후보 ${candidates.length}건`);
  for (const c of candidates) {
    try {
      const raw = await runCodexSummary(buildTriagePrompt(c.body), { schemaPath: TRIAGE_SCHEMA });
      const verdict = JSON.parse(raw);
      await appendTriage(corpusRoot, c.blogId, { id: c.id, semis: !!verdict.semis, reasoning: !!verdict.reasoning, at: new Date().toISOString() });
      job.triaged += 1;
      if (verdict.semis && verdict.reasoning) job.passed += 1;
      console.log(`triage ${c.id} semis=${verdict.semis} reasoning=${verdict.reasoning}`);
    } catch (error) {
      job.failed += 1;
      job.errors.push({ id: c.id, stage: "triage", error: String(error.message || error) });
      console.error(`triage 실패 ${c.id}: ${error.message}`);
    }
  }
}

async function runExtract(blogIds) {
  let extracted = 0;
  for (const blogId of blogIds) {
    const triage = await loadTriageMap(corpusRoot, blogId);
    // 최신→과거 정렬
    const rows = [...triage.values()].filter((r) => r.semis && r.reasoning);
    const withDates = [];
    for (const r of rows) {
      if (await loadCard(corpusRoot, blogId, r.id)) continue; // 재개: 이미 추출됨
      let markdown;
      try {
        markdown = await readFile(join(corpusRoot, "naver", blogId, "articles", `${r.id}.md`), "utf8");
      } catch {
        continue;
      }
      // publishedAt은 index.jsonl에서
      withDates.push({ blogId, id: r.id, markdown });
    }
    const index = new Map();
    try {
      for (const line of (await readFile(join(corpusRoot, "naver", blogId, "index.jsonl"), "utf8")).split("\n")) {
        if (!line) continue;
        try { const row = JSON.parse(line); index.set(row.id, row); } catch { /* skip */ }
      }
    } catch { /* index 없으면 날짜 없이 진행 */ }
    for (const item of withDates) {
      const meta = index.get(item.id) || {};
      if (skipAfter && kstDay(meta.publishedAt) && kstDay(meta.publishedAt) > skipAfter) continue; // holdout 보존
      item.title = meta.title || "";
      item.publishedAt = meta.publishedAt || "";
      item.body = extractBody(item.markdown);
    }
    withDates.sort((a, b) => ((a.publishedAt || "") < (b.publishedAt || "") ? 1 : -1));
    for (const item of withDates) {
      if (extracted >= limit) return;
      if (item.body === undefined) continue; // skipAfter로 걸러진 항목
      try {
        const summary = await loadSummary(corpusRoot, item.blogId, item.id);
        const record = await extractCard(corpusRoot, item, { summaryType: summary?.type || null });
        extracted += 1;
        job.extracted += 1;
        if (record.needsReview) job.reviewQueue.push(`${item.blogId}/${item.id}`);
        console.log(`extract ${item.id} quoteFailures=${record.quoteFailures.length} review=${record.needsReview}`);
      } catch (error) {
        job.failed += 1;
        job.errors.push({ id: item.id, stage: "extract", error: String(error.message || error) });
        console.error(`extract 실패 ${item.id}: ${error.message}`);
      }
    }
  }
}

const blogIds = onlyBlog ? [onlyBlog] : await activeBlogIds();
if (stage === "triage" || stage === "all") await runTriage(blogIds);
if (stage === "extract" || stage === "all") await runExtract(blogIds);
job.done = true;
job.finishedAt = new Date().toISOString();
await mkdir(join(corpusRoot, "analysis-jobs"), { recursive: true });
const jobPath = join(corpusRoot, "analysis-jobs", `${job.startedAt.replace(/[:.]/g, "-")}.json`);
await writeFile(jobPath, `${JSON.stringify(job, null, 2)}\n`, "utf8");
console.log(`job 로그: ${jobPath}`);
console.log(`검수 대상 ${job.reviewQueue.length}건:`, job.reviewQueue.join(", ") || "없음");
