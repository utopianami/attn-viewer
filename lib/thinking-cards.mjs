// 사고 카드 — 블로그 글에서 추출한 사고 구조를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { extractBody, runCodexSummary } from "./summaries.mjs";

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

// 인용문을 문장 종결 부호+공백 경계로 분할하여 각 조각이 body에 순서대로 있는지 확인한다.
// 개조식 원문에 목록 번호("4.")·이미지 플레이스홀더("![...]")가 끼어도 문장 각각은 원문과 일치하므로 통과.
// 목록 마커 형태(숫자·기호만으로 구성된 조각)만 스킵하고, 그 외는 길이 무관하게 검사한다.
// 순서 검사: 이전 매칭 끝 위치 이후에서만 다음 조각을 찾아 문장 재배열 합성 인용을 잡는다.
const MARKER_RE = /^[\d.\s()\-]+$/;
function matchesInFragments(quote, haystack) {
  const fragments = normalize(quote).split(/(?<=[.!?…])\s+/).filter((f) => !MARKER_RE.test(f));
  if (fragments.length === 0) return false; // 검사할 조각 없음 → 실패
  let pos = 0;
  for (const f of fragments) {
    const idx = haystack.indexOf(f, pos);
    if (idx === -1) return false;
    pos = idx + f.length;
  }
  return true;
}

export function validateQuotes(card, body) {
  const haystack = normalize(body);
  const quoteFailures = [];
  const checkQuote = (holder, path) => {
    if (!holder || holder.quote == null) return;
    if (!matchesInFragments(holder.quote, haystack)) {
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

const CARD_SCHEMA_PATH = fileURLToPath(new URL("../schemas/thinking-card.schema.json", import.meta.url));
const MAX_EXTRACT_CHARS = 14000; // 추출은 요약보다 본문을 넓게 준다 — 인용 원문이 잘리면 검증이 깨진다

export function buildExtractPrompt(title, body) {
  return `다음은 투자 블로그의 추론글이다. 저자가 "어떻게 생각했는지"를 아래 구조로 추출하라.
이 글에 실제로 적힌 것만 담는다. 어떤 글에나 맞는 일반론(예: "밸류에이션을 확인했다")은 금지.

- situation: 이 글이 다루는 상황/질문 한 줄 (예: "메모리 사이클 방향 판단")
- checks[]: 저자가 확인한 것들, 글에 나타난 순서대로
  - what: 무엇을 확인했나 / why: 왜 그걸 봤나 (글에 근거 없으면 null)
  - kill: 저자가 "이러면 아니다/접는다/틀린 것"이라고 한 조건. 반드시 찾아보고, 정말 없으면 null.
  - quote: 근거 문장을 원문에서 그대로 복사 (변형·요약 금지). 못 찾으면 null.
- connection: 확인한 것들을 결론으로 연결한 논리 (logic + quote)
- reservations: 유보 지점·생각을 바꾸겠다고 한 조건 (text + quote)
- conclusionType: 방향 판단 | 종목 비교 | 시점 판단 | 리스크 점검 | 기타
- topics: 관련 키워드 (예: ["HBM", "감산"])

제목: ${title}

${body.slice(0, MAX_EXTRACT_CHARS)}`;
}

// 퍼널 ③: 추출 1건 — codex 실행 → 파싱 → 인용 코드검증 → 검수 플래그 → 저장.
export async function extractCard(corpusRoot, candidate, { summaryType = null, runCodex } = {}) {
  const run = runCodex
    // 420초 — 장문 글(14k자) 추출은 180초를 넘기는 사례가 실측됨 (2026-07-13 튜닝 배치)
    || ((prompt) => runCodexSummary(prompt, { schemaPath: CARD_SCHEMA_PATH, timeoutMs: 420_000 }));
  const raw = await run(buildExtractPrompt(candidate.title, candidate.body));
  const parsed = JSON.parse(raw);
  const { card, quoteFailures } = validateQuotes(parsed, candidate.body);
  card.quoteFailures = quoteFailures;
  card.needsReview = needsReview(card, summaryType);
  card.publishedAt = candidate.publishedAt || null;
  card.engine = "codex-cli";
  card.sourceContentHash = createHash("sha256").update(candidate.body).digest("hex");
  return saveCard(corpusRoot, candidate.blogId, candidate.id, card);
}
