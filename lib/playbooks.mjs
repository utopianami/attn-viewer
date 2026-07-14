// 플레이북 — 사고 카드를 상황 단위로 합성한 게이트 절차를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

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
