# 플레이북 합성 + holdout 검증 + chat 주입 구현 계획 (계획 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사고 카드(글 단위, 227장)를 상황별 플레이북으로 합성하고, holdout 게이트 단위 검증을 통과한 플레이북만 QA 엔진의 PLAN·SYNTHESIZE에 주입한다.

**Architecture:** 합성·검증은 Node(lib/ + codex CLI, 계획 1과 동일 패턴), 주입은 Python 엔진(engine/stages/). 플레이북은 `storage/users/<user>/corpus/playbooks/<slug>.json`. 매칭은 LLM 호출 없이 결정적(질문 유형 매핑 + 키워드 겹침)으로 한다.

**Tech Stack:** Node 20 (node:test), codex CLI(`runCodexSummary` + `--output-schema`), Python FastAPI 엔진(pytest).

**스펙:** `docs/superpowers/specs/2026-07-13-thinking-playbook-design.md` §합성·§선택+주입·§검증

## Global Constraints

- LLM 호출은 전부 codex CLI(`runCodexSummary`) — 비용 $0. API 전환은 측정 미달 시에만 (스펙 §모델 배치).
- 주입은 **관련 플레이북 1장만**, `status: "holdout_passed"`만, 매칭 없으면 주입 없음(현행 동작 그대로).
- 플레이북은 **절차로만 쓰고 사실로 쓰지 않는다** — 주입 프롬프트에 경계 문구 필수.
- 게이트는 카드당 최대 7개, `operationalization`(구체 숫자·조건) 없는 게이트는 채택 보류(드롭+로그).
- 블로거 1명만의 패턴은 근거 글 3편 이상일 때만 카드화.
- `needsReview: true`인 사고 카드는 합성 입력에서 제외.
- 커밋 메시지는 작은따옴표로 감싼다(`$0` 등 zsh 확장 사고 방지).
- 엔진 재시작은 `pm2 restart attn-engine`만. pkill 금지.
- 배포 후 같은 세션에서 `docs/workflow-review.html` 현행화 + 스크린샷 확인 (Task 8).
- 배치 스크립트는 반드시 프로젝트 루트에서 실행 (cwd 의존).

## 사용자 체크포인트 (자동 진행 금지)

- **CP-1 (Task 3 뒤):** 합성 프롬프트 + 첫 플레이북 1장을 사용자에게 보여주고 승인받은 뒤에만 Task 4 배치 확대. (사용자 지시: "합성 프롬프트는 같이 보기")
- **CP-2 (Task 5 뒤):** holdout 결과(통과/탈락 목록)를 보여주고 승인받은 뒤에만 Task 6 주입.
- **CP-3 (Task 7 뒤):** A/B 리포트 확인 후 유지/롤백 결정.

---

### Task 1: 플레이북 스키마 + 저장/검증 모듈

**Files:**
- Create: `schemas/playbook.schema.json`
- Create: `lib/playbooks.mjs`
- Test: `lib/playbooks.test.mjs`

**Interfaces:**
- Produces: `savePlaybook(corpusRoot, playbook)` → 저장된 record, `loadPlaybooks(corpusRoot)` → playbook[], `validatePlaybook(playbook, knownCardIds: Set)` → `{ playbook, dropped: string[] }`, `playbooksDir(corpusRoot)` → 경로 문자열
- 플레이북 정본 필드: `slug, situation, triggers[], topics[], conclusionType, gates[{order, check, why, kill, operationalization, evidence[]}], connection, reservations, asOf, sources{bloggers[], articleCount}, status("draft"|"holdout_passed"), synthesizedAt`

- [ ] **Step 1: 스키마 파일 작성** — codex `--output-schema`용. 코드가 채우는 필드(slug·status·sources·synthesizedAt·topics)는 스키마에 넣지 않는다.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "required": ["situation", "triggers", "conclusionType", "gates", "connection", "reservations", "asOf"],
  "properties": {
    "situation": { "type": "string" },
    "triggers": { "type": "array", "items": { "type": "string" } },
    "conclusionType": { "type": "string", "enum": ["방향 판단", "종목 비교", "시점 판단", "리스크 점검", "기타"] },
    "gates": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["order", "check", "why", "kill", "operationalization", "evidence"],
        "properties": {
          "order": { "type": "integer" },
          "check": { "type": "string" },
          "why": { "type": ["string", "null"] },
          "kill": { "type": ["string", "null"] },
          "operationalization": { "type": ["string", "null"] },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "connection": { "type": "string" },
    "reservations": { "type": ["string", "null"] },
    "asOf": { "type": "string" }
  }
}
```

- [ ] **Step 2: 실패하는 테스트 작성** (`lib/playbooks.test.mjs`)

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { savePlaybook, loadPlaybooks, validatePlaybook } from "./playbooks.mjs";

const basePlaybook = () => ({
  slug: "memory-cycle-direction",
  situation: "메모리 사이클 방향 판단",
  triggers: ["감산", "재고"],
  topics: ["DRAM"],
  conclusionType: "방향 판단",
  gates: [
    { order: 1, check: "재고 주수 확인", why: null, kill: "재고 20주 이상이면 회복 시나리오 기각",
      operationalization: "고객사 재고 주수 8주 미만", evidence: ["naver-ranto28-1"] },
  ],
  connection: "재고와 가격의 방향이 일치할 때만 결론",
  reservations: null,
  asOf: "2026-07",
  sources: { bloggers: ["ranto28"], articleCount: 3 },
  status: "draft",
});

test("savePlaybook/loadPlaybooks 왕복", async () => {
  const root = await mkdtemp(join(tmpdir(), "pb-"));
  await savePlaybook(root, basePlaybook());
  const list = await loadPlaybooks(root);
  assert.equal(list.length, 1);
  assert.equal(list[0].slug, "memory-cycle-direction");
  assert.ok(list[0].synthesizedAt);
});

test("validatePlaybook: 실존하지 않는 evidence 카드 id는 게이트 드롭", () => {
  const pb = basePlaybook();
  pb.gates.push({ order: 2, check: "x", why: null, kill: null,
    operationalization: "y", evidence: ["naver-ghost-999"] });
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 1);
  assert.deepEqual(dropped, ["gates[2]: evidence 미실존 naver-ghost-999"]);
});

test("validatePlaybook: operationalization 없는 게이트는 채택 보류(드롭)", () => {
  const pb = basePlaybook();
  pb.gates.push({ order: 2, check: "x", why: null, kill: null,
    operationalization: null, evidence: ["naver-ranto28-1"] });
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 1);
  assert.equal(dropped.length, 1);
});

test("validatePlaybook: 게이트 7개 초과는 8번째부터 드롭", () => {
  const pb = basePlaybook();
  pb.gates = Array.from({ length: 9 }, (_, i) => ({ order: i + 1, check: `c${i}`, why: null,
    kill: null, operationalization: "기준", evidence: ["naver-ranto28-1"] }));
  const { playbook } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook.gates.length, 7);
});

test("validatePlaybook: 단일 블로거 3편 미만이면 전체 거부", () => {
  const pb = basePlaybook();
  pb.sources = { bloggers: ["ranto28"], articleCount: 2 };
  const { playbook, dropped } = validatePlaybook(pb, new Set(["naver-ranto28-1"]));
  assert.equal(playbook, null);
  assert.ok(dropped[0].includes("단일 블로거"));
});
```

