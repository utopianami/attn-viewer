// 블로그 글 요약 — codex CLI(API 키 불필요)로 2문장 요약을 만들어 글 옆에 저장한다.
// 저장: corpus/naver/<blogId>/summaries/<articleId>.json
// 범위: SUMMARY_SINCE(2026-07-09) 이후 게시 글만 — 이전 글은 요약 없이 링크만 (사용자 결정).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { join } from "node:path";

export const SUMMARY_SINCE = "2026-07-09";

const MAX_BODY_CHARS = 6000;
const MIN_TEXT_CHARS = 60;

export function extractBody(markdown) {
  return String(markdown)
    .replace(/^---\n[\s\S]*?\n---\n/, "")
    .replace(/^# .*\n/, "")
    .trim();
}

// 이미지 placeholder만 있는 글은 요약할 텍스트가 없다.
// 인용 블록(>)은 본문으로 친다 — 링크 공유형 글(예: cybermw)은 내용이 인용 안에 있다.
export function hasSummarizableText(body) {
  const text = String(body)
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/^> ?링크:.*$/gm, "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/_[^_\n]*_/g, "")
    .replace(/[>#*\-|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length >= MIN_TEXT_CHARS;
}

export function buildPrompt(body) {
  return `다음은 투자 블로그 글이다. 이 글을 읽지 않아도 판단할 수 있게 요약하라.

규칙:
- 글의 정보량에 맞춰 2~5문장. 짧은 뉴스 공유 글이면 2문장이면 충분하고, 논증이 여러 단계인 분석 글이면 4~5문장까지 써라.
- 반드시 담을 것: ① 핵심 주장(그래서 뭐라는 글인가 — 제목 반복 금지) ② 그 주장의 근거 사슬(왜 그렇게 보는가) ③ 구체 숫자·종목·날짜가 있으면 포함 ④ 저자가 유보하거나 반대로 볼 여지를 언급했으면 그것도.
- 저자 본인의 견해와 단순 전달(인용·번역)을 구분하라. 저자 코멘트가 있으면 그의 시각이 드러나게.
- 말투는 평서형 종결("~다"). 다른 텍스트 없이 요약만 출력하라.

${body.slice(0, MAX_BODY_CHARS)}`;
}

function summaryPath(corpusRoot, blogId, articleId) {
  return join(corpusRoot, "naver", blogId, "summaries", `${articleId}.json`);
}

export async function loadSummary(corpusRoot, blogId, articleId) {
  try {
    return JSON.parse(await readFile(summaryPath(corpusRoot, blogId, articleId), "utf8"));
  } catch {
    return null;
  }
}

export async function saveSummary(corpusRoot, blogId, articleId, data) {
  const dir = join(corpusRoot, "naver", blogId, "summaries");
  await mkdir(dir, { recursive: true });
  const record = { id: articleId, createdAt: new Date().toISOString(), ...data };
  await writeFile(summaryPath(corpusRoot, blogId, articleId), `${JSON.stringify(record, null, 2)}\n`, "utf8");
  return record;
}

// 요약이 필요한 글 목록 — SUMMARY_SINCE 이후 게시 + summaries/ 파일 없음.
// noText=true 후보는 codex를 태우지 않고 no_text로 마킹만 한다.
export async function sweepCandidates(corpusRoot, blogIds) {
  const candidates = [];
  for (const blogId of blogIds) {
    let text;
    try {
      text = await readFile(join(corpusRoot, "naver", blogId, "index.jsonl"), "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) {
      if (!line) {
        continue;
      }
      let row;
      try {
        row = JSON.parse(line);
      } catch {
        continue;
      }
      // 날짜 비교는 KST 기준 — UTC로 자르면 한국 밤 시간대 글이 하루 밀린다
      const publishedTs = Date.parse(row.publishedAt || "");
      if (!Number.isFinite(publishedTs)) {
        continue;
      }
      const kstDay = new Date(publishedTs + 9 * 3600 * 1000).toISOString().slice(0, 10);
      if (kstDay < SUMMARY_SINCE) {
        continue;
      }
      if (await loadSummary(corpusRoot, blogId, row.id)) {
        continue;
      }
      let markdown;
      try {
        markdown = await readFile(join(corpusRoot, "naver", blogId, "articles", `${row.id}.md`), "utf8");
      } catch {
        continue;
      }
      const body = extractBody(markdown);
      candidates.push({
        blogId,
        id: row.id,
        title: row.title,
        body,
        noText: !hasSummarizableText(body),
      });
    }
  }
  return candidates;
}

// codex exec 1회 — 마지막 메시지를 파일로 받아 파싱 실수를 없앤다 (server.mjs runCodexNoteOnce 패턴)
export function runCodexSummary(prompt, { timeoutMs = 120_000 } = {}) {
  return new Promise((resolve, reject) => {
    const outputPath = join(
      process.env.TMPDIR || "/tmp",
      `blog-summary-${Date.now()}-${Math.random().toString(36).slice(2)}.txt`,
    );
    const child = spawn(
      "codex",
      ["-a", "never", "exec", "--ephemeral", "--sandbox", "read-only", "--output-last-message", outputPath, "-"],
      { stdio: ["pipe", "ignore", "pipe"] },
    );
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error("codex timeout"));
    }, timeoutMs);
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", async (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(`codex exit ${code}: ${stderr.slice(-200)}`));
        return;
      }
      try {
        const answer = (await readFile(outputPath, "utf8")).trim();
        resolve(answer);
      } catch (error) {
        reject(error);
      }
    });
    child.stdin.write(prompt);
    child.stdin.end();
  });
}

let sweepRunning = false;

// 스윕 실행 — 후보를 순차 요약(동시 1개). 이미 도는 중이면 재진입하지 않는다.
export async function runSummarySweep(corpusRoot, blogIds, { log = () => {} } = {}) {
  if (sweepRunning) {
    return { skipped: "already-running" };
  }
  sweepRunning = true;
  const result = { summarized: 0, noText: 0, failed: 0 };
  try {
    const candidates = await sweepCandidates(corpusRoot, blogIds);
    for (const candidate of candidates) {
      if (candidate.noText) {
        await saveSummary(corpusRoot, candidate.blogId, candidate.id, { summary: null, reason: "no_text" });
        result.noText += 1;
        continue;
      }
      try {
        const summary = await runCodexSummary(buildPrompt(candidate.body));
        if (!summary) {
          throw new Error("empty summary");
        }
        await saveSummary(corpusRoot, candidate.blogId, candidate.id, {
          summary,
          engine: "codex-cli",
          sourceContentHash: createHash("sha256").update(candidate.body).digest("hex"),
        });
        result.summarized += 1;
        log(`summarized ${candidate.id}`);
      } catch (error) {
        // 실패는 마킹하지 않는다 — 다음 스윕에서 재시도
        result.failed += 1;
        log(`summary failed ${candidate.id}: ${error.message}`);
      }
    }
  } finally {
    sweepRunning = false;
  }
  return result;
}
