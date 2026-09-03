// 블로거 코퍼스 레지스트리 — 웹 탭과 크롤러가 공유하는 블로그 목록/통계.
// 저장 규칙은 docs/naver-blog-corpus.md, 1차 설계는 docs/2026-07-08-blogger-tab-phase1-design.md.
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

export const SEED_BLOGS = [
  { id: "ranto28", name: "메르" },
  { id: "yminsong", name: "와이민" },
  { id: "ionia17", name: "James Lee Advisors" },
  { id: "jakojako", name: "재콩" },
  { id: "tosoha1", name: "농구천재" },
  { id: "mistergray", name: "회색 인간" },
  { id: "sungdory", name: "승도리" },
  { id: "shinook430", name: "북회귀선" },
  { id: "crush212121", name: "체리형부" },
  { id: "jyt4159", name: "초대현대농업" },
  { id: "cybermw", name: "좋은친구" },
  { id: "zzayofactory", name: "미생에서 완생으로" },
  { id: "new10yrs", name: "멘탈거북" },
  { id: "furmea21", name: "드리머" },
  { id: "morgoth", name: "와시즈" },
];

const NAVER_MOBILE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";

export function isValidBlogId(id) {
  return /^[a-z0-9_-]{2,30}$/i.test(String(id || ""));
}

