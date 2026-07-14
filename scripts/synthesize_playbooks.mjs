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
    runCodex: (p) => runCodexSummary(p, { schemaPath: CLUSTERS_SCHEMA_PATH, timeoutMs: 900_000 }), // 2026-07-14 실측: 213장 클러스터링 420s 타임아웃 → 900s 성공
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
