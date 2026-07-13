# 사고 카드 추출 파이프라인 구현 계획 (계획 1/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 블로그 코퍼스에서 반도체 추론글을 3단 퍼널로 골라 codex CLI로 4층 사고 카드를 추출·저장하고, 블로거 탭에서 글 옆에 카드를 띄워 검수할 수 있게 한다.

**Architecture:** `lib/thinking-cards.mjs`가 퍼널 후보 선정·프롬프트·인용 코드검증·저장을 담당하고, `scripts/extract_thinking.mjs`가 배치 실행(재개 가능·jobs 로그), `lib/blogs-router.mjs`·`public/blogger.js`가 검수 UI를 담당한다. 스펙: `docs/superpowers/specs/2026-07-13-thinking-playbook-design.md`. 합성·holdout·주입은 계획 2(튜닝 후 작성).

**Tech Stack:** Node (ESM .mjs), codex CLI(`--output-schema`), node:test, Express 라우터, 기존 summaries.mjs 패턴 재사용.

## Global Constraints

- 추출 엔진 기본값 = **codex CLI** (API 키·비용 없음). API 전환은 튜닝 측정 후에만.
- **모든 인용(quote)은 원문 Markdown에 실제 존재해야 함** — 코드로 대조, 실패 시 해당 quote를 null로 바꾸고 `quoteFailures`에 기록.
- 사고 카드 저장: `storage/users/<user>/corpus/naver/<blogId>/analysis/<articleId>.json`
- triage 결과 저장: `.../naver/<blogId>/analysis/triage.jsonl` (append, 글당 1줄)
- 재개 가능: 이미 triage/카드가 있는 글은 스킵. 처리 순서는 최신→과거.
- 반도체 키워드(퍼널 ①): `HBM|하이닉스|마이크론|Micron|D램|DRAM|낸드|NAND|디램|파운드리|메모리 반도체` (2026-07-13 실측 508편)
- 커밋 메시지에 `$`가 들어가면 zsh 확장됨 — 작은따옴표 사용.

---

### Task 1: 사고 카드 저장/로드 + 인용 코드검증

**Files:**
- Create: `lib/thinking-cards.mjs`
- Create: `lib/thinking-cards.test.mjs`
- Create: `schemas/thinking-card.schema.json`

**Interfaces:**
- Produces: `saveCard(corpusRoot, blogId, articleId, card)`, `loadCard(corpusRoot, blogId, articleId) -> object|null`, `validateQuotes(card, body) -> {card, quoteFailures: string[]}`, `needsReview(card, summaryType) -> boolean`
- 카드 객체 형태(디스크와 동일): `{ id, situation, checks: [{order, what, why, kill, quote}], connection: {logic, quote}, reservations: {text, quote}, conclusionType, topics, publishedAt, extractedAt, engine, sourceContentHash, quoteFailures, needsReview }`

- [ ] **Step 1: 실패하는 테스트 작성**

```js
// lib/thinking-cards.test.mjs
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
```

- [ ] **Step 2: 실패 확인** — Run: `node --test lib/thinking-cards.test.mjs` / Expected: FAIL (`Cannot find module './thinking-cards.mjs'`)

- [ ] **Step 3: 최소 구현**

```js
// lib/thinking-cards.mjs
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
```

- [ ] **Step 4: 통과 확인** — Run: `node --test lib/thinking-cards.test.mjs` / Expected: PASS (3 tests)

