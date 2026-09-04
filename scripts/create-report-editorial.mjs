#!/usr/bin/env node

import { access, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { constants } from "node:fs";

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

function buildEditorialReport(base, overlay) {
  assertObject(base, "base");
  assertObject(overlay, "overlay");
  assertObject(overlay.editorial, "overlay.editorial");
  assertObject(overlay.cardBriefs, "overlay.cardBriefs");
  if (!/^[A-Za-z0-9._-]+$/.test(String(overlay.id || ""))) throw new Error("overlay.id가 올바르지 않습니다.");
  if (!Number.isInteger(overlay.seq) || overlay.seq < 1) throw new Error("overlay.seq는 양의 정수여야 합니다.");
  if (overlay.editorial.baseReportId !== base.id) throw new Error("편집본의 baseReportId가 원본 id와 다릅니다.");
  if (overlay.editorial.baseGeneratedAt !== base.generatedAt) throw new Error("편집본의 baseGeneratedAt이 원본 시각과 다릅니다.");
  if (base.format !== "axes" || !Array.isArray(base.cards)) throw new Error("3축 리포트만 편집할 수 있습니다.");

  const cards = base.cards.map((card) => {
    const brief = overlay.cardBriefs[card.axis];
    assertObject(brief, `cardBriefs.${card.axis}`);
    return { ...card, brief };
  });
  const axes = new Set(cards.map((card) => card.axis));
  for (const axis of ["macro", "memory", "other"]) {
    if (!axes.has(axis)) throw new Error(`원본 카드 누락: ${axis}`);
  }

  return {
    ...base,
    id: overlay.id,
    seq: overlay.seq,
    editorial: overlay.editorial,
    cards,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  try {
    await access(args.output, constants.F_OK);
    throw new Error(`출력 파일이 이미 존재합니다: ${args.output}`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  const base = JSON.parse(await readFile(args.base, "utf8"));
  const overlay = JSON.parse(await readFile(args.overlay, "utf8"));
  const report = buildEditorialReport(base, overlay);
  const temporary = `${args.output}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(report, null, 1)}\n`, { flag: "wx" });
    await rename(temporary, args.output);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
  process.stdout.write(`${report.id}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