- [ ] **Step 3: 실패 확인** — Run: `node --test lib/playbooks.test.mjs` / Expected: FAIL (`Cannot find module './playbooks.mjs'`)

- [ ] **Step 4: 구현** (`lib/playbooks.mjs`)

```js
// 플레이북 — 사고 카드를 상황 단위로 합성한 게이트 절차를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

export function playbooksDir(corpusRoot) {
  return join(corpusRoot, "playbooks");
}

export async function savePlaybook(corpusRoot, playbook) {
  const dir = playbooksDir(corpusRoot);
  await mkdir(dir, { recursive: true });
  const record = { ...playbook, synthesizedAt: new Date().toISOString() };
  await writeFile(join(dir, `${playbook.slug}.json`), `${JSON.stringify(record, null, 2)}\n`, "utf8");
  return record;
}

export async function loadPlaybooks(corpusRoot) {
  let files;
  try {
    files = await readdir(playbooksDir(corpusRoot));
  } catch {
    return [];
  }
  const out = [];
  for (const f of files.filter((f) => f.endsWith(".json") && !["holdout.json", "clusters.json"].includes(f))) {
    try {
      out.push(JSON.parse(await readFile(join(playbooksDir(corpusRoot), f), "utf8")));
    } catch { /* 손상 파일은 건너뜀 — 스펙 §오류 처리 */ }
  }
  return out;
}

const MAX_GATES = 7;

// 게이트 단위 검증: evidence 실존·operationalization 존재·개수 상한. 위반 게이트는 드롭하고 사유를 남긴다.
// 단일 블로거 패턴은 근거 3편 미만이면 플레이북 자체를 거부한다 (스펙 §플레이북 카드).
export function validatePlaybook(playbook, knownCardIds) {
  const dropped = [];
  if ((playbook.sources?.bloggers || []).length === 1 && (playbook.sources?.articleCount || 0) < 3) {
    return { playbook: null, dropped: ["단일 블로거 3편 미만 — 플레이북 거부"] };
  }
  const gates = [];
  for (const g of playbook.gates || []) {
    const ghost = (g.evidence || []).find((id) => !knownCardIds.has(id));
    if (ghost) { dropped.push(`gates[${g.order}]: evidence 미실존 ${ghost}`); continue; }
    if (!g.operationalization) { dropped.push(`gates[${g.order}]: operationalization 없음 — 채택 보류`); continue; }
    if ((g.evidence || []).length === 0) { dropped.push(`gates[${g.order}]: evidence 없음`); continue; }
    gates.push(g);
  }
  if (gates.length > MAX_GATES) {
    for (const g of gates.slice(MAX_GATES)) dropped.push(`gates[${g.order}]: 상한 ${MAX_GATES}개 초과`);
  }
  return { playbook: { ...playbook, gates: gates.slice(0, MAX_GATES) }, dropped };
}
```

- [ ] **Step 5: 통과 확인 후 커밋** — Run: `node --test lib/playbooks.test.mjs` / Expected: PASS 5개
  `git add schemas/playbook.schema.json lib/playbooks.mjs lib/playbooks.test.mjs && git commit -m 'feat(playbook): 스키마+저장/검증 모듈 — 게이트 단위 검증, 단일 블로거 3편 규칙'`

---

### Task 2: 카드 로딩 + 클러스터 제안 + holdout 선정

**Files:**
- Create: `schemas/playbook-clusters.schema.json`
- Modify: `lib/playbooks.mjs` (함수 추가)
- Test: `lib/playbooks.test.mjs` (테스트 추가)

**Interfaces:**
- Consumes: `loadCard` 계열은 쓰지 않고 `analysis/*.json` 직접 순회 (extract 배치와 동일 저장 구조)
- Produces: `loadAllCards(corpusRoot)` → `[{blogId, ...card}]` (needsReview 제외), `buildClusterPrompt(cards)` → string, `proposeClusters(cards, {runCodex})` → `{clusters: [{slug, situation, cardIds[]}]}`, `pickHoldout(clusters, cards)` → `Map<slug, cardId[]>`

- [ ] **Step 1: 실패하는 테스트 작성**

```js
import { loadAllCards, buildClusterPrompt, pickHoldout } from "./playbooks.mjs";

test("loadAllCards: needsReview 카드는 합성 입력에서 제외", async () => {
  const root = await mkdtemp(join(tmpdir(), "cards-"));
  const dir = join(root, "naver", "b1", "analysis");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "a1.json"), JSON.stringify({ id: "a1", situation: "s", needsReview: false, topics: [] }));
  await writeFile(join(dir, "a2.json"), JSON.stringify({ id: "a2", situation: "s", needsReview: true, topics: [] }));
  await writeFile(join(dir, "triage.jsonl"), "");
  const cards = await loadAllCards(root);
  assert.deepEqual(cards.map((c) => c.id), ["a1"]);
  assert.equal(cards[0].blogId, "b1");
});

test("buildClusterPrompt: 카드당 한 줄 + 최소 3편 규칙 명시", () => {
  const p = buildClusterPrompt([
    { id: "a1", blogId: "b1", situation: "메모리 사이클 판단", conclusionType: "방향 판단", topics: ["DRAM"] },
  ]);
  assert.ok(p.includes("a1"));
  assert.ok(p.includes("3편"));
});

test("pickHoldout: 4편 이상 클러스터에서 최신 20%(최소 1장)를 뽑고, 3편 클러스터는 비움", () => {
  const mk = (id, at) => ({ id, publishedAt: at });
  const cards = [mk("a1", "2026-01"), mk("a2", "2026-02"), mk("a3", "2026-03"),
    mk("a4", "2026-04"), mk("b1", "2026-01"), mk("b2", "2026-02"), mk("b3", "2026-03")];
  const clusters = [
    { slug: "big", cardIds: ["a1", "a2", "a3", "a4"] },
    { slug: "small", cardIds: ["b1", "b2", "b3"] },
  ];
  const holdout = pickHoldout(clusters, cards);
  assert.deepEqual(holdout.get("big"), ["a4"]); // 최신 1장
  assert.deepEqual(holdout.get("small"), []);   // 3편은 남기면 3편 미만 — holdout 없음(draft 유지)
});
```

- [ ] **Step 2: 실패 확인** — Run: `node --test lib/playbooks.test.mjs` / Expected: FAIL (`loadAllCards is not a function`)

- [ ] **Step 3: 구현** (`lib/playbooks.mjs`에 추가)