export function normalizeCrawlSince(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const timestamp = Date.parse(raw);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

function publishedAtOf(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  const timestamp = Number.isFinite(numeric) && numeric > 0 ? numeric : Date.parse(String(value));
  if (!Number.isFinite(timestamp)) {
    return null;
  }
  const date = new Date(timestamp);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export function hasNewEligiblePost(preview, newestLocal, crawlSince) {
  const newest = preview?.items?.[0];
  if (!newest || Number(newest.logNo) <= Number(newestLocal || 0)) {
    return false;
  }
  const boundary = Date.parse(crawlSince || "");
  const published = Date.parse(newest.publishedAt || "");
  if (Number.isFinite(boundary) && Number.isFinite(published) && published < boundary) {
    return false;
  }
  return true;
}

function registryPath(corpusRoot) {
  return join(corpusRoot, "blogs.json");
}

const registryMutationQueues = new Map();

async function mutateRegistry(corpusRoot, mutate) {
  const path = registryPath(corpusRoot);
  const previous = registryMutationQueues.get(path) || Promise.resolve();
  const operation = previous.catch(() => {}).then(async () => {
    const registry = await loadRegistry(corpusRoot);
    const result = await mutate(registry);
    await saveRegistry(corpusRoot, registry);
    return result;
  });
  registryMutationQueues.set(path, operation);
  try {
    return await operation;
  } finally {
    if (registryMutationQueues.get(path) === operation) {
      registryMutationQueues.delete(path);
    }
  }
}

export async function loadRegistry(corpusRoot) {
  try {
    const registry = JSON.parse(await readFile(registryPath(corpusRoot), "utf8"));
    if (Array.isArray(registry.blogs)) {
      return registry;
    }
  } catch {
    // 파일 없음/깨짐 → 시드
  }
  const registry = {
    blogs: SEED_BLOGS.map((blog) => ({
      ...blog,
      source: "naver",
      tags: [],
      active: true,
      addedAt: new Date().toISOString(),
    })),
  };
  await saveRegistry(corpusRoot, registry);
  return registry;
}

export async function saveRegistry(corpusRoot, registry) {
  await mkdir(corpusRoot, { recursive: true });
  const path = registryPath(corpusRoot);
  const temporaryPath = `${path}.${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf8");
  await rename(temporaryPath, path);
}

export async function upsertBlog(corpusRoot, { id, name, source = "naver", crawlSince }) {
  return mutateRegistry(corpusRoot, (registry) => {
    let blog = registry.blogs.find((entry) => entry.id === id && entry.source === source);
    if (blog) {
      blog.active = true;
      if (name) {
        blog.name = name;
      }
      if (crawlSince !== undefined) {
        blog.crawlSince = crawlSince;
      }
    } else {
      blog = {
        id,
        name: name || id,
        source,
        tags: [],
        active: true,
        addedAt: new Date().toISOString(),
      };
      if (crawlSince !== undefined) {
        blog.crawlSince = crawlSince;
      }
      registry.blogs.push(blog);
    }
    return blog;
  });
}

export async function deactivateBlog(corpusRoot, id) {
  return mutateRegistry(corpusRoot, (registry) => {
    const blog = registry.blogs.find((entry) => entry.id === id);
    if (!blog) {
      return false;
    }
    blog.active = false;
    return true;
  });
}

export async function setBlogFlags(corpusRoot, id, flags) {
  return mutateRegistry(corpusRoot, (registry) => {
    const blog = registry.blogs.find((entry) => entry.id === id);
    if (!blog) {
      return false;
    }
    Object.assign(blog, flags);
    return true;
  });
}

function blogRoot(corpusRoot, blog) {
  return join(corpusRoot, blog.source || "naver", blog.id);
}

function logNoOf(row) {
  const match = /-(\d+)$/.exec(String(row.id || ""));
  return match ? Number(match[1]) : 0;
}

// 정렬 기준: 게시 시각 우선, 없으면 글 번호. 글 번호는 초안 시점에 발급되어
// 실제 게시 순서와 어긋날 수 있다 (예: 메르 — 미리 써두고 나중에 게시).
function sortKeyOf(row) {
  const ts = Date.parse(row.publishedAt || "");
  return Number.isFinite(ts) ? ts : logNoOf(row);
}

async function readIndex(corpusRoot, blog) {
  try {
    const text = await readFile(join(blogRoot(corpusRoot, blog), "index.jsonl"), "utf8");
    const rows = [];
    for (const line of text.split("\n")) {
      if (!line) {
        continue;
      }
      try {
        rows.push(JSON.parse(line));
      } catch {
        // 깨진 줄은 통계에서 제외
      }
    }
    return rows;
  } catch {
    return [];
  }
}

async function latestJob(corpusRoot, blog) {
  const jobsDir = join(blogRoot(corpusRoot, blog), "jobs");
  try {
    const files = (await readdir(jobsDir)).filter((file) => file.endsWith(".json")).sort();
    if (!files.length) {
      return null;
    }
    return JSON.parse(await readFile(join(jobsDir, files[files.length - 1]), "utf8"));
  } catch {
    return null;
  }
}

async function readLastCheck(corpusRoot, blog) {
  try {
    return JSON.parse(await readFile(join(blogRoot(corpusRoot, blog), "last-check.json"), "utf8"));
  } catch {
    return null;
  }
}

export async function writeLastCheck(corpusRoot, blog, data) {
  const root = blogRoot(corpusRoot, blog);
  await mkdir(root, { recursive: true });
  await writeFile(join(root, "last-check.json"), `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

export async function blogStats(corpusRoot, blog) {
  const rows = await readIndex(corpusRoot, blog);
  let latest = null;
  for (const row of rows) {
    if (!latest || sortKeyOf(row) > sortKeyOf(latest)) {
      latest = row;
    }
  }
  return {
    count: rows.length,
    latest: latest
      ? {
          id: latest.id,
          title: latest.title,
          url: latest.url,
          publishedAtText: latest.publishedAtText || "",
          fetchedAt: latest.fetchedAt || "",
        }
      : null,
    lastJob: await latestJob(corpusRoot, blog),
    lastCheck: await readLastCheck(corpusRoot, blog),
  };
}

export async function listPosts(corpusRoot, { blogIds, offset = 0, limit = 50, withSummaries = false }) {
  const rows = [];
  for (const blogId of blogIds) {
    const blogRows = await readIndex(corpusRoot, { id: blogId, source: "naver" });
    for (const row of blogRows) {
      rows.push({ ...row, blogId });
    }
  }
  rows.sort((first, second) => sortKeyOf(second) - sortKeyOf(first) || logNoOf(second) - logNoOf(first));
  const posts = rows.slice(offset, offset + limit);
  if (withSummaries) {
    // 보이는 페이지만 요약 파일을 읽는다 (글별 summaries/<id>.json)
    for (const post of posts) {
      try {
        const raw = await readFile(
          join(corpusRoot, "naver", post.blogId, "summaries", `${post.id}.json`),
          "utf8",
        );
        const record = JSON.parse(raw);
        post.summary = record.summary || null;
        post.summaryReason = record.reason || null;
        post.summaryType = record.type || null;
      } catch {
        post.summary = null;
        post.summaryReason = null;
        post.summaryType = null;
      }
    }
  }
  return {
    total: rows.length,
    posts,
  };
}

export async function readPost(corpusRoot, blogId, articleId) {
  if (!isValidBlogId(blogId) || !new RegExp(`^naver-${blogId}-\\d+$`).test(String(articleId))) {
    throw new Error("잘못된 글 id");
  }
  const root = join(corpusRoot, "naver", blogId);
  const markdown = await readFile(join(root, "articles", `${articleId}.md`), "utf8");
  let metadata = null;
  try {
    metadata = JSON.parse(await readFile(join(root, "metadata", `${articleId}.json`), "utf8"));
  } catch {
    metadata = null;
  }
  return { markdown, metadata };
}

// 네이버 목록 API로 블로그 ID 검증 + 최신 글 미리보기. referer 없으면 실패한다 (2026-07-08 실측).
export async function fetchNaverPreview(blogId) {
  const url = new URL(`https://m.blog.naver.com/api/blogs/${blogId}/post-list`);
  url.searchParams.set("categoryNo", "0");
  url.searchParams.set("itemCount", "5");
  url.searchParams.set("page", "1");
  const resp = await fetch(url, {
    headers: {
      "user-agent": NAVER_MOBILE_UA,
      accept: "application/json",
      referer: `https://m.blog.naver.com/PostList.naver?blogId=${blogId}`,
    },
    signal: AbortSignal.timeout(10_000),
  });
  if (!resp.ok) {
    throw new Error(`목록 API HTTP ${resp.status}`);
  }
  const payload = await resp.json();
  if (!payload.isSuccess) {
    throw new Error(payload.error?.message || "블로그를 찾을 수 없습니다");
  }
  const items = payload.result?.items || [];
  return {
    totalCount: Number(payload.result?.totalCount || 0) || items.length,
    items: items.map((item) => {
      const publishedAt = publishedAtOf(item.addDate);
      return {
        logNo: String(item.logNo),
        title: item.titleWithInspectMessage || item.title || "",
        nickName: item.nickName || "",
        ...(publishedAt ? { publishedAt } : {}),
      };
    }),
  };
}
