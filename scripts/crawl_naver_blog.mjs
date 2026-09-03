import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { basename, extname, join } from "node:path";
import { extractMainContainer, parseBody, parseHeader } from "../lib/naver-parse.mjs";

const DEFAULT_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";

const args = parseArgs(process.argv.slice(2));
const blogId = args.blogId || positional(0);
if (!blogId) {
  console.error(
    "Usage: node scripts/crawl_naver_blog.mjs --blogId ranto28 [--user ryze_yn] [--limit 50] [--download-images]",
  );
  process.exit(1);
}

const user = args.user || process.env.USER || "default";
const itemCount = parsePositiveInt(args.itemCount, 24);
const limit = args.limit ? parsePositiveInt(args.limit, 0) : 0;
const startPage = parsePositiveInt(args.startPage, 1);
const delayMs = parsePositiveInt(args.delayMs, 700);
const imageDelayMs = parsePositiveInt(args.imageDelayMs, 150);
const stopAfterConsecutiveFailures = args.stopAfterConsecutiveFailures
  ? parsePositiveInt(args.stopAfterConsecutiveFailures, 0)
  : 0;
const downloadImages = Boolean(args.downloadImages);
const force = Boolean(args.force);
const since = parseSince(args.since);
if (args.since && !since) {
  console.error("--since must be a valid ISO 8601 date or date-time");
  process.exit(1);
}
const sinceMs = since ? Date.parse(since) : 0;
// 증분 모드: 이미 저장된 글을 연속 N개 만나면 종료 (새 글 감지용). --stopOnKnown [N], 기본 10.
const stopOnKnown = args.stopOnKnown ? parsePositiveInt(args.stopOnKnown, 10) : 0;

const corpusRoot = join(process.cwd(), "storage", "users", user, "corpus");
const root = join(corpusRoot, "naver", blogId);
const dirs = {
  root,
  articles: join(root, "articles"),
  raw: join(root, "raw"),
  metadata: join(root, "metadata"),
  assetsRoot: join(root, "assets"),
  jobs: join(root, "jobs"),
};

for (const dir of Object.values(dirs)) {
  await mkdir(dir, { recursive: true });
}

const jobId = `naver-${blogId}-${new Date().toISOString().replace(/[:.]/g, "-")}`;
const jobPath = join(dirs.jobs, `${jobId}.json`);
const startedAt = new Date().toISOString();
const stats = {
  jobId,
  blogId,
  user,
  startedAt,
  updatedAt: startedAt,
  discovered: 0,
  saved: 0,
  skipped: 0,
  failed: 0,
  imageErrors: 0,
  totalCount: null,
  lastPage: null,
  crawlSince: since,
  cutoffReached: false,
  done: false,
  errors: [],
};

await writeJob();

let savedOrSeen = 0;
let page = startPage;
let consecutiveFailures = 0;
let consecutiveKnown = 0;
while (true) {
  const list = await fetchPostList(blogId, page, itemCount);
  stats.totalCount = list.totalCount || stats.totalCount;
  stats.lastPage = page;
  stats.discovered += list.items.length;
  await writeJob();

  if (!list.items.length) {
    break;
  }

  for (const item of list.items) {
    const publishedMs = Number(item.addDate || 0);
    if (sinceMs && publishedMs > 0 && publishedMs < sinceMs) {
      stats.cutoffReached = true;
      stats.done = true;
      stats.updatedAt = new Date().toISOString();
      await writeJob();
      printStats("since cutoff reached");
      process.exit(0);
    }
    if (sinceMs && !publishedMs) {
      stats.skipped += 1;
      continue;
    }
    if (limit && savedOrSeen >= limit) {
      stats.done = true;
      await writeJob();
      printStats("limit reached");
      process.exit(0);
    }
    savedOrSeen += 1;

    const logNo = String(item.logNo);
    const articleId = `naver-${blogId}-${logNo}`;
    if (!force && (await fileExists(join(dirs.articles, `${articleId}.md`)))) {
      stats.skipped += 1;
      consecutiveFailures = 0;
      consecutiveKnown += 1;
      if (stopOnKnown && consecutiveKnown >= stopOnKnown) {
        stats.done = true;
        stats.updatedAt = new Date().toISOString();
        await writeJob();
        printStats("stopped on known posts");
        process.exit(0);
      }
      continue;
    }
    consecutiveKnown = 0;

    try {
      const result = await savePost({ blogId, logNo, listItem: item });
      stats.saved += 1;
      stats.imageErrors += result.imageErrors;
      consecutiveFailures = 0;
      console.log(
        JSON.stringify({
          status: "saved",
          count: stats.saved,
          seen: savedOrSeen,
          page,
          totalCount: stats.totalCount,
          id: articleId,
          title: result.title,
          images: result.images,
          imageErrors: result.imageErrors,
        }),
      );
    } catch (error) {
      stats.failed += 1;
      consecutiveFailures += 1;
      stats.errors.push({
        id: articleId,
        url: `https://m.blog.naver.com/${blogId}/${logNo}`,
        message: error.message,
        at: new Date().toISOString(),
      });
      console.error(JSON.stringify({ status: "failed", id: articleId, message: error.message }));
      if (stopAfterConsecutiveFailures && consecutiveFailures >= stopAfterConsecutiveFailures) {
        stats.done = true;
        stats.updatedAt = new Date().toISOString();
        await writeJob();
        printStats("stopped after consecutive failures");
        process.exit(0);
      }
    }

    stats.updatedAt = new Date().toISOString();
    await writeJob();
    await sleep(delayMs);
  }

  page += 1;
}