```js
// 합성 입력 카드: 전 블로그 analysis/*.json 순회. needsReview는 품질 미달 후보라 제외.
export async function loadAllCards(corpusRoot) {
  const root = join(corpusRoot, "naver");
  const cards = [];
  let blogIds;
  try {
    blogIds = await readdir(root);
  } catch {
    return cards;
  }
  for (const blogId of blogIds) {
    let files;
    try {
      files = await readdir(join(root, blogId, "analysis"));
    } catch {
      continue;
    }
    for (const f of files.filter((f) => f.endsWith(".json"))) {
      try {
        const card = JSON.parse(await readFile(join(root, blogId, "analysis", f), "utf8"));
        if (card.needsReview) continue;
        cards.push({ blogId, ...card });
      } catch { /* 손상 카드는 무시 */ }
    }
  }
  return cards;
}

export function buildClusterPrompt(cards) {
  const lines = cards.map((c) =>
    `${c.id} | ${c.blogId} | ${c.conclusionType || "?"} | ${(c.topics || []).join(",")} | ${c.situation}`);
  return `다음은 투자 블로그 글에서 추출한 사고 카드 목록이다 (한 줄 = 카드ID | 블로거 | 결론유형 | 주제 | 상황).
"같은 상황에서 같은 종류의 판단"을 하는 카드끼리 묶어 플레이북 후보 클러스터를 제안하라.

규칙:
- 블로거 경계 없이 묶는다. 여러 블로거가 섞인 클러스터가 더 좋다(교차 검증).
- 한 클러스터는 최소 3편. 3편이 안 되면 클러스터로 만들지 마라.
- 상황이 실제로 같아야 한다. "반도체 관련"처럼 넓은 묶음 금지 — 예: "메모리 사이클 국면 판단"과 "장비주 신규 진입 시점 판단"은 다른 클러스터다.
- slug는 영문 kebab-case로.
- 어떤 클러스터에도 안 들어가는 카드는 버려도 된다.

${lines.join("\n")}`;
}

// holdout: 클러스터별 최신 20%(최소 1장). 남는 카드가 3편 미만이 되면 holdout을 뽑지 않는다
// (3편 미만 합성은 규칙 위반 → 그 클러스터는 draft로만 남고 주입 불가 — 안전 기본값).
export function pickHoldout(clusters, cards) {
  const byId = new Map(cards.map((c) => [c.id, c]));
  const holdout = new Map();
  for (const cl of clusters) {
    const sorted = [...cl.cardIds]
      .filter((id) => byId.has(id))
      .sort((a, b) => ((byId.get(a).publishedAt || "") < (byId.get(b).publishedAt || "") ? 1 : -1));
    const n = Math.max(1, Math.floor(sorted.length * 0.2));
    holdout.set(cl.slug, sorted.length - n >= 3 ? sorted.slice(0, n) : []);
  }
  return holdout;
}

export async function proposeClusters(cards, { runCodex }) {
  const raw = await runCodex(buildClusterPrompt(cards));
  return JSON.parse(raw);
}
```

