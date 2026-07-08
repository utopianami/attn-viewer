// 블로거 탭 API — 레지스트리 CRUD + 백필/증분 수집 job + 새 글 감지 스케줄러.
// 설계: docs/2026-07-08-blogger-tab-phase1-design.md
// 코퍼스는 로그인 계정과 무관한 공유 자원 (BLOG_CORPUS_USER, 기본 ryze_yn).
import { Router } from "express";
import { spawn } from "node:child_process";
import { join } from "node:path";

import {
  loadRegistry,
  upsertBlog,
  deactivateBlog,
  setBlogFlags,
  blogStats,
  listPosts,
  readPost,
  writeLastCheck,
  fetchNaverPreview,
  isValidBlogId,
} from "./blogs.mjs";

export function createBlogsRouter({ corpusRoot, rootDir, requireAuth }) {
  const runningJobs = new Map(); // blogId → { mode, startedAt }

  function startCrawlJob(blogId, { incremental }) {
    if (runningJobs.has(blogId)) {
      return { started: false, reason: "already-running" };
    }
    const corpusUser = process.env.BLOG_CORPUS_USER || "ryze_yn";
    const args = ["scripts/crawl_naver_blog.mjs", "--blogId", blogId, "--user", corpusUser];
    if (incremental) {
      args.push("--stopOnKnown", "10");
    }
    const child = spawn("node", args, { cwd: rootDir, stdio: "ignore" });
    runningJobs.set(blogId, {
      mode: incremental ? "refresh" : "backfill",
      startedAt: new Date().toISOString(),
    });
    child.on("exit", async () => {
      runningJobs.delete(blogId);
      try {
        const stats = await blogStats(corpusRoot, { id: blogId, source: "naver" });
        const job = stats.lastJob;
        if (job && job.saved > 0) {
          await setBlogFlags(corpusRoot, blogId, { fetchBlocked: false });
        } else if (job && job.discovered > 0 && job.saved === 0 && job.failed >= job.discovered / 2) {
          // 목록은 보이는데 본문이 전부 실패 → 이웃공개/제한 블로그 (ionia17·zzayofactory 유형)
          await setBlogFlags(corpusRoot, blogId, { fetchBlocked: true });
        }
      } catch {
        // 플래그 갱신 실패는 치명적이지 않다
      }
    });
    child.on("error", () => {
      runningJobs.delete(blogId);
    });
    return { started: true };
  }

  const router = Router();
  router.use(requireAuth);

  router.get("/", async (_req, res) => {
    try {
      const registry = await loadRegistry(corpusRoot);
      const dayAgo = Date.now() - 24 * 3600 * 1000;
      const blogs = [];
      for (const blog of registry.blogs) {
        const stats = await blogStats(corpusRoot, blog);
        blogs.push({
          ...blog,
          count: stats.count,
          latest: stats.latest,
          lastCheck: stats.lastCheck,
          runningJob: runningJobs.get(blog.id) || null,
          lastJob: stats.lastJob
            ? {
                discovered: stats.lastJob.discovered,
                saved: stats.lastJob.saved,
                failed: stats.lastJob.failed,
                done: stats.lastJob.done,
                updatedAt: stats.lastJob.updatedAt,
              }
            : null,
          recentCount: 0,
        });
      }
      // 새 글 뱃지 = 최근 24시간에 수집된 글 수
      for (const blog of blogs) {
        if (!blog.count) {
          continue;
        }
        const { posts } = await listPosts(corpusRoot, { blogIds: [blog.id], offset: 0, limit: 30 });
        blog.recentCount = posts.filter((post) => Date.parse(post.fetchedAt || "") > dayAgo).length;
      }
      res.json({ ok: true, blogs });
    } catch (error) {
      res.status(500).json({ ok: false, error: String(error?.message || error) });
    }
  });

  router.post("/", async (req, res) => {
    const blogId = String(req.body?.blogId || "").trim();
    const name = String(req.body?.name || "").trim();
    if (!isValidBlogId(blogId)) {
      res.status(400).json({ ok: false, error: "블로그 ID 형식이 잘못됐습니다 (영문/숫자/-/_ 2~30자)" });
      return;
    }
    try {
      const preview = await fetchNaverPreview(blogId);
      if (!preview.items.length) {
        res.status(422).json({ ok: false, error: "블로그는 있지만 공개 글이 없습니다", preview });
        return;
      }
      const blog = await upsertBlog(corpusRoot, {
        id: blogId,
        name: name || preview.items[0].nickName || blogId,
      });
      const job = startCrawlJob(blogId, { incremental: false });
      res.status(202).json({ ok: true, blog, preview, job });
    } catch (error) {
      res.status(422).json({ ok: false, error: `블로그 확인 실패: ${String(error?.message || error)}` });
    }
  });

  router.delete("/:blogId", async (req, res) => {
    const { blogId } = req.params;
    if (!isValidBlogId(blogId)) {
      res.status(400).json({ ok: false, error: "잘못된 블로그 ID" });
      return;
    }
    const found = await deactivateBlog(corpusRoot, blogId);
    if (!found) {
      res.status(404).json({ ok: false, error: "등록되지 않은 블로그" });
      return;
    }
    res.json({ ok: true });
  });

  router.get("/posts", async (req, res) => {
    try {
      const registry = await loadRegistry(corpusRoot);
      const active = registry.blogs.filter((blog) => blog.active).map((blog) => blog.id);
      const offset = Math.max(0, Number(req.query.offset) || 0);
      const limit = Math.min(200, Math.max(1, Number(req.query.limit) || 50));
      const result = await listPosts(corpusRoot, { blogIds: active, offset, limit });
      res.json({ ok: true, ...result });
    } catch (error) {
      res.status(500).json({ ok: false, error: String(error?.message || error) });
    }
  });

  router.post("/:blogId/refresh", async (req, res) => {
    const { blogId } = req.params;
    if (!isValidBlogId(blogId)) {
      res.status(400).json({ ok: false, error: "잘못된 블로그 ID" });
      return;
    }
    res.status(202).json({ ok: true, job: startCrawlJob(blogId, { incremental: true }) });
  });

  router.get("/:blogId/posts", async (req, res) => {
    const { blogId } = req.params;
    if (!isValidBlogId(blogId)) {
      res.status(400).json({ ok: false, error: "잘못된 블로그 ID" });
      return;
    }
    try {
      const offset = Math.max(0, Number(req.query.offset) || 0);
      const limit = Math.min(200, Math.max(1, Number(req.query.limit) || 50));
      const result = await listPosts(corpusRoot, { blogIds: [blogId], offset, limit });
      res.json({ ok: true, ...result });
    } catch (error) {
      res.status(500).json({ ok: false, error: String(error?.message || error) });
    }
  });

  router.get("/:blogId/posts/:articleId", async (req, res) => {
    try {
      const post = await readPost(corpusRoot, req.params.blogId, req.params.articleId);
      res.json({ ok: true, ...post });
    } catch (error) {
      res.status(404).json({ ok: false, error: "글을 찾을 수 없습니다" });
    }
  });

  // 새 글 감지 — active && !fetchBlocked 블로그를 순차 확인, 새 logNo가 있으면 증분 수집.
  async function checkNewPosts() {
    let registry;
    try {
      registry = await loadRegistry(corpusRoot);
    } catch {
      return;
    }
    for (const blog of registry.blogs) {
      if (!blog.active || blog.fetchBlocked || runningJobs.has(blog.id)) {
        continue;
      }
      try {
        const [preview, stats] = [
          await fetchNaverPreview(blog.id),
          await blogStats(corpusRoot, blog),
        ];
        const newestRemote = preview.items.length ? Number(preview.items[0].logNo) : 0;
        const newestLocal = stats.latest ? Number(/-(\d+)$/.exec(stats.latest.id)?.[1] || 0) : 0;
        const hasNew = newestRemote > newestLocal;
        await writeLastCheck(corpusRoot, blog, {
          checkedAt: new Date().toISOString(),
          newestRemote,
          newestLocal,
          hasNew,
        });
        if (hasNew) {
          startCrawlJob(blog.id, { incremental: true });
        }
      } catch (error) {
        await writeLastCheck(corpusRoot, blog, {
          checkedAt: new Date().toISOString(),
          error: String(error?.message || error),
        }).catch(() => {});
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }

  function startScheduler() {
    const intervalMs = Math.max(
      5 * 60 * 1000,
      Number(process.env.BLOG_CHECK_INTERVAL_MS) || 30 * 60 * 1000,
    );
    setInterval(() => {
      checkNewPosts().catch(() => {});
    }, intervalMs).unref();
    // 서버 시작 2분 뒤 첫 확인 (부팅 직후 트래픽 분산)
    setTimeout(() => {
      checkNewPosts().catch(() => {});
    }, 2 * 60 * 1000).unref();
  }

  return { router, startScheduler, checkNewPosts };
}
