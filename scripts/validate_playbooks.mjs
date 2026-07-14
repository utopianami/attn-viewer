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
