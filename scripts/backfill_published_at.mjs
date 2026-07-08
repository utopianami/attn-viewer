// index.jsonl에 publishedAt(게시 시각 ISO)을 채운다 — metadata의 listItem.addDate에서.
// 1회성 마이그레이션 (2026-07-08, 이후 크롤은 crawl_naver_blog.mjs가 직접 기록).
// 사용: node scripts/backfill_published_at.mjs [--user ryze_yn]
import { readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const user = process.argv.includes("--user")
  ? process.argv[process.argv.indexOf("--user") + 1]
  : "ryze_yn";
const naverRoot = join(process.cwd(), "storage", "users", user, "corpus", "naver");

let updated = 0;
let missing = 0;
for (const blogId of await readdir(naverRoot)) {
  const root = join(naverRoot, blogId);
  let text;
  try {
    text = await readFile(join(root, "index.jsonl"), "utf8");
  } catch {
    continue;
  }
  const out = [];
  for (const line of text.split("\n")) {
    if (!line) {
      continue;
    }
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    if (!row.publishedAt) {
      try {
        const meta = JSON.parse(await readFile(join(root, "metadata", `${row.id}.json`), "utf8"));
        const addDate = meta.listItem?.addDate;
        if (addDate) {
          row.publishedAt = new Date(addDate).toISOString();
          updated += 1;
        } else {
          missing += 1;
        }
      } catch {
        missing += 1;
      }
    }
    out.push(JSON.stringify(row));
  }
  await writeFile(join(root, "index.jsonl"), `${out.join("\n")}\n`, "utf8");
  console.log(`${blogId}: done`);
}
console.log(JSON.stringify({ updated, missing }));
