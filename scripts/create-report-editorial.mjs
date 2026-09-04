#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { link, readFile, unlink, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = fileURLToPath(new URL("../", import.meta.url));
const CONTRACT_VALIDATOR = join(REPOSITORY_ROOT, "scripts", "validate_market_report.py");
const PYTHON = join(REPOSITORY_ROOT, "engine", ".venv", "bin", "python");

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) throw new Error("사용법: --base <json> --overlay <json> --output <json>");
    args[key.slice(2)] = value;
  }
  for (const key of ["base", "overlay", "output"]) {
    if (!args[key]) throw new Error(`필수 인자 누락: --${key}`);
  }
  return args;
}

function assertObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}은 객체여야 합니다.`);
  }
}

function expectedCardAxes(base) {
  if (base.axisModel === "topics_v1") return ["macro", "topic1", "topic2"];
  if (base.axisModel == null) return ["macro", "memory", "other"];
  throw new Error(`지원하지 않는 axisModel: ${base.axisModel}`);
}

function assertExactAxes(values, expected, label) {
  const counts = new Map();
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
  const exact = values.length === expected.length
    && expected.every((axis) => counts.get(axis) === 1);
  if (!exact) {
    throw new Error(`${label}: ${expected.join("/")} 카드가 정확히 하나씩 필요합니다.`);
  }
}

function buildEditorialReport(base, overlay) {
  assertObject(base, "base");
  assertObject(overlay, "overlay");
  assertObject(overlay.editorial, "overlay.editorial");
  assertObject(overlay.cardBriefs, "overlay.cardBriefs");
  if (!/^[A-Za-z0-9._-]+$/.test(String(overlay.id || ""))) throw new Error("overlay.id가 올바르지 않습니다.");
  if (!Number.isInteger(overlay.seq) || overlay.seq < 1) throw new Error("overlay.seq는 양의 정수여야 합니다.");
  if (overlay.id === base.id) throw new Error("편집본에는 원본과 다른 새 id가 필요합니다.");
  if (!Number.isInteger(base.seq) || overlay.seq !== base.seq + 1) {
    throw new Error(`편집본 순번은 원본 다음 번호(${Number(base.seq) + 1})여야 합니다.`);
  }
  if (overlay.editorial.baseReportId !== base.id) throw new Error("편집본의 baseReportId가 원본 id와 다릅니다.");
  if (overlay.editorial.baseGeneratedAt !== base.generatedAt) throw new Error("편집본의 baseGeneratedAt이 원본 시각과 다릅니다.");
  if (base.format !== "axes" || !Array.isArray(base.cards)) throw new Error("3축 리포트만 편집할 수 있습니다.");

  const expectedAxes = expectedCardAxes(base);
  assertExactAxes(base.cards.map((card) => card?.axis), expectedAxes,
    base.axisModel === "topics_v1" ? "topics_v1 원본 카드 구성 오류" : "legacy 원본 카드 구성 오류");
  const takeaways = Array.isArray(overlay.editorial.takeaways) ? overlay.editorial.takeaways : [];
  assertExactAxes(takeaways.map((item) => item?.axis), expectedAxes,
    "MarketReport.editorial.takeaways contains 오류");

  const cards = base.cards.map((card) => {
    const brief = overlay.cardBriefs[card.axis];
    assertObject(brief, `cardBriefs.${card.axis}`);
    return { ...card, brief };
  });

  return {
    ...base,
    id: overlay.id,
    seq: overlay.seq,
    editorial: overlay.editorial,
    cards,
  };
}

function validateContract(reportPath) {
  const result = spawnSync(PYTHON, [CONTRACT_VALIDATOR, reportPath], {
    cwd: REPOSITORY_ROOT,
    encoding: "utf8",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(String(result.stderr || result.stdout || "OpenAPI 계약 검증 실패").trim());
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const base = JSON.parse(await readFile(args.base, "utf8"));
  const overlay = JSON.parse(await readFile(args.overlay, "utf8"));
  const report = buildEditorialReport(base, overlay);
  const expectedFilename = `${report.id}.json`;
  if (basename(args.output) !== expectedFilename) {
    throw new Error(`--output 파일명은 ${expectedFilename}이어야 합니다.`);
  }
  const temporary = `${args.output}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(report, null, 1)}\n`, { flag: "wx" });
    validateContract(temporary);
    try {
      await link(temporary, args.output);
    } catch (error) {
      if (error?.code === "EEXIST") throw new Error(`출력 파일이 이미 존재합니다: ${args.output}`);
      throw error;
    }
  } catch (error) {
    throw error;
  } finally {
    await unlink(temporary).catch(() => {});
  }
  process.stdout.write(`${report.id}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
