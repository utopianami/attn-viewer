// 사고 카드 — 블로그 글에서 추출한 사고 구조를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

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
  const record = { id: articleId, extractedAt: new Date().toISOString(), ...card };
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