- [ ] **Step 4: 클러스터 스키마 작성** (`schemas/playbook-clusters.schema.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "required": ["clusters"],
  "properties": {
    "clusters": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["slug", "situation", "cardIds"],
        "properties": {
          "slug": { "type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$" },
          "situation": { "type": "string" },
          "cardIds": { "type": "array", "items": { "type": "string" }, "minItems": 3 }
        }
      }
    }
  }
}
```

- [ ] **Step 5: 통과 확인 후 커밋** — Run: `node --test lib/playbooks.test.mjs` / Expected: PASS 8개
  `git add lib/playbooks.mjs lib/playbooks.test.mjs schemas/playbook-clusters.schema.json && git commit -m 'feat(playbook): 카드 로딩·클러스터 제안·holdout 선정'`

---

### Task 3: 플레이북 합성 (프롬프트 + 1건 파이프)

**Files:**
- Modify: `lib/playbooks.mjs` (함수 추가)
- Test: `lib/playbooks.test.mjs` (테스트 추가)

**Interfaces:**
- Consumes: Task 1 `validatePlaybook/savePlaybook`, Task 2 카드 형태
- Produces: `buildPlaybookPrompt(cluster, cards)` → string, `synthesizePlaybook(corpusRoot, cluster, cards, {runCodex})` → 저장된 draft record (거부 시 null). `PLAYBOOK_SCHEMA_PATH` export (배치 스크립트가 codex 기본 러너 구성에 사용)

- [ ] **Step 1: 실패하는 테스트 작성**

```js
import { buildPlaybookPrompt, synthesizePlaybook } from "./playbooks.mjs";

const clusterCards = [
  { id: "a1", blogId: "b1", publishedAt: "2026-01", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
    topics: ["DRAM"], checks: [{ order: 1, what: "재고 주수", why: "선행지표", kill: "20주 이상이면 기각", quote: "원문" }],
    connection: { logic: "재고→가격", quote: "원문" }, reservations: { text: "환율 변수는 유보", quote: null } },
  { id: "a2", blogId: "b2", publishedAt: "2026-02", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
    topics: ["DRAM"], checks: [{ order: 1, what: "가격 방향", why: null, kill: null, quote: "원문" }],
    connection: { logic: "가격→실적", quote: "원문" }, reservations: { text: null, quote: null } },
  { id: "a3", blogId: "b1", publishedAt: "2026-03", situation: "메모리 사이클 판단", conclusionType: "방향 판단",
    topics: ["DRAM"], checks: [{ order: 1, what: "CAPEX", why: null, kill: null, quote: "원문" }],
    connection: { logic: "CAPEX→공급", quote: "원문" }, reservations: { text: null, quote: null } },
];

test("buildPlaybookPrompt: 카드 checks·kill 포함, 평균화 금지 명시", () => {
  const p = buildPlaybookPrompt({ slug: "s", situation: "메모리 사이클 판단", cardIds: ["a1", "a2", "a3"] }, clusterCards);
  assert.ok(p.includes("재고 주수"));
  assert.ok(p.includes("20주 이상이면 기각"));
  assert.ok(p.includes("evidence"));
});

test("synthesizePlaybook: codex 응답 → 검증 → draft 저장, sources는 코드가 계산", async () => {
  const root = await mkdtemp(join(tmpdir(), "pb-syn-"));
  const fake = JSON.stringify({
    situation: "메모리 사이클 방향 판단", triggers: ["감산"], conclusionType: "방향 판단",
    gates: [{ order: 1, check: "재고 주수", why: null, kill: "20주 이상 기각",
      operationalization: "재고 8주 미만", evidence: ["a1"] }],
    connection: "재고와 가격 방향 일치 시 결론", reservations: null, asOf: "2026-07",
  });
  const rec = await synthesizePlaybook(root,
    { slug: "memory-cycle", situation: "메모리 사이클 판단", cardIds: ["a1", "a2", "a3"] },
    clusterCards, { runCodex: async () => fake });
  assert.equal(rec.status, "draft");
  assert.deepEqual(rec.sources, { bloggers: ["b1", "b2"], articleCount: 3 });
  assert.deepEqual(rec.topics, ["DRAM"]);
  const list = await loadPlaybooks(root);
  assert.equal(list[0].slug, "memory-cycle");
});
```

- [ ] **Step 2: 실패 확인** — Run: `node --test lib/playbooks.test.mjs` / Expected: FAIL

- [ ] **Step 3: 구현** (`lib/playbooks.mjs`에 추가)

```js
import { fileURLToPath } from "node:url";
export const PLAYBOOK_SCHEMA_PATH = fileURLToPath(new URL("../schemas/playbook.schema.json", import.meta.url));
export const CLUSTERS_SCHEMA_PATH = fileURLToPath(new URL("../schemas/playbook-clusters.schema.json", import.meta.url));

function cardBrief(c) {
  const checks = (c.checks || []).map((k) =>
    `  - [${k.order}] ${k.what}${k.why ? ` (왜: ${k.why})` : ""}${k.kill ? ` (킬: ${k.kill})` : ""}`).join("\n");
  return `### 카드 ${c.id} (${c.blogId}, ${c.publishedAt || "?"})
상황: ${c.situation}
확인 순서:
${checks}
연결: ${c.connection?.logic || "-"}
유보: ${c.reservations?.text || "-"}`;
}

export function buildPlaybookPrompt(cluster, cards) {
  const byId = new Map(cards.map((c) => [c.id, c]));
  const members = cluster.cardIds.map((id) => byId.get(id)).filter(Boolean);
  return `다음은 같은 상황("${cluster.situation}")에 대한 사고 카드들이다.
이들을 하나의 플레이북(순서 있는 확인 절차)으로 합성하라.

규칙:
- 게이트는 순서가 중요하다. 저자들이 실제로 확인한 순서를 보존하라.
- kill: 저자가 "이러면 아니다/접는다"라고 한 조건. 카드에 있는 것만, 뭉개지 말고 그대로.
- operationalization: 구체 숫자·조건(예: "재고 8주 미만"). 카드에 구체 기준이 없으면 null —
  지어내지 마라. null인 게이트는 채택 보류된다.
- evidence: 그 게이트의 근거가 된 카드 id 배열. 반드시 실존 카드 id만.
- 여러 카드가 같은 확인을 하면 게이트 하나로 합치고 evidence를 모은다 — 이런 게이트가 가장 신뢰도 높다.
- 카드들에 없는 확인 절차를 만들어내지 마라. 어떤 글에나 맞는 일반론(예: "밸류에이션 확인") 금지.
- 시기별로 사고가 다르면 최신 시기 기준으로 게이트를 만들고, 이전 사고와의 차이는 reservations에 남겨라.
- asOf: 이 사고가 유효한 시기 (멤버 카드 게시일 범위 기준, 예: "2026-07").
- triggers: 이 플레이북을 꺼내야 할 신호 (질문·뉴스에 나올 표현들).

${members.map(cardBrief).join("\n\n")}`;
}

export async function synthesizePlaybook(corpusRoot, cluster, cards, { runCodex }) {
  const byId = new Map(cards.map((c) => [c.id, c]));
  const members = cluster.cardIds.map((id) => byId.get(id)).filter(Boolean);
  const raw = await runCodex(buildPlaybookPrompt(cluster, cards));
  const parsed = JSON.parse(raw);
  const draft = {
    ...parsed,
    slug: cluster.slug,
    topics: [...new Set(members.flatMap((c) => c.topics || []))],
    sources: {
      bloggers: [...new Set(members.map((c) => c.blogId))].sort(),
      articleCount: members.length,
    },
    status: "draft",
  };
  const { playbook, dropped } = validatePlaybook(draft, new Set(cluster.cardIds));
  if (!playbook || playbook.gates.length === 0) {
    console.warn(`[synthesize] ${cluster.slug} 거부: ${dropped.join(" / ")}`);
    return null;
  }
  if (dropped.length) console.warn(`[synthesize] ${cluster.slug} 게이트 드롭: ${dropped.join(" / ")}`);
  return savePlaybook(corpusRoot, playbook);
}
```

- [ ] **Step 4: 통과 확인 후 커밋** — Run: `node --test lib/playbooks.test.mjs` / Expected: PASS 10개
  `git add lib/playbooks.mjs lib/playbooks.test.mjs && git commit -m 'feat(playbook): 합성 프롬프트+1건 파이프 — 게이트 순서·킬 보존, 일반론 금지'`

- [ ] **Step 5: 🛑 CP-1 — 실카드 1클러스터로 시험 합성, 프롬프트+결과를 사용자에게 보여주고 승인 대기**
  (Task 4의 스크립트를 `--limit 1`로 먼저 쓰거나, node REPL로 1건 실행. 승인 전 배치 확대 금지.)

---

### Task 4: 배치 스크립트 (클러스터 → 합성 전량)

**Files:**
- Create: `scripts/synthesize_playbooks.mjs`

**Interfaces:**
- Consumes: Task 1~3의 전 함수, `runCodexSummary(prompt, {schemaPath, timeoutMs})` (lib/summaries.mjs)
- Produces: CLI `node scripts/synthesize_playbooks.mjs --user ryze_yn --stage cluster|synthesize|all [--limit N]`. 산출물: `corpus/playbooks/clusters.json`(클러스터+holdout 목록), `corpus/playbooks/<slug>.json`, jobs 로그 `corpus/analysis-jobs/<ts>-playbooks.json`

- [ ] **Step 1: 스크립트 작성**

```js
// 플레이북 합성 배치 — 반드시 프로젝트 루트에서 실행.
// cluster: 카드 전체 → 클러스터 제안 + holdout 선정 → clusters.json 저장 (이미 있으면 스킵)
// synthesize: clusters.json의 각 클러스터에서 holdout 카드를 뺀 멤버로 합성 (기존 slug 스킵 → 재개 가능)
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { runCodexSummary } from "../lib/summaries.mjs";
import {
  CLUSTERS_SCHEMA_PATH, PLAYBOOK_SCHEMA_PATH,
  loadAllCards, loadPlaybooks, pickHoldout, proposeClusters, synthesizePlaybook,
} from "../lib/playbooks.mjs";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? dflt : args[i + 1];
};
const user = opt("user", null);
const stage = opt("stage", "all");
const limit = Number(opt("limit", Infinity));
if (!user) { console.error("--user 필수"); process.exit(1); }

const corpusRoot = join("storage", "users", user, "corpus");
const clustersPath = join(corpusRoot, "playbooks", "clusters.json");
const jobLog = { startedAt: new Date().toISOString(), stage, clusters: 0, synthesized: 0, rejected: [], errors: [] };

const cards = await loadAllCards(corpusRoot);
console.log(`합성 입력 카드 ${cards.length}장 (needsReview 제외)`);

let clustersDoc = null;
try { clustersDoc = JSON.parse(await readFile(clustersPath, "utf8")); } catch { /* 없음 */ }

if ((stage === "cluster" || stage === "all") && !clustersDoc) {
  const { clusters } = await proposeClusters(cards, {
    runCodex: (p) => runCodexSummary(p, { schemaPath: CLUSTERS_SCHEMA_PATH, timeoutMs: 420_000 }),
  });
  const holdout = pickHoldout(clusters, cards);
  clustersDoc = { clusters, holdout: Object.fromEntries(holdout), createdAt: new Date().toISOString() };
  await mkdir(join(corpusRoot, "playbooks"), { recursive: true });
  await writeFile(clustersPath, `${JSON.stringify(clustersDoc, null, 2)}\n`, "utf8");
  console.log(`클러스터 ${clusters.length}개 제안, holdout ${[...holdout.values()].flat().length}장`);
}
jobLog.clusters = clustersDoc?.clusters?.length || 0;

if (stage === "synthesize" || stage === "all") {
  const existing = new Set((await loadPlaybooks(corpusRoot)).map((p) => p.slug));
  let done = 0;
  for (const cluster of clustersDoc.clusters) {
    if (done >= limit) break;
    if (existing.has(cluster.slug)) continue;
    const holdoutIds = new Set(clustersDoc.holdout[cluster.slug] || []);
    const trainIds = cluster.cardIds.filter((id) => !holdoutIds.has(id));
    try {
      const rec = await synthesizePlaybook(corpusRoot, { ...cluster, cardIds: trainIds }, cards, {
        runCodex: (p) => runCodexSummary(p, { schemaPath: PLAYBOOK_SCHEMA_PATH, timeoutMs: 420_000 }),
      });
      if (rec) { jobLog.synthesized++; console.log(`synthesize ${cluster.slug} gates=${rec.gates.length}`); }
      else jobLog.rejected.push(cluster.slug);
    } catch (err) {
      jobLog.errors.push({ slug: cluster.slug, error: String(err).slice(0, 300) });
      console.warn(`synthesize ${cluster.slug} 실패: ${err}`);
    }
    done++;
  }
}

jobLog.finishedAt = new Date().toISOString();
const jobsDir = join(corpusRoot, "analysis-jobs");
await mkdir(jobsDir, { recursive: true });
const ts = jobLog.startedAt.replace(/[:.]/g, "-");
await writeFile(join(jobsDir, `${ts}-playbooks.json`), `${JSON.stringify(jobLog, null, 2)}\n`, "utf8");
console.log(`job 로그: ${join(jobsDir, `${ts}-playbooks.json`)}`);
```

- [ ] **Step 2: 동작 확인 (CP-1 승인 후)** — Run: `cd /home/ryze_yn/attn-viewer && node scripts/synthesize_playbooks.mjs --user ryze_yn --stage all`
  Expected: `클러스터 N개 제안` 후 slug별 `synthesize <slug> gates=K` 로그, `corpus/playbooks/*.json` 생성. 재실행 시 기존 slug 전부 스킵(재개 확인).

- [ ] **Step 3: 커밋** — `git add scripts/synthesize_playbooks.mjs && git commit -m 'feat(playbook): 합성 배치 CLI — 재개 가능, holdout 제외 합성, jobs 로그'`

---

### Task 5: holdout 검증 (게이트 단위 채점, 대조군 포함)

**Files:**
- Create: `schemas/playbook-prediction.schema.json`, `schemas/playbook-verdict.schema.json`
- Create: `scripts/validate_playbooks.mjs`
- Modify: `lib/playbooks.mjs` (프롬프트 빌더 추가)
- Test: `lib/playbooks.test.mjs` (테스트 추가)

**Interfaces:**
- Consumes: `clusters.json`의 holdout 목록, 저장된 draft 플레이북
- Produces: `buildPredictionPrompt(situation, playbook|null)`, `buildJudgePrompt(actualCard, prediction)`, `scorePlaybook(verdicts)` → `{coverage, killRecall}`. CLI가 통과 플레이북의 `status`를 `holdout_passed`로 갱신하고 `playbooks/holdout-report.json` 기록

- [ ] **Step 1: 실패하는 테스트 작성** (판정 로직은 코드로 — LLM 심판은 커버 여부만 답한다)

```js
import { buildPredictionPrompt, buildJudgePrompt, scorePlaybook } from "./playbooks.mjs";

test("buildPredictionPrompt: 플레이북 있으면 절차 포함+사실 사용 금지, 없으면(대조군) 미포함", () => {
  const pb = basePlaybook();
  const withPb = buildPredictionPrompt("메모리 사이클 판단", pb);
  assert.ok(withPb.includes("재고 주수 확인"));
  assert.ok(withPb.includes("사실"));               // 절차로만 쓰라는 경계 문구
  const control = buildPredictionPrompt("메모리 사이클 판단", null);
  assert.ok(!control.includes("재고 주수 확인"));
});

test("scorePlaybook: 실제 check 커버율과 킬 조건 재현율 집계", () => {
  const verdicts = [ // 심판 출력: holdout 카드의 check 하나당 한 항목
    { covered: true, killCovered: true, hasKill: true },
    { covered: true, killCovered: false, hasKill: true },
    { covered: false, killCovered: false, hasKill: false },
  ];
  const s = scorePlaybook(verdicts);
  assert.equal(s.coverage.toFixed(2), "0.67");   // 2/3
  assert.equal(s.killRecall.toFixed(2), "0.50"); // 킬 있는 check 2개 중 1개
});
```

- [ ] **Step 2: 실패 확인** — Run: `node --test lib/playbooks.test.mjs` / Expected: FAIL

- [ ] **Step 3: 프롬프트 빌더+집계 구현** (`lib/playbooks.mjs`에 추가)

```js
export function buildPredictionPrompt(situation, playbook) {
  const procedure = playbook ? `
아래 참고 절차가 있다. 절차(확인 순서·킬 조건)로만 참고하고,
절차 안의 내용을 사실·근거로 인용하지 마라.
${playbook.gates.map((g) => `${g.order}. ${g.check}${g.kill ? ` (킬: ${g.kill})` : ""} — 기준: ${g.operationalization}`).join("\n")}
연결: ${playbook.connection}` : "";
  return `너는 반도체 투자 리서치 계획을 세운다. 다음 상황에서 결론을 내기 전에
무엇을 어떤 순서로 확인할지, 각 확인마다 "이러면 시나리오 기각"인 킬 조건이 있으면 함께 적어라.
상황만 보고 확인 계획을 세워라. 답(결론)을 내지 마라.
${procedure}

상황: ${situation}`;
}

export function buildJudgePrompt(actualCard, prediction) {
  const checks = (actualCard.checks || []).map((c) =>
    `${c.order}. ${c.what}${c.kill ? ` (킬: ${c.kill})` : ""}`).join("\n");
  return `실제 전문가가 이 상황에서 확인한 목록(정답)과, 모델이 예측한 확인 계획이 있다.
정답의 각 항목에 대해 예측이 그 확인을 담았는지(covered), 정답에 킬 조건이 있는 항목이라면
예측도 같은 취지의 킬 조건을 담았는지(killCovered) 판정하라.
표현이 달라도 같은 지표·같은 확인이면 covered=true. 너그럽게 봐주지 마라 — 뭉뚱그린 일반론("업황 확인")은 불인정.

[정답 — 실제 확인 목록]
${checks}

[예측]
${prediction}`;
}

export function scorePlaybook(verdicts) {
  const covered = verdicts.filter((v) => v.covered).length;
  const withKill = verdicts.filter((v) => v.hasKill);
  const killCovered = withKill.filter((v) => v.killCovered).length;
  return {
    coverage: verdicts.length ? covered / verdicts.length : 0,
    killRecall: withKill.length ? killCovered / withKill.length : 1,
  };
}
```

- [ ] **Step 4: 스키마 2개 작성**

`schemas/playbook-prediction.schema.json`:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object", "additionalProperties": false, "required": ["plan"],
  "properties": {
    "plan": { "type": "array", "items": { "type": "object", "additionalProperties": false,
      "required": ["order", "check", "kill"],
      "properties": { "order": { "type": "integer" }, "check": { "type": "string" },
        "kill": { "type": ["string", "null"] } } } }
  }
}
```

`schemas/playbook-verdict.schema.json`:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object", "additionalProperties": false, "required": ["items"],
  "properties": {
    "items": { "type": "array", "items": { "type": "object", "additionalProperties": false,
      "required": ["order", "covered", "hasKill", "killCovered"],
      "properties": { "order": { "type": "integer" }, "covered": { "type": "boolean" },
        "hasKill": { "type": "boolean" }, "killCovered": { "type": "boolean" } } } }
  }
}
```

