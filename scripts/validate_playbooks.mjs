// holdout 검증 — 플레이북별로: holdout 카드 상황 → (플레이북 예측 vs 대조군 예측) → 게이트 단위 심판.
// 통과 기준: coverage(with) > coverage(control) AND killRecall(with) >= killRecall(control).
// 통과 시 status=holdout_passed로 갱신. 반드시 프로젝트 루트에서 실행.
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { runCodexSummary } from "../lib/summaries.mjs";
import {
  alignVerdicts, buildJudgePrompt, buildPredictionPrompt, loadAllCardsWithReview, loadPlaybooks,
  playbooksDir, scorePlaybook,
} from "../lib/playbooks.mjs";

const PRED_SCHEMA = fileURLToPath(new URL("../schemas/playbook-prediction.schema.json", import.meta.url));
const VERDICT_SCHEMA = fileURLToPath(new URL("../schemas/playbook-verdict.schema.json", import.meta.url));

const args = process.argv.slice(2);
const userIdx = args.indexOf("--user");
if (userIdx === -1) { console.error("--user 필수"); process.exit(1); }
const user = args[userIdx + 1];
if (!user || user.startsWith("--")) { console.error("--user 필수"); process.exit(1); }
const corpusRoot = join("storage", "users", user, "corpus");

const clustersDoc = JSON.parse(await readFile(join(playbooksDir(corpusRoot), "clusters.json"), "utf8"));
const cards = await loadAllCardsWithReview(corpusRoot); // holdout 카드는 needsReview여도 정답으로 쓸 수 있어야 함
const byId = new Map(cards.map((c) => [c.id, c]));
const playbooks = await loadPlaybooks(corpusRoot);

// 재개: 이전 리포트에 판정이 있는 슬러그는 스킵 (codex 크래시로 중단된 배치 이어가기).
// --fresh로 전량 재판정. error 항목은 판정이 아니므로 재시도 대상.
const reportPath = join(playbooksDir(corpusRoot), "holdout-report.json");
const fresh = args.includes("--fresh");
let report = [];
if (!fresh) {
  try {
    report = JSON.parse(await readFile(reportPath, "utf8")).report.filter((r) => !r.error);
  } catch { /* 리포트 없음 — 처음부터 */ }
}
const judged = new Set(report.map((r) => r.slug));
const saveReport = () => writeFile(reportPath,
  `${JSON.stringify({ judgedAt: new Date().toISOString(), report }, null, 2)}\n`, "utf8");

for (const pb of playbooks) {
  if (judged.has(pb.slug)) { console.log(`${pb.slug}: 이전 판정 재사용 — 스킵`); continue; }
  const holdoutIds = (clustersDoc.holdout[pb.slug] || []).filter((id) => byId.has(id));

  // holdout 없음: 이전에 holdout_passed였으면 draft로 복귀
  if (holdoutIds.length === 0) {
    if (pb.status === "holdout_passed") {
      const path = join(playbooksDir(corpusRoot), `${pb.slug}.json`);
      const cur = JSON.parse(await readFile(path, "utf8"));
      cur.status = "draft";
      delete cur.holdoutScores;
      await writeFile(path, `${JSON.stringify(cur, null, 2)}\n`, "utf8");
      console.log(`${pb.slug}: holdout 없음 — holdout_passed → draft 복귀`);
    }
    report.push({ slug: pb.slug, result: "no-holdout(draft 유지)" });
    continue;
  }

  // codex 개별 크래시(시그널 종료 등)가 전체 배치를 죽이지 않도록 격리 — 실패는 error로 기록 후 다음 재실행에서 재시도
  const agg = { with: [], control: [] };
  try {
    for (const id of holdoutIds) {
      const card = byId.get(id);
      for (const [key, playbook] of [["with", pb], ["control", null]]) {
        const predRaw = await runCodexSummary(buildPredictionPrompt(card.situation, playbook),
          { schemaPath: PRED_SCHEMA, timeoutMs: 420_000 });
        const pred = JSON.parse(predRaw).plan
          .map((p) => `${p.order}. ${p.check}${p.kill ? ` (킬: ${p.kill})` : ""}`).join("\n");
        const verdictRaw = await runCodexSummary(buildJudgePrompt(card, pred),
          { schemaPath: VERDICT_SCHEMA, timeoutMs: 420_000 });
        // hasKill은 코드가 카드에서 결정 — LLM 출력에서 가져오지 않는다
        const aligned = alignVerdicts(card, JSON.parse(verdictRaw).items);
        agg[key].push(...aligned);
      }
    }
  } catch (err) {
    report.push({ slug: pb.slug, error: String(err).slice(0, 300) });
    await saveReport();
    console.warn(`${pb.slug}: 판정 실패 — ${String(err).slice(0, 120)}`);
    continue;
  }
  const sWith = scorePlaybook(agg.with);
  const sControl = scorePlaybook(agg.control);
  const passed = sWith.coverage > sControl.coverage && sWith.killRecall >= sControl.killRecall && sWith.orderScore >= sControl.orderScore;
  report.push({ slug: pb.slug, holdout: holdoutIds.length, with: sWith, control: sControl, passed });

  if (passed) {
    const path = join(playbooksDir(corpusRoot), `${pb.slug}.json`);
    const cur = JSON.parse(await readFile(path, "utf8"));
    cur.status = "holdout_passed";
    cur.holdoutScores = { with: sWith, control: sControl, judgedAt: new Date().toISOString() };
    await writeFile(path, `${JSON.stringify(cur, null, 2)}\n`, "utf8");
  } else if (pb.status === "holdout_passed") {
    // 이전 실행에서 통과했지만 이번에는 실패 — 상태 복귀
    const path = join(playbooksDir(corpusRoot), `${pb.slug}.json`);
    const cur = JSON.parse(await readFile(path, "utf8"));
    cur.status = "draft";
    delete cur.holdoutScores;
    await writeFile(path, `${JSON.stringify(cur, null, 2)}\n`, "utf8");
    console.log(`${pb.slug}: FAIL — holdout_passed → draft 복귀`);
  }

  await saveReport(); // 증분 기록 — 중단돼도 판정 결과 보존
  console.log(`${pb.slug}: with=${JSON.stringify(sWith)} control=${JSON.stringify(sControl)} → ${passed ? "PASS" : "FAIL"}`);
}

await saveReport();
console.log("리포트:", reportPath);
