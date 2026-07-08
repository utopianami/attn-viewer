import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  SEED_BLOGS,
  loadRegistry,
  upsertBlog,
  deactivateBlog,
  setBlogFlags,
  blogStats,
  listPosts,
  readPost,
  isValidBlogId,
} from "./blogs.mjs";

async function makeCorpus() {
  return mkdtemp(join(tmpdir(), "blogs-test-"));
}

async function seedPosts(corpusRoot, blogId, rows) {
  const root = join(corpusRoot, "naver", blogId);
  await mkdir(join(root, "articles"), { recursive: true });
  await mkdir(join(root, "metadata"), { recursive: true });
  const lines = [];
  for (const row of rows) {
    const id = `naver-${blogId}-${row.logNo}`;
    lines.push(
      JSON.stringify({
        id,
        title: row.title,
        author: row.author || blogId,
        source: "naver_blog",
        url: `https://blog.naver.com/${blogId}/${row.logNo}`,
        publishedAtText: row.publishedAtText || "2026. 7. 8.",
        fetchedAt: row.fetchedAt || "2026-07-08T00:00:00.000Z",
        markdownPath: `articles/${id}.md`,
        metadataPath: `metadata/${id}.json`,
      }),
    );
    await writeFile(join(root, "articles", `${id}.md`), `# ${row.title}\n\nbody of ${id}\n`, "utf8");
    await writeFile(
      join(root, "metadata", `${id}.json`),
      JSON.stringify({ id, title: row.title }),
      "utf8",
    );
  }
  await writeFile(join(root, "index.jsonl"), `${lines.join("\n")}\n`, "utf8");
}

test("loadRegistry seeds 15 blogs when file is missing", async () => {
  const corpusRoot = await makeCorpus();
  const registry = await loadRegistry(corpusRoot);
  assert.equal(registry.blogs.length, SEED_BLOGS.length);
  assert.equal(SEED_BLOGS.length, 15);
  assert.ok(registry.blogs.every((b) => b.active));
  assert.ok(registry.blogs.some((b) => b.id === "ranto28" && b.name === "메르"));
  // second load reads the persisted file, not re-seed
  const again = await loadRegistry(corpusRoot);
  assert.equal(again.blogs.length, 15);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("upsertBlog adds a new blog and reactivates a removed one", async () => {
  const corpusRoot = await makeCorpus();
  await loadRegistry(corpusRoot);
  const added = await upsertBlog(corpusRoot, { id: "hodolry", name: "호돌이" });
  assert.equal(added.active, true);
  let registry = await loadRegistry(corpusRoot);
  assert.equal(registry.blogs.length, 16);

  assert.equal(await deactivateBlog(corpusRoot, "hodolry"), true);
  registry = await loadRegistry(corpusRoot);
  assert.equal(registry.blogs.find((b) => b.id === "hodolry").active, false);

  const back = await upsertBlog(corpusRoot, { id: "hodolry", name: "호돌이" });
  assert.equal(back.active, true);
  registry = await loadRegistry(corpusRoot);
  assert.equal(registry.blogs.length, 16);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("deactivateBlog returns false for unknown id", async () => {
  const corpusRoot = await makeCorpus();
  await loadRegistry(corpusRoot);
  assert.equal(await deactivateBlog(corpusRoot, "nope"), false);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("setBlogFlags merges flags", async () => {
  const corpusRoot = await makeCorpus();
  await loadRegistry(corpusRoot);
  await setBlogFlags(corpusRoot, "ionia17", { fetchBlocked: true });
  const registry = await loadRegistry(corpusRoot);
  assert.equal(registry.blogs.find((b) => b.id === "ionia17").fetchBlocked, true);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("blogStats counts posts and finds latest by logNo", async () => {
  const corpusRoot = await makeCorpus();
  await seedPosts(corpusRoot, "testblog", [
    { logNo: 100, title: "old post" },
    { logNo: 300, title: "newest post" },
    { logNo: 200, title: "middle post" },
  ]);
  const stats = await blogStats(corpusRoot, { id: "testblog", source: "naver" });
  assert.equal(stats.count, 3);
  assert.equal(stats.latest.title, "newest post");
  await rm(corpusRoot, { recursive: true, force: true });
});

test("blogStats handles missing corpus dir", async () => {
  const corpusRoot = await makeCorpus();
  const stats = await blogStats(corpusRoot, { id: "empty", source: "naver" });
  assert.equal(stats.count, 0);
  assert.equal(stats.latest, null);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("listPosts merges blogs sorted by logNo desc with paging", async () => {
  const corpusRoot = await makeCorpus();
  await seedPosts(corpusRoot, "aaa", [
    { logNo: 100, title: "aaa-100" },
    { logNo: 400, title: "aaa-400" },
  ]);
  await seedPosts(corpusRoot, "bbb", [{ logNo: 300, title: "bbb-300" }]);
  const all = await listPosts(corpusRoot, { blogIds: ["aaa", "bbb"], offset: 0, limit: 10 });
  assert.deepEqual(
    all.posts.map((p) => p.title),
    ["aaa-400", "bbb-300", "aaa-100"],
  );
  assert.equal(all.total, 3);

  const page = await listPosts(corpusRoot, { blogIds: ["aaa", "bbb"], offset: 1, limit: 1 });
  assert.deepEqual(page.posts.map((p) => p.title), ["bbb-300"]);

  const only = await listPosts(corpusRoot, { blogIds: ["aaa"], offset: 0, limit: 10 });
  assert.equal(only.total, 2);
  await rm(corpusRoot, { recursive: true, force: true });
});

test("readPost returns markdown and rejects bad article ids", async () => {
  const corpusRoot = await makeCorpus();
  await seedPosts(corpusRoot, "testblog", [{ logNo: 100, title: "one" }]);
  const post = await readPost(corpusRoot, "testblog", "naver-testblog-100");
  assert.match(post.markdown, /body of naver-testblog-100/);
  assert.equal(post.metadata.title, "one");

  await assert.rejects(() => readPost(corpusRoot, "testblog", "../../etc/passwd"));
  await assert.rejects(() => readPost(corpusRoot, "testblog", "naver-other-100"));
  await rm(corpusRoot, { recursive: true, force: true });
});

test("isValidBlogId accepts naver ids and rejects junk", () => {
  assert.equal(isValidBlogId("ranto28"), true);
  assert.equal(isValidBlogId("santa_croce"), true);
  assert.equal(isValidBlogId("crush212121"), true);
  assert.equal(isValidBlogId(""), false);
  assert.equal(isValidBlogId("has space"), false);
  assert.equal(isValidBlogId("a/b"), false);
  assert.equal(isValidBlogId("x".repeat(40)), false);
});