- [ ] **Step 5: 검증 CLI 작성** (`scripts/validate_playbooks.mjs`)

```js
// holdout 검증 — 플레이북별로: holdout 카드 상황 → (플레이북 예측 vs 대조군 예측) → 게이트 단위 심판.
// 통과 기준: coverage(with) > coverage(control) AND killRecall(with) >= killRecall(control).
// 통과 시 status=holdout_passed로 갱신. 반드시 프로젝트 루트에서 실행.
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { runCodexSummary } from "../lib/summaries.mjs";
import {
  buildJudgePrompt, buildPredictionPrompt, loadAllCardsWithReview, loadPlaybooks,
  playbooksDir, scorePlaybook,
} from "../lib/playbooks.mjs";

const PRED_SCHEMA = fileURLToPath(new URL("../schemas/playbook-prediction.schema.json", import.meta.url));
const VERDICT_SCHEMA = fileURLToPath(new URL("../schemas/playbook-verdict.schema.json", import.meta.url));

const args = process.argv.slice(2);
const user = args[args.indexOf("--user") + 1];
if (!user || user.startsWith("--")) { console.error("--user 필수"); process.exit(1); }
const corpusRoot = join("storage", "users", user, "corpus");

const clustersDoc = JSON.parse(await readFile(join(playbooksDir(corpusRoot), "clusters.json"), "utf8"));
const cards = await loadAllCardsWithReview(corpusRoot); // holdout 카드는 needsReview여도 정답으로 쓸 수 있어야 함
const byId = new Map(cards.map((c) => [c.id, c]));
const playbooks = await loadPlaybooks(corpusRoot);
const report = [];

for (const pb of playbooks) {
  const holdoutIds = (clustersDoc.holdout[pb.slug] || []).filter((id) => byId.has(id));
  if (holdoutIds.length === 0) { report.push({ slug: pb.slug, result: "no-holdout(draft 유지)" }); continue; }
  const agg = { with: [], control: [] };
  for (const id of holdoutIds) {
    const card = byId.get(id);
    for (const [key, playbook] of [["with", pb], ["control", null]]) {
      const predRaw = await runCodexSummary(buildPredictionPrompt(card.situation, playbook),
        { schemaPath: PRED_SCHEMA, timeoutMs: 420_000 });
      const pred = JSON.parse(predRaw).plan
        .map((p) => `${p.order}. ${p.check}${p.kill ? ` (킬: ${p.kill})` : ""}`).join("\n");
      const verdictRaw = await runCodexSummary(buildJudgePrompt(card, pred),
        { schemaPath: VERDICT_SCHEMA, timeoutMs: 420_000 });
      agg[key].push(...JSON.parse(verdictRaw).items);
    }
  }
  const sWith = scorePlaybook(agg.with);
  const sControl = scorePlaybook(agg.control);
  const passed = sWith.coverage > sControl.coverage && sWith.killRecall >= sControl.killRecall;
  report.push({ slug: pb.slug, holdout: holdoutIds.length, with: sWith, control: sControl, passed });
  if (passed) {
    const path = join(playbooksDir(corpusRoot), `${pb.slug}.json`);
    const cur = JSON.parse(await readFile(path, "utf8"));
    cur.status = "holdout_passed";
    cur.holdoutScores = { with: sWith, control: sControl, judgedAt: new Date().toISOString() };
    await writeFile(path, `${JSON.stringify(cur, null, 2)}\n`, "utf8");
  }
  console.log(`${pb.slug}: with=${JSON.stringify(sWith)} control=${JSON.stringify(sControl)} → ${passed ? "PASS" : "FAIL"}`);
}

await writeFile(join(playbooksDir(corpusRoot), "holdout-report.json"),
  `${JSON.stringify({ judgedAt: new Date().toISOString(), report }, null, 2)}\n`, "utf8");
console.log("리포트:", join(playbooksDir(corpusRoot), "holdout-report.json"));
```

