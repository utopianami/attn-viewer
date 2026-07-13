// 사고 카드 — 블로그 글에서 추출한 사고 구조를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { extractBody } from "./summaries.mjs";

function cardPath(corpusRoot, blogId, articleId) {
  return join(corpusRoot, "naver", blogId, "analysis", `${articleId}.json`);
}

export async function loadCard(corpusRoot, blogId, articleId) {
  try {
    return JSON.parse(await readFile(cardPath(corpusRoot, blogId, articleId), "utf8"));
  } catch {
    return null;
  }
}

export async function saveCard(corpusRoot, blogId, articleId, card) {
  const dir = join(corpusRoot, "naver", blogId, "analysis");
  await mkdir(dir, { recursive: true });
  const record = { ...card, id: articleId, extractedAt: new Date().toISOString() };
  await writeFile(cardPath(corpusRoot, blogId, articleId), `${JSON.stringify(record, null, 2)}\n`, "utf8");
  return record;
}

// 인용 대조는 공백 정규화 후 부분 문자열 검사 — 줄바꿈·연속 공백 차이는 허용, 단어 변형은 불허.
function normalize(s) {
  return String(s).replace(/\s+/g, " ").trim();
}

export function validateQuotes(card, body) {
  const haystack = normalize(body);
  const quoteFailures = [];
  const checkQuote = (holder, path) => {
    if (!holder || holder.quote == null) return;
    if (!haystack.includes(normalize(holder.quote))) {
      holder.quote = null;
      quoteFailures.push(path);
    }
  };
  const out = structuredClone(card);
  (out.checks || []).forEach((c, i) => checkQuote(c, `checks[${i}].quote`));
  checkQuote(out.connection, "connection.quote");
  checkQuote(out.reservations, "reservations.quote");
  return { card: out, quoteFailures };
}

// 검수 라우팅 — 인용 실패가 있거나, 기존 summaries 분류(reasoning/info/note/chat)와 어긋나면 사람 확인 대상.
export function needsReview(card, summaryType) {
  if ((card.quoteFailures || []).length > 0) return true;
  if (summaryType && summaryType !== "reasoning") return true;
  return false;
}

// 퍼널 ①② — 키워드 필터 · triage 후보 스윕 · triage 기록
export const SEMIS_RE = /HBM|하이닉스|마이크론|Micron|D램|DRAM|낸드|NAND|디램|파운드리|메모리 반도체/;

export function buildTriagePrompt(body) {
  return `다음은 투자 블로그 글이다. 두 가지를 판정하라.

- semis: 메모리/반도체(HBM·DRAM·NAND·파운드리·반도체 장비/소재·관련 기업의 업황과 투자판단)가 글의 중심 주제인가.
  다른 주제 글에서 스치듯 언급만 되면 false.
- reasoning: 저자 본인의 논지·예측·판단이 단계적으로 전개되는 추론글인가.
  뉴스·리포트 전달 중심, 짧은 메모, 잡담이면 false.

${body.slice(0, 6000)}`;
}

function triagePath(corpusRoot, blogId) {
  return join(corpusRoot, "naver", blogId, "analysis", "triage.jsonl");
}

export async function loadTriageMap(corpusRoot, blogId) {
  const map = new Map();
  let text;
  try {
    text = await readFile(triagePath(corpusRoot, blogId), "utf8");
  } catch {
    return map;
  }
  for (const line of text.split("\n")) {
    if (!line) continue;
    try {
      const row = JSON.parse(line);
      map.set(row.id, row);
    } catch { /* 손상 줄은 건너뜀 */ }
  }
  return map;
}

export async function appendTriage(corpusRoot, blogId, row) {
  await mkdir(join(corpusRoot, "naver", blogId, "analysis"), { recursive: true });
  await writeFile(triagePath(corpusRoot, blogId), `${JSON.stringify(row)}\n`, { flag: "a" });
}

// 퍼널 ①: index.jsonl 순회 → 키워드 매칭 + triage 미처리 글만, 최신→과거.
export async function sweepTriageCandidates(corpusRoot, blogIds) {
  const candidates = [];
  for (const blogId of blogIds) {
    let text;
    try {
      text = await readFile(join(corpusRoot, "naver", blogId, "index.jsonl"), "utf8");
    } catch {
      continue;
    }
    const done = await loadTriageMap(corpusRoot, blogId);
    for (const line of text.split("\n")) {
      if (!line) continue;
      let row;
      try {
        row = JSON.parse(line);
      } catch {
        continue;
      }
      if (done.has(row.id)) continue;
      let markdown;
      try {
        markdown = await readFile(join(corpusRoot, "naver", blogId, "articles", `${row.id}.md`), "utf8");
      } catch {
        continue;
      }
      const body = extractBody(markdown);
      if (!SEMIS_RE.test(body) && !SEMIS_RE.test(row.title || "")) continue;
      candidates.push({ blogId, id: row.id, title: row.title, body, publishedAt: row.publishedAt || "" });
    }
  }
  candidates.sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : -1));
  return candidates;
}