- [ ] **Step 5: codex 출력 스키마 파일 작성** (`schemas/thinking-card.schema.json`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["situation", "checks", "connection", "reservations", "conclusionType", "topics"],
  "properties": {
    "situation": { "type": "string" },
    "checks": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["order", "what", "why", "kill", "quote"],
        "properties": {
          "order": { "type": "integer" },
          "what": { "type": "string" },
          "why": { "type": ["string", "null"] },
          "kill": { "type": ["string", "null"] },
          "quote": { "type": ["string", "null"] }
        }
      }
    },
    "connection": {
      "type": "object",
      "additionalProperties": false,
      "required": ["logic", "quote"],
      "properties": { "logic": { "type": ["string", "null"] }, "quote": { "type": ["string", "null"] } }
    },
    "reservations": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text", "quote"],
      "properties": { "text": { "type": ["string", "null"] }, "quote": { "type": ["string", "null"] } }
    },
    "conclusionType": { "type": "string" },
    "topics": { "type": "array", "items": { "type": "string" } }
  }
}
```

- [ ] **Step 6: 커밋**

```bash
git add lib/thinking-cards.mjs lib/thinking-cards.test.mjs schemas/thinking-card.schema.json
git commit -m 'feat(thinking): 사고 카드 저장/로드 + 인용 코드검증 + 출력 스키마'
```

---

### Task 2: 퍼널 ①② — 키워드 필터 · triage 후보 스윕 · triage 기록

**Files:**
- Modify: `lib/thinking-cards.mjs` (함수 추가)
- Modify: `lib/thinking-cards.test.mjs` (테스트 추가)
- Create: `schemas/thinking-triage.schema.json`

**Interfaces:**
- Consumes: Task 1의 저장 규칙.
- Produces: `SEMIS_RE` (RegExp), `buildTriagePrompt(body) -> string`, `sweepTriageCandidates(corpusRoot, blogIds) -> [{blogId, id, title, body, publishedAt}]` (최신→과거 정렬, 키워드 매칭·미처리 글만), `loadTriageMap(corpusRoot, blogId) -> Map<id, row>`, `appendTriage(corpusRoot, blogId, row)` — row는 `{id, semis, reasoning, at}`.

- [ ] **Step 1: 실패하는 테스트 작성** (lib/thinking-cards.test.mjs에 추가)

```js
import { mkdir, writeFile } from "node:fs/promises";
import {
  SEMIS_RE, buildTriagePrompt, sweepTriageCandidates, loadTriageMap, appendTriage,
} from "./thinking-cards.mjs";

const FM = `---\nid: "x"\n---\n# 제목\n\n`;

async function seedPost(corpusRoot, blogId, logNo, { body, publishedAt }) {
  const id = `naver-${blogId}-${logNo}`;
  const root = join(corpusRoot, "naver", blogId);
  await mkdir(join(root, "articles"), { recursive: true });
  await writeFile(join(root, "articles", `${id}.md`), FM + body, "utf8");
  return JSON.stringify({ id, title: `post ${logNo}`, publishedAt, markdownPath: `articles/${id}.md` });
}

