import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { basename, extname, join } from "node:path";

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

  await writeFile(join(dirs.raw, `${articleId}.html`), html, "utf8");

  const title =
    firstMatch(html, /<title>(.*?)\s*:\s*네이버 블로그<\/title>/is) ||
    metaProperty(html, "og:title") ||
    decodeHtml(listItem.titleWithInspectMessage || listItem.title || "Untitled");
  const author =
    firstMatch(html, /<strong class="ell">([\s\S]*?)<\/strong>/is) ||
    metaProperty(html, "naverblog:nickname") ||
    listItem.nickName ||
    "";
  const publishedAtText = firstMatch(html, /<p class="blog_date">\s*([\s\S]*?)\s*<\/p>/i).replace(
    /\s+/g,
    " ",
  );
  const category = firstMatch(
    html,
    /<div class="blog_category">\s*<a[^>]*>([\s\S]*?)<\/a>/is,
  );

  const main =
    html.match(
      /<div class="se-main-container">([\s\S]*?)<\/div>\s*<\/div>\s*<\/div>\s*\n\s*\t\t\n\s*\t\t\n\s*\t<\/div>/,
    )?.[1] ?? html.match(/<div class="se-main-container">([\s\S]*?)<div class="social_plugin_property"/i)?.[1];
  if (!main) {
    throw new Error("main container extraction failed");
  }

  const components = [
    ...main.matchAll(
      /<div class="se-component ([^" ]+)[\s\S]*?(?=<div class="se-component |\s*<\/div>\s*<\/div>\s*<\/div>\s*$)/g,
    ),
  ].map((match) => match[0]);
  const images = [];
  const mdParts = [];

  for (const component of components) {
    if (component.includes("se-component se-text") || component.includes("se-module se-module-text")) {
      const paragraphs = [...component.matchAll(/<p\b[^>]*class="se-text-paragraph[^"]*"[^>]*>([\s\S]*?)<\/p>/gi)]
        .map((match) => anchorAwareText(match[1]))
        .filter(Boolean);
      if (paragraphs.length) {
        mdParts.push(paragraphs.join("\n\n"));
      }
      continue;
    }

    if (component.includes("se-component se-oglink")) {
      const link =
        component.match(/<a\b[^>]*href="([^"]+)"[^>]*class="se-oglink-info"/i)?.[1] ||
        component.match(/<a\b[^>]*href="([^"]+)"/i)?.[1] ||
        "";
      const ogTitle = stripTags(
        component.match(/<strong class="se-oglink-title">([\s\S]*?)<\/strong>/i)?.[1] ?? "",
      );
      const summary = stripTags(
        component.match(/<p class="se-oglink-summary">([\s\S]*?)<\/p>/i)?.[1] ?? "",
      );
      if (link || ogTitle) {
        mdParts.push(
          `> 링크: ${ogTitle || link}${link ? `\n> ${decodeHtml(link)}` : ""}${summary ? `\n> ${summary}` : ""}`,
        );
      }
      continue;
    }

    if (component.includes("se-component se-image")) {
      const lazy = decodeHtml(component.match(/data-lazy-src="([^"]+)"/i)?.[1] ?? "");
      const srcFromData = decodeHtml(component.match(/"src"\s*:\s*"([^"]+)"/i)?.[1] ?? "");
      const src = lazy || srcFromData;
      if (!src) {
        continue;
      }
      images.push({ src });
      const n = images.length;
      const caption = stripTags(
        component.match(/<div class="se-module se-module-text se-caption">([\s\S]*?)<\/div>/i)?.[1] ?? "",
      );
      mdParts.push(
        `![image ${n}](assets/${articleId}/image-${String(n).padStart(2, "0")})${
          caption ? `\n\n_${caption}_` : ""
        }`,
      );
    }
  }

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

function decodeHtml(value = "") {
  const named = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " ", "#034": "\"", "#039": "'" };
  return String(value)
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, decimal) => String.fromCodePoint(parseInt(decimal, 10)))
    .replace(/&([a-zA-Z]+|#034|#039);/g, (match, name) => named[name] ?? match);
}

function stripTags(value = "") {
  return decodeHtml(value.replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]+>/g, ""))
    .replace(/\u200b/g, "")
    .trim();
}

function anchorAwareText(html) {
  const withLinks = html.replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi, (match, attrs, inner) => {
    const href = attr(attrs, "href");
    const text = stripTags(inner);
    return href && text ? `[${text}](${href})` : text;
  });
  return stripTags(withLinks).replace(/\s+/g, " ").trim();
}

function attr(tag, name) {
  const match = tag.match(new RegExp(`${name}=["']([^"']*)["']`, "i"));
  return match ? decodeHtml(match[1]) : "";
}

function firstMatch(html, regex) {
  return stripTags(html.match(regex)?.[1] ?? "");
}

function metaProperty(html, prop) {
  const match = html.match(
    new RegExp(`<meta[^>]+property=["']${prop.replace(/:/g, ":")}["'][^>]+content=["']([^"']*)["'][^>]*>`, "i"),
  );
  return decodeHtml(match?.[1] ?? "");
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
