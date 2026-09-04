import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";

const SCRIPT = fileURLToPath(new URL("../../scripts/create-report-editorial.mjs", import.meta.url));

test("editorial builder adds a reading layer without changing report evidence", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "attn-report-editorial-"));
  t.after(() => rm(root, { recursive: true, force: true }));

  const basePath = join(root, "base.json");
  const overlayPath = join(root, "overlay.json");
  const outputPath = join(root, "edited.json");
  const base = {
    id: "2026-09-04-1",
    seq: 1,
    generatedAt: "2026-09-04T06:39:09+09:00",
    title: "긴 원문 제목",
    format: "axes",
    cards: [
      { axis: "macro", title: "거시 원문", phenomenon: "거시 상세", sources: [{ url: "https://example.com/macro" }] },
      { axis: "memory", title: "메모리 원문", phenomenon: "메모리 상세", sources: [{ url: "https://example.com/memory" }] },
      { axis: "other", title: "기타 원문", phenomenon: "기타 상세", sources: [{ url: "https://example.com/other" }] },
    ],
    pipeline: { stages: [{ key: "collect", items: ["원시 근거"] }] },
    diagnostics: { stage_errors: ["검증 경고"] },
  };
  const overlay = {
    id: "2026-09-04-2",
    seq: 2,
    editorial: {
      label: "읽기 편집본",
      baseReportId: "2026-09-04-1",
      baseGeneratedAt: "2026-09-04T06:39:09+09:00",
      editedAt: "2026-09-04T14:30:00+09:00",
      headline: "짧은 편집 제목",
      deck: "핵심 설명",
      takeaways: [{ axis: "macro", title: "거시", text: "요약" }],
    },
    cardBriefs: {
      macro: { headline: "거시 제목", summary: "거시 요약", keyNumbers: [], flow: [], scenarioGuide: [], watchlist: [], bottomLine: "거시 결론" },
      memory: { headline: "메모리 제목", summary: "메모리 요약", keyNumbers: [], flow: [], scenarioGuide: [], watchlist: [], bottomLine: "메모리 결론" },
      other: { headline: "기타 제목", summary: "기타 요약", keyNumbers: [], flow: [], scenarioGuide: [], watchlist: [], bottomLine: "기타 결론" },
    },
  };
  await writeFile(basePath, JSON.stringify(base));
  await writeFile(overlayPath, JSON.stringify(overlay));

  const result = spawnSync(process.execPath, [SCRIPT,
    "--base", basePath,
    "--overlay", overlayPath,
    "--output", outputPath,
  ], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);

  const edited = JSON.parse(await readFile(outputPath, "utf8"));
  assert.equal(edited.id, "2026-09-04-2");
  assert.equal(edited.seq, 2);
  assert.deepEqual(edited.editorial, overlay.editorial);
  assert.deepEqual(edited.pipeline, base.pipeline);
  assert.deepEqual(edited.diagnostics, base.diagnostics);
  assert.deepEqual(edited.cards.map(({ brief, ...card }) => card), base.cards);
  assert.deepEqual(edited.cards.map((card) => card.brief), [
    overlay.cardBriefs.macro,
    overlay.cardBriefs.memory,
    overlay.cardBriefs.other,
  ]);
});