stats.done = true;
stats.updatedAt = new Date().toISOString();
await writeJob();
printStats("done");

async function savePost({ blogId, logNo, listItem }) {
  const articleId = `naver-${blogId}-${logNo}`;
  const url = `https://m.blog.naver.com/${blogId}/${logNo}`;
  const canonicalUrl = `https://blog.naver.com/${blogId}/${logNo}`;
  const resp = await fetch(url, {
    headers: {
      "user-agent": DEFAULT_UA,
      accept: "text/html",
      referer: `https://m.blog.naver.com/PostList.naver?blogId=${blogId}`,
    },
  });
  if (!resp.ok) {
    throw new Error(`post fetch failed HTTP ${resp.status}`);
  }

  const html = await resp.text();
  if (!html.includes("se-main-container")) {
    throw new Error("post body marker not found");
  }

  const { title, author, publishedAtText, category } = parseHeader(html, listItem);

  const main = extractMainContainer(html);
  if (!main) {
    throw new Error("main container extraction failed");
  }

  const { mdParts, images } = parseBody(main, articleId);

  let downloaded = [];
  if (downloadImages) {
    downloaded = await downloadPostImages({ articleId, images, url });
  } else {
    downloaded = images.map((image, index) => ({
      ...image,
      file: null,
      placeholder: `assets/${articleId}/image-${String(index + 1).padStart(2, "0")}`,
    }));
  }

  let body = mdParts.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
  for (const image of downloaded) {
    if (image.file) {
      const placeholder = basename(image.file).replace(/\.[^.]+$/, "");
      body = body.replaceAll(`assets/${articleId}/${placeholder}`, image.file);
    }
  }

  const fetchedAt = new Date().toISOString();
  const contentHash = createHash("sha256").update(body).digest("hex");
  const imageErrors = downloaded.filter((image) => image.error).length;
  const metadata = {
    id: articleId,
    source: "naver_blog",
    sourceReliability: "scraped",
    ingestMode: "crawl",
    fetchStatus: "ok",
    author,
    blogId,
    logNo,
    title,
    category,
    url,
    canonicalUrl,
    publishedAtText,
    fetchedAt,
    contentHash,
    rawHtmlPath: `raw/${articleId}.html`,
    markdownPath: `articles/${articleId}.md`,
    imageCount: downloaded.length,
    imageDownloadEnabled: downloadImages,
    images: downloaded,
    listItem,
  };

  const frontmatter = [
    "---",
    `id: ${JSON.stringify(articleId)}`,
    `source: ${JSON.stringify("naver_blog")}`,
    `author: ${JSON.stringify(author)}`,
    `title: ${JSON.stringify(title)}`,
    `url: ${JSON.stringify(canonicalUrl)}`,
    `publishedAtText: ${JSON.stringify(publishedAtText)}`,
    `fetchedAt: ${JSON.stringify(fetchedAt)}`,
    `contentHash: ${JSON.stringify(contentHash)}`,
    "---",
    "",
  ].join("\n");

  const markdown = `${frontmatter}# ${title}\n\n${body}\n`;
  const rawPath = join(dirs.raw, `${articleId}.html`);
  const rawTempPath = `${rawPath}.${process.pid}-${Date.now()}.tmp`;
  await writeFile(rawTempPath, html, "utf8");
  try {
    await writeFile(join(dirs.articles, `${articleId}.md`), markdown, "utf8");
    await writeFile(join(dirs.metadata, `${articleId}.json`), JSON.stringify(metadata, null, 2), "utf8");
    await upsertIndex({
      id: articleId,
      title,
      author,
      source: "naver_blog",
      url: canonicalUrl,
      publishedAtText,
      publishedAt: listItem.addDate ? new Date(listItem.addDate).toISOString() : "",
      fetchedAt,
      contentHash,
      markdownPath: `articles/${articleId}.md`,
      metadataPath: `metadata/${articleId}.json`,
      imageCount: downloaded.length,
    });
    await rename(rawTempPath, rawPath);
  } finally {
    await unlink(rawTempPath).catch(() => {});
  }

  return { title, images: downloaded.length, imageErrors };
}