`loadAllCardsWithReview`는 `loadAllCards`와 동일하되 needsReview 필터만 없는 함수 — `loadAllCards` 내부를 `_loadCards(corpusRoot, {includeReview})`로 추출해 둘 다 노출한다.

- [ ] **Step 6: 테스트 통과 확인 후 커밋** — Run: `node --test lib/playbooks.test.mjs` / Expected: PASS 12개
  `git add lib/playbooks.mjs lib/playbooks.test.mjs schemas/playbook-prediction.schema.json schemas/playbook-verdict.schema.json scripts/validate_playbooks.mjs && git commit -m 'feat(playbook): holdout 게이트 단위 검증 — 대조군 비교, 통과 시 holdout_passed'`

- [ ] **Step 7: 실행** — Run: `cd /home/ryze_yn/attn-viewer && node scripts/validate_playbooks.mjs --user ryze_yn`
  Expected: 플레이북별 PASS/FAIL 로그 + holdout-report.json

- [ ] **Step 8: 🛑 CP-2 — holdout 결과를 사용자에게 보고, 승인 후 Task 6 진행**

---

### Task 6: 엔진 주입 — user_id 배관 + 결정적 매칭 + PLAN·SYNTHESIZE 주입

**Files:**
- Create: `engine/stages/playbook.py`
- Modify: `engine/contracts/api.py:24-36` (AnswerRequest에 `user_id` 추가)
- Modify: `engine/orchestrator.py:137` (run_qa 시그니처 + 매칭 + 레이어 방출)
- Modify: `engine/stages/plan.py:158-171` (run_plan에 playbook 파라미터 + ctx 주입)
- Modify: `engine/stages/synthesize.py:38-159` (run_synthesize에 playbook 파라미터 + 섹션 추가)
- Modify: `engine/app/main.py:161-206` (req.user_id 전달)
- Modify: `server.mjs:1800-1810` (payload에 user_id)
- Test: `engine/tests/test_playbook_match.py`

**Interfaces:**
- Consumes: `storage/users/<user>/corpus/playbooks/*.json` (Task 1 정본 필드)
- Produces: `load_playbooks(user_id) -> list[dict]`, `match_playbook(question, question_type, playbooks) -> dict | None`, `format_gates(playbook) -> str`, `format_connection(playbook) -> str`. run_qa는 `{"type": "layer", "stage": "playbook", "matched": slug|None}` 레이어를 방출

