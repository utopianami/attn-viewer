import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const SCRIPT = fileURLToPath(new URL("../../scripts/create-report-editorial.mjs", import.meta.url));

function brief(label) {
  return {
    headline: `${label} 제목`,
    summary: `${label} 요약`,
    keyNumbers: [{ label: "가격", value: "+55%", context: "계약가", tone: "positive" }],
    flow: [
      { label: "원인", detail: "정책 신호", tone: "neutral" },
      { label: "결과", detail: "시장 반응", tone: "warning" },
    ],
    scenarioGuide: [
      { polarity: "positive", condition: "우호 조건", outcome: "상승 여력" },
      { polarity: "negative", condition: "경계 조건", outcome: "하락 위험" },
    ],
    watchlist: [{ label: "가격", current: "괴리", trigger: "방향 일치 여부" }],
    bottomLine: `${label} 결론`,
  };
}

function fixtures() {
  const base = {
    id: "2026-09-04-1",
    seq: 1,
    generatedAt: "2026-09-04T06:39:09+09:00",
    title: "긴 원문 제목",
    window: { from: "2026-09-03T18:30:00+09:00", to: "2026-09-04T06:30:00+09:00" },
    finalOpinion: { text: "세 축의 괴리를 관찰한다.", confidence: "중" },
    claims: [],
    format: "axes",
    cards: [
      { axis: "macro", title: "거시 원문", phenomenon: "거시 상세", sources: [{ url: "https://example.com/macro" }] },
      { axis: "memory", title: "메모리 원문", phenomenon: "메모리 상세", sources: [{ url: "https://example.com/memory" }] },
      { axis: "other", title: "기타 원문", phenomenon: "기타 상세", sources: [{ url: "https://example.com/other" }] },
    ],
    pipeline: { stages: [{ key: "collect", label: "수집", items: ["원시 근거"] }] },
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
      macro: brief("거시"),
      memory: brief("메모리"),
      other: brief("기타"),
    },
  };
  return { base, overlay };
}

function runBuilder(basePath, overlayPath, outputPath) {
  return spawnSync(process.execPath, [SCRIPT,
    "--base", basePath,
    "--overlay", overlayPath,
    "--output", outputPath,
  ], { encoding: "utf8" });
}

test("editorial builder adds a reading layer without changing report evidence", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "attn-report-editorial-"));
  t.after(() => rm(root, { recursive: true, force: true }));

  const basePath = join(root, "base.json");
  const overlayPath = join(root, "overlay.json");
  const outputPath = join(root, "2026-09-04-2.json");
  const { base, overlay } = fixtures();
  await writeFile(basePath, JSON.stringify(base));
  await writeFile(overlayPath, JSON.stringify(overlay));

  const result = runBuilder(basePath, overlayPath, outputPath);
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

test("editorial builder rejects data that violates the OpenAPI reading-layer contract", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "attn-report-editorial-invalid-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const { base, overlay } = fixtures();
  overlay.cardBriefs.memory.keyNumbers = [];
  const basePath = join(root, "base.json");
  const overlayPath = join(root, "overlay.json");
  const outputPath = join(root, `${overlay.id}.json`);
  await writeFile(basePath, JSON.stringify(base));
  await writeFile(overlayPath, JSON.stringify(overlay));

  const result = runBuilder(basePath, overlayPath, outputPath);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /MarketReport.*cards.*brief.*keyNumbers|minItems/i);
});

test("editorial builder enforces a new sequential id and matching output filename", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "attn-report-editorial-id-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const { base, overlay } = fixtures();
  const basePath = join(root, "base.json");
  const overlayPath = join(root, "overlay.json");
  await writeFile(basePath, JSON.stringify(base));
  await writeFile(overlayPath, JSON.stringify(overlay));

  const wrongName = runBuilder(basePath, overlayPath, join(root, "different.json"));
  assert.notEqual(wrongName.status, 0);
  assert.match(wrongName.stderr, /output.*2026-09-04-2\.json/i);

  overlay.id = base.id;
  overlay.seq = base.seq;
  await writeFile(overlayPath, JSON.stringify(overlay));
  const unchanged = runBuilder(basePath, overlayPath, join(root, `${base.id}.json`));
  assert.notEqual(unchanged.status, 0);
  assert.match(unchanged.stderr, /새 id|순번/i);
});

test("concurrent editorial builders cannot overwrite the first published report", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "attn-report-editorial-race-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const { base, overlay } = fixtures();
  base.racePadding = "x".repeat(2_000_000);
  const basePath = join(root, "base.json");
  const overlayPath = join(root, "overlay.json");
  const outputPath = join(root, `${overlay.id}.json`);
  await writeFile(basePath, JSON.stringify(base));
  await writeFile(overlayPath, JSON.stringify(overlay));

  const runs = Array.from({ length: 6 }, () => new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT,
      "--base", basePath,
      "--overlay", overlayPath,
      "--output", outputPath,
    ], { stdio: ["ignore", "pipe", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => resolve({ code, stderr }));
  }));
  const results = await Promise.all(runs);
  assert.equal(results.filter(({ code }) => code === 0).length, 1, JSON.stringify(results));
  assert.equal(results.filter(({ code }) => code !== 0).length, 5, JSON.stringify(results));
  assert.ok(results.filter(({ code }) => code !== 0).every(({ stderr }) => /이미 존재/.test(stderr)));
});
