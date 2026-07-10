// 저장된 raw HTML에서 본문을 재파싱해 articles/metadata/index를 갱신한다.
// 배경(2026-07-10): 구 컴포넌트 분리 정규식이 ① 컴포넌트 1개짜리 글은 전부,
// ② 여러 개짜리 글은 마지막 컴포넌트를 버리는 버그 → lib/naver-parse.mjs로 수정.
// 재수집 없이 raw에서 복구한다. 사용: node scripts/reparse_from_raw.mjs [--user ryze_yn] [--blog ID]
import { readFile, readdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { basename, join } from "node:path";
import { extractMainContainer, parseBody } from "../lib/naver-parse.mjs";

const args = process.argv.slice(2);
const user = args.includes("--user") ? args[args.indexOf("--user") + 1] : "ryze_yn";
const onlyBlog = args.includes("--blog") ? args[args.indexOf("--blog") + 1] : "";
const naverRoot = join(process.cwd(), "storage", "users", user, "corpus", "naver");

const stats = { scanned: 0, changed: 0, unchanged: 0, noRaw: 0, noMain: 0, errors: 0 };

for (const blogId of await readdir(naverRoot)) {
  if (onlyBlog && blogId !== onlyBlog) {
    continue;
  }
  const root = join(naverRoot, blogId);
  let articleFiles;
  try {
    articleFiles = (await readdir(join(root, "articles"))).filter((file) => file.endsWith(".md"));
  } catch {
    continue;
  }

  const indexPath = join(root, "index.jsonl");
  let indexRows = [];
  try {
    indexRows = (await readFile(indexPath, "utf8")).split("\n").filter(Boolean).map((line) => JSON.parse(line));
  } catch {
    indexRows = [];
  }
  const indexById = new Map(indexRows.map((row) => [row.id, row]));
  let indexDirty = false;

  for (const file of articleFiles) {
    const articleId = basename(file, ".md");
    stats.scanned += 1;
    try {
      let html;
      try {
        html = await readFile(join(root, "raw", `${articleId}.html`), "utf8");
      } catch {
        stats.noRaw += 1;
        continue;
      }
      const main = extractMainContainer(html);
      if (!main) {
        stats.noMain += 1;
        continue;
      }
      const { mdParts } = parseBody(main, articleId);
      let body = mdParts.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();

      const oldMd = await readFile(join(root, "articles", file), "utf8");
      const frontmatterMatch = oldMd.match(/^---\n[\s\S]*?\n---\n/);
      const frontmatter = frontmatterMatch ? frontmatterMatch[0] : "";
      const afterFm = oldMd.slice(frontmatter.length);
      const titleLine = afterFm.match(/^# .*\n/)?.[0] ?? "";
      const oldBody = afterFm.slice(titleLine.length).trim();

      // 이미지 다운로드된 글이면 placeholder를 실제 파일 경로로 치환 (크롤러와 동일)
      let metadata = null;
      try {
        metadata = JSON.parse(await readFile(join(root, "metadata", `${articleId}.json`), "utf8"));
      } catch {
        metadata = null;
      }
      if (metadata?.imageDownloadEnabled && Array.isArray(metadata.images)) {
        for (const image of metadata.images) {
          if (image.file) {
            const placeholder = basename(image.file).replace(/\.[^.]+$/, "");
            body = body.replaceAll(`assets/${articleId}/${placeholder}`, image.file);
          }
        }
      }

      if (body === oldBody) {
        stats.unchanged += 1;
        continue;
      }

      const contentHash = createHash("sha256").update(body).digest("hex");
      const newFrontmatter = frontmatter.replace(/contentHash: "[0-9a-f]*"/, `contentHash: ${JSON.stringify(contentHash)}`);
      await writeFile(join(root, "articles", file), `${newFrontmatter}${titleLine}${body}\n`, "utf8");

      if (metadata) {
        metadata.contentHash = contentHash;
        metadata.reparsedAt = new Date().toISOString();
        await writeFile(join(root, "metadata", `${articleId}.json`), JSON.stringify(metadata, null, 2), "utf8");
      }
      const row = indexById.get(articleId);
      if (row && row.contentHash !== contentHash) {
        row.contentHash = contentHash;
        indexDirty = true;
      }
      stats.changed += 1;
    } catch (error) {
      stats.errors += 1;
      console.error(`${articleId}: ${error.message}`);
    }
  }

  if (indexDirty) {
    await writeFile(indexPath, `${indexRows.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf8");
  }
  console.log(`${blogId}: done`);
}

console.log(JSON.stringify(stats));