- [ ] **Step 1: 실패하는 테스트 작성** (`engine/tests/test_playbook_match.py`)

```python
from stages.playbook import match_playbook, format_gates

PB = {
    "slug": "memory-cycle-direction", "situation": "메모리 사이클 방향 판단",
    "triggers": ["감산", "재고"], "topics": ["DRAM", "HBM"], "conclusionType": "방향 판단",
    "gates": [{"order": 1, "check": "재고 주수 확인", "why": None,
               "kill": "재고 20주 이상이면 기각", "operationalization": "8주 미만", "evidence": ["a1"]}],
    "connection": "재고·가격 방향 일치 시 결론", "reservations": None,
    "status": "holdout_passed",
}

def test_match_topic_hit_and_type_map():
    got = match_playbook("DRAM 감산이 사이클에 미치는 영향은?", "industry_analysis", [PB])
    assert got["slug"] == "memory-cycle-direction"

def test_no_match_on_fact_lookup():
    assert match_playbook("DRAM 감산 발표일이 언제야?", "fact_lookup", [PB]) is None

def test_no_match_without_keyword():
    assert match_playbook("현대차 실적 어때?", "stock_judgment", [PB]) is None

def test_draft_never_matches():
    draft = {**PB, "status": "draft"}
    assert match_playbook("DRAM 감산 영향?", "industry_analysis", [draft]) is None

def test_top1_by_keyword_score():
    other = {**PB, "slug": "other", "triggers": [], "topics": ["DRAM"]}
    got = match_playbook("DRAM 감산과 재고를 보면?", "industry_analysis", [other, PB])
    assert got["slug"] == "memory-cycle-direction"  # 히트 3(감산·재고·DRAM) > 1(DRAM)

def test_format_gates_marks_procedure_only():
    text = format_gates(PB)
    assert "재고 주수 확인" in text
    assert "킬" in text
    assert "사실" in text  # 절차로만 쓰라는 경계 문구
```

- [ ] **Step 2: 실패 확인** — Run: `cd engine && .venv/bin/python -m pytest tests/test_playbook_match.py -v`
  Expected: FAIL (`ModuleNotFoundError: stages.playbook`)

- [ ] **Step 3: 구현** (`engine/stages/playbook.py`)

```python
"""플레이북 선택+주입 — 결정적 매칭(LLM 없음), holdout_passed만, 1장만.
스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md §선택+주입
"""
import json
import os
from pathlib import Path

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT",
                    Path(__file__).resolve().parents[2] / "storage"))

# 질문 유형 → 허용 conclusionType. fact_lookup·unknown·smalltalk은 주입 없음(안전 기본값).
_TYPE_MAP = {
    "stock_judgment": {"방향 판단", "종목 비교", "시점 판단"},
    "industry_analysis": {"방향 판단", "리스크 점검"},
    "event_interpretation": {"방향 판단", "리스크 점검"},
    "strategy_portfolio": {"시점 판단"},
}


def load_playbooks(user_id: str) -> list[dict]:
    pb_dir = STORAGE_ROOT / "users" / user_id / "corpus" / "playbooks"
    out = []
    if not pb_dir.is_dir():
        return out
    for f in pb_dir.glob("*.json"):
        if f.name in ("clusters.json", "holdout.json", "holdout-report.json"):
            continue
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue  # 손상 파일은 무시하고 주입 없이 정상 답변 (스펙 §오류 처리)
    return out


def match_playbook(question: str, question_type: str, playbooks: list[dict]) -> dict | None:
    allowed = _TYPE_MAP.get(question_type)
    if not allowed:
        return None
    best, best_score = None, 0
    for pb in playbooks:
        if pb.get("status") != "holdout_passed":
            continue
        if pb.get("conclusionType") not in allowed:
            continue
        keys = set(pb.get("triggers", [])) | set(pb.get("topics", []))
        score = sum(1 for k in keys if k and k in question)
        if score > best_score:
            best, best_score = pb, score
    return best  # 키워드 0히트면 best_score=0 → None


def format_gates(pb: dict) -> str:
    lines = [f"[참고 절차 — {pb['situation']} (전문가 사고 재구성)]",
             "아래는 확인 '절차'다. 절차 내용을 사실·근거로 인용하지 말고, 계획 수립에만 써라."]
    for g in pb["gates"]:
        kill = f" / 킬: {g['kill']}" if g.get("kill") else ""
        lines.append(f"{g['order']}. {g['check']} (기준: {g['operationalization']}{kill})")
    return "\n".join(lines)


def format_connection(pb: dict) -> str:
    lines = [f"[사고 연결 참고 — {pb['situation']}]",
             "아래는 결론 연결 '방식'이다. 이 절의 내용을 사실 근거로 인용하지 마라.",
             f"연결: {pb['connection']}"]
    if pb.get("reservations"):
        lines.append(f"유보: {pb['reservations']}")
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인** — Run: `cd engine && .venv/bin/python -m pytest tests/test_playbook_match.py -v` / Expected: PASS 6개

- [ ] **Step 5: 배관 연결** (각 파일 최소 수정)

`engine/contracts/api.py` — AnswerRequest에 한 줄:
```python
    user_id: str = ""
```

`server.mjs:1806` 근처 payload에 한 줄 (라우트에 `req.user`가 있는지 확인 — chat 라우트는 인증 미들웨어 뒤):
```javascript
        user_id: req.user?.username || "",
```

`engine/app/main.py` — `_qa_pipeline`에서 `run_qa(...)` 호출에 `user_id=req.user_id` 전달.

`engine/orchestrator.py:137` — 시그니처에 `user_id: str | None = None` 추가. triage 직후·PLAN 호출 전에:
```python
    playbook = None
    if user_id:
        try:
            from stages.playbook import load_playbooks, match_playbook
            playbook = match_playbook(question, triage.question_type, load_playbooks(user_id))
        except Exception:
            playbook = None  # 주입 실패는 무주입 폴백 — 답변은 정상 진행
    yield {"type": "layer", "stage": "playbook",
           "matched": playbook["slug"] if playbook else None}
```
(triage 결과 변수명·레이어 방출 형식은 현행 orchestrator의 triage 레이어 코드를 그대로 답습한다. run_plan/run_synthesize 호출부에 `playbook=playbook` 추가.)

`engine/stages/plan.py:158` — `def run_plan(question, history=None, overrides=None, playbook=None)`. ctx 조립(162-165행) 뒤:
```python
    if playbook:
        from stages.playbook import format_gates
        ctx += "\n\n" + format_gates(playbook)
```
(Role A·B 공용 ctx에 붙인다 — sub_questions·needed_evidence가 게이트를 반영하게 하는 것이 목적.)

`engine/stages/synthesize.py` — `run_synthesize(..., playbook=None)`. `_render_context()`에 `[메모리 섹터 근거]`(139행) 섹션 다음에:
```python
    if playbook:
        from stages.playbook import format_connection
        parts.append(format_connection(playbook))
