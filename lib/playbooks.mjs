// 플레이북 — 사고 카드를 상황 단위로 합성한 게이트 절차를 저장·검증한다.
// 스펙: docs/superpowers/specs/2026-07-13-thinking-playbook-design.md
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const PLAYBOOK_SCHEMA_PATH = fileURLToPath(new URL("../schemas/playbook.schema.json", import.meta.url));
export const CLUSTERS_SCHEMA_PATH = fileURLToPath(new URL("../schemas/playbook-clusters.schema.json", import.meta.url));

// 합성 입력 카드: 전 블로그 analysis/*.json 순회. 필요에 따라 needsReview 필터 적용.
async function _loadCards(corpusRoot, { includeReview = false } = {}) {
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
        if (!includeReview && card.needsReview) continue;
        cards.push({ blogId, ...card });
      } catch { /* 손상 카드는 무시 */ }
    }
  }
  return cards;
}

// needsReview 카드는 제외하고 로드 (합성 입력용)
export async function loadAllCards(corpusRoot) {
  return _loadCards(corpusRoot, { includeReview: false });
}

// needsReview 카드도 포함해서 로드 (holdout 검증용 정답)
export async function loadAllCardsWithReview(corpusRoot) {
  return _loadCards(corpusRoot, { includeReview: true });
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
  for (const f of files.filter((f) => f.endsWith(".json") && !["holdout.json", "clusters.json", "holdout-report.json"].includes(f))) {
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
  const { playbook, dropped } = validatePlaybook(draft, new Set(members.map((c) => c.id)));
  if (!playbook || playbook.gates.length === 0) {
    console.warn(`[synthesize] ${cluster.slug} 거부: ${dropped.join(" / ")}`);
    return null;
  }
  if (dropped.length) console.warn(`[synthesize] ${cluster.slug} 게이트 드롭: ${dropped.join(" / ")}`);
  return savePlaybook(corpusRoot, playbook);
}

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

정답 항목 순서대로, 각 항목마다 정확히 하나의 객체 {order, covered, killCovered, predictedOrder}를 반환하라.
killCovered는 해당 정답 항목에 킬이 없거나 예측이 킬을 담지 않으면 false.
predictedOrder는 이 정답 항목을 담은 예측 항목의 번호(1-based). covered=false이면 null.
hasKill은 반환하지 마라 — 코드가 직접 결정한다.

[정답 — 실제 확인 목록]
${checks}

[예측]
${prediction}`;
}

// 심판 출력 items를 실제 카드 checks에 정렬한다.
// - 카드의 각 check에 대해: verdict items에서 order 일치하는 첫 항목을 찾는다 (없으면 covered=false, killCovered=false).
// - hasKill은 카드 check의 kill 유무에서 코드가 결정한다 (LLM 출력 불사용).
// - 중복 order: 첫 번째 항목을 사용한다.
export function alignVerdicts(card, items) {
  const byOrder = new Map();
  for (const item of items) {
    if (!byOrder.has(item.order)) byOrder.set(item.order, item);
  }
  return (card.checks || []).map((c) => {
    const v = byOrder.get(c.order) || { covered: false, killCovered: false };
    const predictedOrder = v.covered && Number.isInteger(v.predictedOrder) ? v.predictedOrder : null;
    return { covered: !!v.covered, killCovered: !!v.killCovered, hasKill: c.kill != null, predictedOrder };
  });
}

// scorePlaybook(verdictGroups): verdictGroups is an array of arrays (one per holdout card).
// coverage/killRecall: aggregate over all items flattened.
// orderScore: compute pairs WITHIN each group only, pool across groups.
//   null-gaming rule: covered=true with predictedOrder===null counts in denominator as incorrect.
export function scorePlaybook(verdictGroups) {
  const allVerdicts = verdictGroups.flat();
  const covered = allVerdicts.filter((v) => v.covered).length;
  const withKill = allVerdicts.filter((v) => v.hasKill);
  const killCovered = withKill.filter((v) => v.killCovered).length;

  // orderScore: pairs within each group only
  let totalPairs = 0, correctPairs = 0;
  for (const group of verdictGroups) {
    // include covered=true items regardless of predictedOrder (null counts as wrong)
    const coveredItems = group
      .map((v, i) => ({ actualIdx: i, predictedOrder: v.predictedOrder }))
      .filter((_, i) => group[i].covered === true);
    if (coveredItems.length >= 2) {
      for (let i = 0; i < coveredItems.length; i++) {
        for (let j = i + 1; j < coveredItems.length; j++) {
          totalPairs++;
          const pi = coveredItems[i].predictedOrder;
          const pj = coveredItems[j].predictedOrder;
          // null predictedOrder means cannot order → always wrong
          if (pi !== null && pj !== null && pi < pj) correctPairs++;
        }
      }
    }
  }
  const orderScore = totalPairs === 0 ? 1 : correctPairs / totalPairs;

  return {
    coverage: allVerdicts.length ? covered / allVerdicts.length : 0,
    killRecall: withKill.length ? killCovered / withKill.length : 1,
    orderScore,
  };
}

export function buildMatchKeysPrompt(playbooks) {
  const blocks = playbooks.map((pb) =>
    `slug: ${pb.slug}
상황: ${pb.situation}
triggers: ${(pb.triggers || []).join(", ")}
topics: ${(pb.topics || []).join(", ")}`).join("\n\n");
  return `각 플레이북마다 사용자 질문에 실제로 등장할 법한 짧은 매칭 키 5~12개를 뽑아라. 종목명·지표명·상황 표현 등 2~10자 내외 짧은 표현만. 복합 구절 금지(예: '레거시 DRAM·DDR4 가격 급등' 대신 '레거시 DRAM', 'DDR4', '가격 급등'). 해당 플레이북 상황에 특유한 키를 우선하고, 모든 반도체 질문에 걸리는 과잉 일반 키(예: '반도체', '주가')는 넣지 마라.

${blocks}`;
}