async function fetchPostList(blogId, page, itemCount) {
  const url = new URL(`https://m.blog.naver.com/api/blogs/${blogId}/post-list`);
  url.searchParams.set("categoryNo", "0");
  url.searchParams.set("itemCount", String(itemCount));
  url.searchParams.set("page", String(page));
  const resp = await fetch(url, {
    headers: {
      "user-agent": DEFAULT_UA,
      accept: "application/json",
      referer: `https://m.blog.naver.com/PostList.naver?blogId=${blogId}`,
    },
  });
  if (!resp.ok) {
    throw new Error(`post list failed HTTP ${resp.status}`);
  }
  const payload = await resp.json();
  if (!payload.isSuccess) {
    throw new Error(payload.error?.message || "post list API returned failure");
  }
  return {
    items: payload.result?.items || [],
    totalCount: Number(payload.result?.totalCount || 0),
    page: Number(payload.result?.page || page),
  };
}

async function downloadPostImages({ articleId, images, url }) {
  const assetDir = join(dirs.assetsRoot, articleId);
  await mkdir(assetDir, { recursive: true });
  const downloaded = [];
  for (let i = 0; i < images.length; i += 1) {
    const image = images[i];
    try {
      const resp = await fetch(image.src, {
        headers: {
          "user-agent": DEFAULT_UA,
          referer: url,
        },
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const contentType = resp.headers.get("content-type") || "";
      let ext = contentType.includes("png")
        ? ".png"
        : contentType.includes("jpeg") || contentType.includes("jpg")
          ? ".jpg"
          : extname(new URL(image.src).pathname) || ".img";
      if (ext === ".jpeg") {
        ext = ".jpg";
      }
      const filename = `image-${String(i + 1).padStart(2, "0")}${ext}`;
      const buf = Buffer.from(await resp.arrayBuffer());
      await writeFile(join(assetDir, filename), buf);
      downloaded.push({
        ...image,
        file: `assets/${articleId}/${filename}`,
        bytes: buf.length,
        contentType,
      });
    } catch (error) {
      downloaded.push({ ...image, error: error.message });
    }
    await sleep(imageDelayMs);
  }
  return downloaded;
}

async function upsertIndex(row) {
  const indexPath = join(dirs.root, "index.jsonl");
  let rows = [];
  try {
    rows = (await readFile(indexPath, "utf8"))
      .split("\n")
      .filter(Boolean)
      .filter((line) => {
        try {
          return JSON.parse(line).id !== row.id;
        } catch {
          return false;
        }
      });
  } catch {
    rows = [];
  }
  rows.push(JSON.stringify(row));
  await writeFile(indexPath, `${rows.join("\n")}\n`, "utf8");
}

async function writeJob() {
  await writeFile(jobPath, JSON.stringify(stats, null, 2), "utf8");
}

function parseArgs(raw) {
  const parsed = { _: [] };
  for (let i = 0; i < raw.length; i += 1) {
    const item = raw[i];
    if (!item.startsWith("--")) {
      parsed._.push(item);
      continue;
    }
    const key = item.slice(2);
    const next = raw[i + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
      continue;
    }
    parsed[key] = next;
    i += 1;
  }
  return parsed;
}

function positional(index) {
  return args._?.[index];
}

function parsePositiveInt(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return Math.floor(parsed);
}

function parseSince(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const timestamp = Date.parse(raw);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

async function fileExists(path) {
  try {
    await readFile(path);
    return true;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function printStats(status) {
  console.log(JSON.stringify({ status, ...stats }, null, 2));
}