```
(`parts` 리스트 변수명은 실제 `_render_context` 구현의 누적 변수를 따른다.)

- [ ] **Step 6: 전체 엔진 테스트 + 커밋** — Run: `cd engine && .venv/bin/python -m pytest tests/ -x -q` / Expected: 전부 PASS (기존 테스트 회귀 없음)
  `git add engine/stages/playbook.py engine/contracts/api.py engine/orchestrator.py engine/stages/plan.py engine/stages/synthesize.py engine/app/main.py server.mjs engine/tests/test_playbook_match.py && git commit -m 'feat(playbook): 엔진 주입 — user_id 배관, 결정적 매칭, PLAN 게이트·SYNTHESIZE 연결 주입'`

- [ ] **Step 7: 배포 + 실질문 확인** — Run: `pm2 restart attn-engine attn-viewer`
  브라우저(playwright 로그인)에서 반도체 판단형 질문 1개 실행 → 레이어에 `stage: "playbook", matched: <slug>` 확인, 비반도체 질문에서 `matched: null` 확인. 스크린샷.

---

### Task 7: evals A/B (골든셋 보강 + 주입 전후 비교)

**Files:**
- Modify: `engine/evals/golden.jsonl` (반도체 판단형 6문 추가)
- Modify: `engine/evals/run_eval.py` (run_qa에 user_id 전달 — env `EVAL_PLAYBOOK_USER`)

**Interfaces:**
- Consumes: Task 6의 `run_qa(user_id=...)`
- Produces: 리포트 2개 (baseline/variant) — 비교 지표: verified_ratio, numeric_supported_ratio, keyword_ok, elapsed_s

- [ ] **Step 1: 골든셋에 추가** (`engine/evals/golden.jsonl` 끝에 6줄 — id는 기존 체계 답습)

```json
{"id": "sj-pb-01", "type": "stock_judgment", "question": "SK하이닉스 지금 들어가도 돼? HBM 계약 뉴스는 계속 나오는데", "must_include": ["HBM"], "must_not": [], "note": "플레이북 A/B: 시점판단 게이트 반영 여부"}
{"id": "sj-pb-02", "type": "stock_judgment", "question": "마이크론이랑 삼성전자 중에 메모리 사이클 후반엔 뭐가 나아?", "must_include": ["마이크론", "삼성전자"], "must_not": [], "note": "플레이북 A/B: 종목 비교"}
{"id": "ia-pb-01", "type": "industry_analysis", "question": "DRAM 감산 끝나간다는데 메모리 사이클 지금 어디쯤이야?", "must_include": ["감산"], "must_not": [], "note": "플레이북 A/B: 사이클 국면"}
{"id": "ia-pb-02", "type": "industry_analysis", "question": "HBM 공급과잉 온다는 말이 있는데 리스크 어떻게 봐야 해?", "must_include": ["HBM"], "must_not": [], "note": "플레이북 A/B: 리스크 점검"}
{"id": "ei-pb-01", "type": "event_interpretation", "question": "SK하이닉스가 CAPEX 늘린다고 발표했는데 이거 사이클에 무슨 의미야?", "must_include": ["CAPEX"], "must_not": [], "note": "플레이북 A/B: 이벤트 해석"}
{"id": "sj-pb-03", "type": "stock_judgment", "question": "반도체 장비주는 언제 들어가는 게 맞아? 지금 너무 오른 것 같은데", "must_include": ["장비"], "must_not": [], "note": "플레이북 A/B: 장비주 진입 시점"}
```

- [ ] **Step 2: run_eval에 user_id 전달** — `run_eval.py`의 `run_qa(...)` 호출에:
```python
user_id=os.environ.get("EVAL_PLAYBOOK_USER", "")
```
(env 미설정 = baseline: user_id 없음 → 주입 없음. 코드 분기 불필요.)

- [ ] **Step 3: A/B 실행**

```bash
cd engine
.venv/bin/python -m evals.run_eval --type stock_judgment --limit 10        # baseline
EVAL_PLAYBOOK_USER=ryze_yn .venv/bin/python -m evals.run_eval --type stock_judgment --limit 10  # variant
```
Expected: `evals/out/report-*.{jsonl,md}` 2쌍. variant 리포트에서 pb 질문들의 답변에 게이트 절차(확인 순서·킬 조건) 반영 여부를 확인하고, verified_ratio·numeric_supported_ratio가 baseline 대비 하락하지 않았는지 대조.

- [ ] **Step 4: 커밋** — `git add engine/evals/golden.jsonl engine/evals/run_eval.py && git commit -m 'feat(playbook): evals A/B — 반도체 판단형 6문 추가, EVAL_PLAYBOOK_USER 주입 토글'`

- [ ] **Step 5: 🛑 CP-3 — A/B 리포트를 사용자에게 보고. 품질 하락 시 롤백 경로: 해당 플레이북 status를 draft로 되돌리면 즉시 주입 차단.**

---

### Task 8: workflow-review.html 현행화 + 마감

**Files:**
- Modify: `docs/workflow-review.html` (public/docs와 하드링크 — 한쪽만 수정하면 됨, inode 동일 확인)
- Modify: `.superpowers/sdd/progress.md` (프로젝트 5 완료 기록)

- [ ] **Step 1: workflow-review.html 갱신** — ① 상단 meta 라인에 날짜·요지 추가, ② 전체 그래프(fnode)에 `playbook 매칭` 노드(triage→PLAN 사이) 반영, ③ 섹션 1b(사고 카드) 아래에 플레이북 합성·holdout·주입 카드 추가(기존 kv/why 마크업 답습), ④ 불변식 추가: "플레이북은 holdout_passed만, 1장만, 절차로만", ⑤ /html 목록 설명 갱신.

- [ ] **Step 2: 스크린샷 검증** — playwright로 https://attn.ngrok.app/docs/workflow-review.html 로그인→캡처→눈 확인 (memory: verify-ui-with-screenshots).

- [ ] **Step 3: 커밋 + SDD 레저 갱신** — `git add docs/workflow-review.html public/docs .superpowers/sdd/progress.md && git commit -m 'docs: workflow-review 현행화 — 플레이북 합성·holdout·주입 (2026-07-14)'`

---

## Self-Review 기록

- 스펙 커버리지: §합성(Task 2·3·4), §검증-holdout(Task 5), §선택+주입(Task 6), §검증-A/B(Task 7), §오류 처리(손상 파일 무시 — Task 1 loadPlaybooks·Task 6 load_playbooks, 주입 실패 무주입 폴백 — Task 6 Step 5, 롤백 — Task 7 CP-3). 시점 관리(asOf 버전 분리)는 "최신 우선 + reservations 기록"으로 단순화 — 실데이터에서 시기 갈림이 실제로 나오면 후속.
- 타입 일치: `validatePlaybook(playbook, Set)` 시그니처 Task 1↔3 일치, `pickHoldout` 반환 Map↔clusters.json 직렬화 시 Object.fromEntries 변환 명시, `loadAllCardsWithReview`는 Task 5에서 정의 지시.
- 미확정(스펙 §미확정) 해소: 매칭 키 = question_type 매핑 + triggers/topics 부분 문자열 히트(top-1). holdout 심판 = 프롬프트 Task 5 Step 3에 확정.
