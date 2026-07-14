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