test("sweepTriageCandidates: 키워드 매칭 + 미처리 글만, 최신순", async () => {
  const corpusRoot = await mkdtemp(join(tmpdir(), "cards-sweep-"));
  const rows = [
    await seedPost(corpusRoot, "b", 1, { body: "HBM 수요가 늘고 있다는 판단의 근거는 다음과 같다.", publishedAt: "2026-07-01T09:00:00+09:00" }),
    await seedPost(corpusRoot, "b", 2, { body: "오늘은 날씨 얘기만 하겠다.", publishedAt: "2026-07-02T09:00:00+09:00" }),
    await seedPost(corpusRoot, "b", 3, { body: "하이닉스 재고를 보면 사이클이 보인다.", publishedAt: "2026-07-03T09:00:00+09:00" }),
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
```

- [ ] **Step 2: 실패 확인** — Run: `node --test lib/thinking-cards.test.mjs` / Expected: FAIL (`SEMIS_RE is not exported` 계열)

- [ ] **Step 3: 최소 구현** (lib/thinking-cards.mjs에 추가)

```js
import { extractBody } from "./summaries.mjs";

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
```

- [ ] **Step 4: 통과 확인** — Run: `node --test lib/thinking-cards.test.mjs` / Expected: PASS (5 tests)

- [ ] **Step 5: triage 출력 스키마 작성** (`schemas/thinking-triage.schema.json`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["semis", "reasoning"],
  "properties": { "semis": { "type": "boolean" }, "reasoning": { "type": "boolean" } }
}
```

- [ ] **Step 6: 커밋**

```bash
git add lib/thinking-cards.mjs lib/thinking-cards.test.mjs schemas/thinking-triage.schema.json
git commit -m 'feat(thinking): 퍼널 ①② — 키워드 스윕 + triage 프롬프트/기록'
```

---

### Task 3: codex 러너 스키마 경로 옵션 + 추출 프롬프트/플로우

**Files:**
- Modify: `lib/summaries.mjs:128-138` (runCodexSummary에 schemaPath 옵션)
- Modify: `lib/thinking-cards.mjs`, `lib/thinking-cards.test.mjs`

**Interfaces:**
- Consumes: `runCodexSummary(prompt, {timeoutMs, schema, schemaPath})` — schemaPath 지정 시 그 스키마로 `--output-schema`.
- Produces: `buildExtractPrompt(title, body) -> string`, `extractCard(corpusRoot, candidate, {summaryType, runCodex}) -> record` — candidate는 Task 2의 후보 객체. runCodex 주입 가능(테스트용). 반환 record는 저장까지 끝난 카드.

- [ ] **Step 1: runCodexSummary 옵션 확장** (기존 동작 불변 — schema=true면 기존 경로 유지)

```js
// lib/summaries.mjs — 시그니처와 스키마 결정부만 변경
export function runCodexSummary(prompt, { timeoutMs = 120_000, schema = false, schemaPath = null } = {}) {
  // ...
  const args = ["-a", "never", "exec", "--ephemeral", "--sandbox", "read-only"];
  const resolvedSchema = schemaPath || (schema ? ANALYSIS_SCHEMA_PATH : null);
  if (resolvedSchema) {
    args.push("--output-schema", resolvedSchema);
  }
  // 이하 동일
```

- [ ] **Step 2: 기존 테스트 회귀 확인** — Run: `node --test lib/summaries.test.mjs` / Expected: PASS (전부)

- [ ] **Step 3: 실패하는 테스트 작성** (lib/thinking-cards.test.mjs에 추가)

```js
import { buildExtractPrompt, extractCard, loadCard as loadCard2 } from "./thinking-cards.mjs";

test("buildExtractPrompt: 4층 요구 + 인용 규칙 + 킬 조건 캐묻기", () => {
  const p = buildExtractPrompt("제목", "본문입니다");
  assert.match(p, /situation/);
  assert.match(p, /kill/);
  assert.match(p, /원문에서 그대로 복사/);
  assert.match(p, /일반론/);
  assert.match(p, /본문입니다/);
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
  assert.equal((await loadCard2(corpusRoot, "b", "naver-b-9")).situation, "메모리 사이클 판단");
});
```

- [ ] **Step 4: 실패 확인** — Run: `node --test lib/thinking-cards.test.mjs` / Expected: FAIL (`buildExtractPrompt is not exported`)

- [ ] **Step 5: 최소 구현** (lib/thinking-cards.mjs에 추가)

```js
import { createHash } from "node:crypto";
import { runCodexSummary } from "./summaries.mjs";

const CARD_SCHEMA_PATH = join(process.cwd(), "schemas", "thinking-card.schema.json");
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
    || ((prompt) => runCodexSummary(prompt, { schemaPath: CARD_SCHEMA_PATH, timeoutMs: 180_000 }));
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
```

- [ ] **Step 6: 통과 확인** — Run: `node --test lib/thinking-cards.test.mjs && node --test lib/summaries.test.mjs` / Expected: PASS (전부)

- [ ] **Step 7: 커밋**

```bash
git add lib/summaries.mjs lib/thinking-cards.mjs lib/thinking-cards.test.mjs
git commit -m 'feat(thinking): 퍼널 ③ — 4층 추출 프롬프트 + extractCard (codex 스키마 경로 옵션)'
```

---

### Task 4: 배치 CLI `scripts/extract_thinking.mjs`

**Files:**
- Create: `scripts/extract_thinking.mjs`

**Interfaces:**
- Consumes: Task 2·3의 `sweepTriageCandidates`, `appendTriage`, `loadTriageMap`, `loadCard`, `extractCard`, `runCodexSummary`, summaries의 `loadSummary`.
- Produces: CLI. `node scripts/extract_thinking.mjs --user ryze_yn --stage all|triage|extract [--blogId X] [--limit N] [--skip-after 2026-06-01]`. jobs 로그: `storage/users/<user>/corpus/analysis-jobs/<ISO ts>.json` (`{stage, triaged, passed, extracted, failed, reviewQueue: [ids], done}`).

- [ ] **Step 1: 구현** (스크립트는 얇게 — 로직은 전부 lib에 있으므로 배선만. 테스트는 lib 단위 테스트 + 실행 검증으로 갈음)

```js
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
```

- [ ] **Step 2: 문법·회귀 확인** — Run: `node --check scripts/extract_thinking.mjs && node --test lib/thinking-cards.test.mjs` / Expected: PASS

- [ ] **Step 3: 드라이런 (triage 2건만, 실제 codex 호출)** — Run: `node scripts/extract_thinking.mjs --user ryze_yn --stage triage --blogId crush212121 --limit 2`
Expected: `triage naver-crush212121-... semis=... reasoning=...` 2줄 + job 로그 경로. `storage/users/ryze_yn/corpus/naver/crush212121/analysis/triage.jsonl`에 2줄 확인. 실패 시 codex CLI 로그인 상태 확인 후 재시도.

- [ ] **Step 4: 커밋**

```bash
git add scripts/extract_thinking.mjs
git commit -m 'feat(thinking): 추출 배치 CLI — 재개 가능·jobs 로그·skip-after(holdout 보존)'
```

---

### Task 5: 검수 UI — 글 상세에 사고 카드 표시

**Files:**
- Modify: `lib/blogs-router.mjs:198-205` (글 상세에 card 동봉)
- Modify: `public/blogger.js:363` 부근 renderPost (카드 패널)

**Interfaces:**
- Consumes: Task 1 `loadCard`.
- Produces: `GET /api/blogs/:blogId/posts/:articleId` 응답에 `card: object|null` 필드. 프런트는 card가 있으면 본문 위에 패널 렌더.

- [ ] **Step 1: 라우터 수정**

```js
// lib/blogs-router.mjs 상단 import에 추가
import { loadCard } from "./thinking-cards.mjs";

// GET /:blogId/posts/:articleId 핸들러 교체
router.get("/:blogId/posts/:articleId", async (req, res) => {
  try {
    const post = await readPost(corpusRoot, req.params.blogId, req.params.articleId);
    const card = await loadCard(corpusRoot, req.params.blogId, req.params.articleId);
    res.json({ ok: true, ...post, card });
  } catch (error) {
    res.status(404).json({ ok: false, error: "글을 찾을 수 없습니다" });
  }
});
```

- [ ] **Step 2: 프런트 — renderPost에 카드 패널** (public/blogger.js, `renderPost` 안에서 `bodyHtml` 계산 직후)

```js
function renderCardPanel(card) {
  if (!card) return "";
  const esc = escapeHtml;
  const checks = (card.checks || []).map((c) => `
    <li>
      <strong>${esc(c.what || "")}</strong>${c.why ? ` — ${esc(c.why)}` : ""}
      ${c.kill ? `<div style="color:#c0392b">✕ 킬 조건: ${esc(c.kill)}</div>` : ""}
      ${c.quote ? `<blockquote>${esc(c.quote)}</blockquote>` : '<div style="color:#e67e22">인용 없음</div>'}
    </li>`).join("");
  const review = card.needsReview
    ? `<div style="background:#fdf2e9;padding:6px 10px;border-radius:6px">⚠ 검수 필요 — 인용 실패 ${(card.quoteFailures || []).length}건${card.quoteFailures?.length ? ` (${card.quoteFailures.join(", ")})` : ""}</div>`
    : "";
  return `<details open style="border:1px solid #ddd;border-radius:8px;padding:10px 14px;margin-bottom:16px">
    <summary><strong>사고 카드</strong> — ${esc(card.situation || "")} <span style="color:#888">[${esc(card.conclusionType || "")}]</span></summary>
    ${review}
    <ol>${checks}</ol>
    ${card.connection?.logic ? `<p><strong>연결:</strong> ${esc(card.connection.logic)}</p>` : ""}
    ${card.reservations?.text ? `<p><strong>유보:</strong> ${esc(card.reservations.text)}</p>` : ""}
  </details>`;
}
```

그리고 renderPost의 본문 삽입부에서 `bodyHtml` 앞에 `renderCardPanel(state.post.card)`를 붙인다.

- [ ] **Step 3: 문법 확인** — Run: `npm run check` / Expected: PASS

- [ ] **Step 4: 시드 카드로 화면 검증 (스크린샷 필수 — 메모리 규칙)**
  1. Task 4 드라이런에서 카드가 하나도 없으면: `node scripts/extract_thinking.mjs --user ryze_yn --stage extract --blogId crush212121 --limit 1`
  2. `test/e2e/*.test.mjs`에서 기존 로그인 헬퍼(세션 쿠키 획득 방식)를 확인해 동일 방식으로 playwright 스크립트를 스크래치패드에 작성 → 블로거 탭 → 해당 글 열기 → 스크린샷 저장.
  3. 스크린샷을 눈으로 확인: 사고 카드 패널이 본문 위에 보이고, 킬 조건·인용 블록·검수 배지가 렌더되는지. 확인 전에는 완료 보고 금지.

- [ ] **Step 5: 커밋**

```bash
git add lib/blogs-router.mjs public/blogger.js
git commit -m 'feat(thinking): 검수 UI — 글 상세에 사고 카드 패널'
```

---

### Task 6: 튜닝 배치 1 — 최신 20~30편 추출 + 검수 큐 보고

**Files:** 없음 (실행 작업)

- [ ] **Step 1: triage 전량 실행 (508편 후보, codex 순차 — 수 시간 소요 가능)**

```bash
node scripts/extract_thinking.mjs --user ryze_yn --stage triage 2>&1 | tee /tmp/claude-1007/-home-ryze-yn-attn-viewer/1f620c11-16cb-4660-867d-cc1dc4b2c262/scratchpad/triage-run1.log
```

Expected: `triaged` 합계가 후보 수와 일치, `failed`가 소수. **같은 사유의 실패가 반복되면 중단하고 버그로 취급** (메모리 규칙).

- [ ] **Step 2: 통과율 확인** — job 로그의 passed/triaged 비율 확인. 예상 30~50%. 10% 미만이거나 90% 초과면 프롬프트 기준이 어긋난 것 — 표본 10건을 직접 읽고 대조.

- [ ] **Step 3: 튜닝 추출 30편**

```bash
node scripts/extract_thinking.mjs --user ryze_yn --stage extract --limit 30
```

Expected: `extract ... quoteFailures=N review=bool` 30줄, job 로그에 reviewQueue.

- [ ] **Step 4: 검수 보고** — 아래를 정리해 사용자에게 보고하고 튜닝 판정을 받는다:
  - 인용 실패율 (전체 quote 중 실패 비율)
  - needsReview 건수와 사유 분포
  - 카드 3~5장 표본 (탭 링크와 함께)
  - **판정 기준**: "카드만 보고 어느 블로거·어떤 글인지 특정 가능한가" — 미달이면 buildExtractPrompt 수정 → `analysis/` 해당 카드 삭제 → 재추출. API 전환 논의는 이 측정 이후에만.

---

## 계획 2 예고 (이 계획 범위 밖)

튜닝 통과 후: 배치 전량 추출(`--skip-after`로 holdout 확보) → 플레이북 합성 → 게이트 단위 holdout 검증 → triage 매칭·PLAN/SYNTHESIZE 주입 + A/B. 튜닝 결과물(실제 카드)을 보고 별도 계획으로 작성한다.
