// 블로거 탭 — 블로그 추가/제거·수집 상태·글 열람 (docs/2026-07-08-blogger-tab-phase1-design.md)
// index.html의 전역(renderMarkdown, escapeHtml)을 재사용한다. window.AttnBlogger.load()가 진입점.
// 하위 화면은 해시로 관리 — #blogger(블로그) / #blogger-posts[-blogId](글 목록) / #blogger-post-<articleId>(본문).
// index.html의 parseRouteHash/getRouteHash가 #blogger- 접두 해시를 blogger 뷰로 라우팅해준다.
(() => {
  const state = {
    blogs: [],
    posts: [],
    postsTotal: 0,
    filter: "",
    offset: 0,
    limit: 30,
    subview: "blogs", // blogs | posts | post
    post: null,
    blogsLoaded: false,
    postsKey: "", // 어떤 필터로 불러온 목록인지 (필터 바뀌면 다시 로드)
    feedback: "",
  };
  let pollTimer = null;

  const style = document.createElement("style");
  style.textContent = `
    .blogger-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
    .blogger-head h2 { margin: 0; font-size: 18px; }
    .blogger-tabs { display: inline-flex; gap: 6px; }
    .blogger-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }
    .blogger-card { border: 1px solid var(--border, #2a3444); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
    .blogger-card-top { display: flex; align-items: baseline; gap: 8px; }
    .blogger-card-top b { font-size: 14px; }
    .blogger-card-top .bid { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-card .meta { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-card .latest { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .blogger-badge { display: inline-block; border-radius: 8px; padding: 1px 7px; font-size: 11px; font-weight: 700; }
    .blogger-badge.new { background: #16a34a22; color: #22c55e; }
    .blogger-badge.warn { background: #f59e0b22; color: #f59e0b; }
    .blogger-badge.run { background: #3b82f622; color: #60a5fa; }
    .blogger-card-actions { display: flex; gap: 6px; margin-top: 6px; }
    .blogger-add { display: flex; gap: 8px; flex-wrap: wrap; align-items: stretch; margin: 12px 0; }
    .blogger-add input { background: transparent; border: 1px solid var(--border, #2a3444); border-radius: 8px; color: inherit; padding: 0 10px; font-size: 13px; height: 34px; box-sizing: border-box; }
    .blogger-add .button, .blogger-add select { height: 34px; box-sizing: border-box; padding-top: 0; padding-bottom: 0; }
    .blogger-post-list { display: flex; flex-direction: column; }
    .blogger-post-row { display: flex; gap: 10px; align-items: baseline; padding: 9px 4px; border-bottom: 1px solid var(--border, #2a3444); cursor: pointer; }
    .blogger-post-row:hover { background: #ffffff0a; }
    .blogger-post-row .who { flex: 0 0 92px; color: var(--muted-2, #8a94a3); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .blogger-post-row .title { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .blogger-post-row .when { flex: 0 0 auto; color: var(--muted-2, #8a94a3); font-size: 11px; }
    .blogger-post-row .src { flex: 0 0 auto; font-size: 11px; }
    .blogger-post-row .src a { color: var(--muted-2, #8a94a3); }
    .blogger-post-row .src a:hover { color: inherit; }
    .blogger-article-head { margin-bottom: 10px; }
    .blogger-article-head h2 { margin: 6px 0; font-size: 18px; }
    .blogger-article-head .meta { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-feedback { color: #f59e0b; font-size: 12px; min-height: 16px; }
  `;
  document.head.appendChild(style);

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      throw new Error("로그인이 필요합니다.");
    }
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `요청 실패 (${response.status})`);
    }
    return data;
  }

  // 해시 → 화면 상태. #blogger-post-naver-<blogId>-<logNo> / #blogger-posts-<blogId> / #blogger-posts / #blogger
  function syncFromHash() {
    const hash = decodeURIComponent(location.hash || "#blogger");
    if (hash.startsWith("#blogger-post-")) {
      const articleId = hash.slice("#blogger-post-".length);
      const match = /^naver-(.+)-\d+$/.exec(articleId);
      if (match) {
        state.subview = "post";
        state.pendingArticle = { blogId: match[1], articleId };
        return;
      }
    }
    if (hash.startsWith("#blogger-posts")) {
      state.subview = "posts";
      state.filter = hash.startsWith("#blogger-posts-") ? hash.slice("#blogger-posts-".length) : "";
      return;
    }
    state.subview = "blogs";
  }

  // 탭 내부 이동 — 히스토리에 쌓아 뒤로가기가 화면 단위로 동작하게 한다
  function goto(hash) {
    history.pushState({ view: "blogger", bloggerPath: hash }, "", hash);
    load();
  }

  async function loadBlogs() {
    const data = await api("/api/blogs");
    state.blogs = data.blogs || [];
    state.blogsLoaded = true;
  }

  async function loadPosts(reset) {
    if (reset) {
      state.offset = 0;
      state.posts = [];
    }
    const base = state.filter ? `/api/blogs/${state.filter}/posts` : "/api/blogs/posts";
    const data = await api(`${base}?offset=${state.offset}&limit=${state.limit}`);
    state.posts = state.posts.concat(data.posts || []);
    state.postsTotal = data.total || 0;
    state.postsKey = state.filter;
  }

  async function loadArticle({ blogId, articleId }) {
    if (state.post?.articleId === articleId) {
      return;
    }
    const data = await api(`/api/blogs/${blogId}/posts/${articleId}`);
    const markdown = data.markdown.replace(/^---\n[\s\S]*?\n---\n/, "");
    state.post = { blogId, articleId, markdown, metadata: data.metadata || {} };
  }

  function blogName(blogId) {
    const blog = state.blogs.find((entry) => entry.id === blogId);
    return blog ? blog.name : blogId;
  }

  // 게시 시각 — publishedAt(ISO)이 있으면 절대 시각으로, 없으면 수집 시점의 원문 표기 그대로
  function formatWhen(post) {
    const ts = Date.parse(post.publishedAt || "");
    if (!Number.isFinite(ts)) {
      return post.publishedAtText || "";
    }
    const d = new Date(ts);
    const sameDay = new Date().toDateString() === d.toDateString();
    return sameDay
      ? d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false })
      : d.toLocaleDateString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric" });
  }

  function statusBadges(blog) {
    const badges = [];
    if (blog.runningJob) {
      const job = blog.lastJob;
      const progress = job && !job.done ? ` ${job.saved ?? 0}편` : "";
      badges.push(`<span class="blogger-badge run">${blog.runningJob.mode === "backfill" ? "백필 중" : "새 글 확인 중"}${progress}</span>`);
    }
    if (blog.recentCount > 0) {
      badges.push(`<span class="blogger-badge new" title="오늘(KST) 게시된 글">오늘 +${blog.recentCount}</span>`);
    }
    if (blog.fetchBlocked) {
      badges.push(`<span class="blogger-badge warn" title="글 목록은 보이지만 본문이 이웃공개/제한이라 수집할 수 없습니다">본문 접근 불가</span>`);
    }
    if (blog.noPublicPosts) {
      badges.push(`<span class="blogger-badge warn">공개 글 없음</span>`);
    }
    return badges.join(" ");
  }

  function render() {
    const view = document.querySelector("#bloggerView");
    if (!view) {
      return;
    }
    const active = state.blogs.filter((blog) => blog.active);
    const parts = [];
    parts.push('<section class="surface" style="padding:16px">');
    parts.push('<div class="blogger-head"><h2>블로거</h2><span class="blogger-tabs">');
    parts.push(`<button class="button secondary compact" type="button" data-sub="blogs" ${state.subview === "blogs" ? "disabled" : ""}>블로그 (${active.length})</button>`);
    parts.push(`<button class="button secondary compact" type="button" data-sub="posts" ${state.subview === "posts" ? "disabled" : ""}>글${state.postsTotal ? ` (${state.postsTotal.toLocaleString()})` : ""}</button>`);
    parts.push("</span>");
    parts.push('<button class="button secondary compact" type="button" data-action="reload" title="목록 새로고침">새로고침</button>');
    parts.push(`<span class="blogger-feedback">${escapeHtml(state.feedback)}</span>`);
    parts.push("</div>");

    if (state.subview === "blogs") {
      parts.push('<div class="blogger-add">');
      parts.push('<input id="bloggerAddId" placeholder="네이버 블로그 ID (예: hodolry)" spellcheck="false">');
      parts.push('<input id="bloggerAddName" placeholder="표시 이름 (비우면 자동)">');
      parts.push('<button class="button compact" type="button" data-action="add">추가 → 백필 시작</button>');
      parts.push("</div>");
      parts.push('<div class="blogger-cards">');
      for (const blog of state.blogs) {
        if (!blog.active) {
          continue;
        }
        const latest = blog.latest
          ? `<span class="latest" title="${escapeHtml(blog.latest.title)}">${escapeHtml(blog.latest.title)}</span>`
          : '<span class="latest meta">아직 수집된 글 없음</span>';
        const checked = blog.lastCheck?.checkedAt
          ? `마지막 확인 ${new Date(blog.lastCheck.checkedAt).toLocaleString("ko-KR", { hour12: false })}`
          : "자동 확인 대기 중";
        parts.push(`
          <div class="blogger-card" data-blog="${escapeHtml(blog.id)}">
            <div class="blogger-card-top"><b>${escapeHtml(blog.name)}</b><span class="bid">${escapeHtml(blog.id)}</span>${statusBadges(blog)}</div>
            ${latest}
            <span class="meta">${blog.count.toLocaleString()}편 · ${checked}</span>
            <div class="blogger-card-actions">
              <button class="button secondary compact" type="button" data-action="posts-of">글 보기</button>
              <button class="button secondary compact" type="button" data-action="refresh-one" ${blog.runningJob || blog.fetchBlocked ? "disabled" : ""}>새 글 확인</button>
              <button class="button secondary compact" type="button" data-action="remove">제거</button>
            </div>
          </div>`);
      }
      parts.push("</div>");
    }

    if (state.subview === "posts") {
      const options = ['<option value="">전체 블로거</option>'];
      for (const blog of active) {
        options.push(`<option value="${escapeHtml(blog.id)}" ${state.filter === blog.id ? "selected" : ""}>${escapeHtml(blog.name)}</option>`);
      }
      parts.push(`<div class="blogger-add"><select id="bloggerFilter" class="button secondary compact">${options.join("")}</select><span class="meta" style="color:var(--muted-2,#8a94a3);font-size:12px">${state.postsTotal.toLocaleString()}편</span></div>`);
      parts.push('<div class="blogger-post-list">');
      for (const post of state.posts) {
        const original = post.url || "";
        parts.push(`
          <div class="blogger-post-row" data-blog="${escapeHtml(post.blogId)}" data-article="${escapeHtml(post.id)}">
            <span class="who">${escapeHtml(blogName(post.blogId))}</span>
            <span class="title">${escapeHtml(post.title)}</span>
            <span class="when">${escapeHtml(formatWhen(post))}</span>
            ${original ? `<span class="src"><a href="${escapeHtml(original)}" target="_blank" rel="noopener" title="네이버 원문 열기">원문 ↗</a></span>` : ""}
          </div>`);
      }
      parts.push("</div>");
      if (state.posts.length < state.postsTotal) {
        parts.push('<div style="text-align:center;margin-top:10px"><button class="button secondary compact" type="button" data-action="more">더 보기</button></div>');
      }
    }

    if (state.subview === "post" && state.post) {
      const meta = state.post.metadata || {};
      parts.push('<div class="blogger-article-head">');
      parts.push('<button class="button secondary compact" type="button" data-action="back">← 목록</button>');
      parts.push(`<h2>${escapeHtml(meta.title || "")}</h2>`);
      const original = meta.canonicalUrl || meta.url || "";
      parts.push(`<div class="meta">${escapeHtml(blogName(state.post.blogId))} · ${escapeHtml(meta.publishedAtText || "")}${original ? ` · <a href="${escapeHtml(original)}" target="_blank" rel="noopener">원문 ↗</a>` : ""}</div>`);
      parts.push("</div>");
      const bodyHtml = renderMarkdown(state.post.markdown.replace(/^# .*\n/, ""));
      parts.push(
        bodyHtml.trim()
          ? `<div class="markdown-body">${bodyHtml}</div>`
          : '<p class="meta" style="color:var(--muted-2,#8a94a3)">본문이 없는 글입니다 (이미지·공지 전용) — 위 원문 링크로 확인하세요.</p>',
      );
    }

    parts.push("</section>");
    view.innerHTML = parts.join("");
    bind(view);
    schedulePoll();
  }

  function bind(view) {
    view.querySelectorAll("[data-sub]").forEach((button) => {
      button.addEventListener("click", () => {
        state.feedback = "";
        goto(button.dataset.sub === "posts" ? "#blogger-posts" : "#blogger");
      });
    });
    view.querySelector('[data-action="reload"]')?.addEventListener("click", () => {
      state.blogsLoaded = false;
      state.postsKey = " "; // 강제 재로드
      load();
    });
    view.querySelector('[data-action="add"]')?.addEventListener("click", async () => {
      const blogId = view.querySelector("#bloggerAddId").value.trim();
      const name = view.querySelector("#bloggerAddName").value.trim();
      if (!blogId) {
        state.feedback = "블로그 ID를 입력하세요";
        render();
        return;
      }
      state.feedback = "블로그 확인 중…";
      render();
      try {
        await api("/api/blogs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blogId, name }),
        });
        state.feedback = `${blogId} 추가됨 — 백필 시작`;
        await loadBlogs();
      } catch (error) {
        state.feedback = error.message;
      }
      render();
    });
    view.querySelectorAll(".blogger-card").forEach((card) => {
      const blogId = card.dataset.blog;
      card.querySelector('[data-action="posts-of"]')?.addEventListener("click", () => {
        goto(`#blogger-posts-${blogId}`);
      });
      card.querySelector('[data-action="refresh-one"]')?.addEventListener("click", async () => {
        try {
          await api(`/api/blogs/${blogId}/refresh`, { method: "POST" });
          state.feedback = `${blogId} 새 글 확인 시작`;
          await loadBlogs();
        } catch (error) {
          state.feedback = error.message;
        }
        render();
      });
      card.querySelector('[data-action="remove"]')?.addEventListener("click", async () => {
        if (!window.confirm(`${blogId} 블로그를 목록에서 제거할까요? (수집된 글은 보존됩니다)`)) {
          return;
        }
        try {
          await api(`/api/blogs/${blogId}`, { method: "DELETE" });
          await loadBlogs();
        } catch (error) {
          state.feedback = error.message;
        }
        render();
      });
    });
    view.querySelector("#bloggerFilter")?.addEventListener("change", (event) => {
      goto(event.target.value ? `#blogger-posts-${event.target.value}` : "#blogger-posts");
    });
    view.querySelector('[data-action="more"]')?.addEventListener("click", async () => {
      state.offset += state.limit;
      try {
        await loadPosts(false);
      } catch (error) {
        state.feedback = error.message;
      }
      render();
    });
    view.querySelectorAll(".blogger-post-row").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest("a")) {
          return; // 원문 링크는 그대로 새 탭으로
        }
        goto(`#blogger-post-${row.dataset.article}`);
      });
    });
    view.querySelector('[data-action="back"]')?.addEventListener("click", () => {
      goto(state.filter ? `#blogger-posts-${state.filter}` : "#blogger-posts");
    });
  }

  // 수집 job이 돌고 있으면 8초마다 상태 갱신 (블로거 화면이 보일 때만)
  function schedulePoll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    const visible = !document.querySelector("#bloggerView")?.hidden;
    const running = state.blogs.some((blog) => blog.runningJob);
    if (!visible || !running || state.subview !== "blogs") {
      return;
    }
    pollTimer = setTimeout(async () => {
      try {
        await loadBlogs();
        if (state.subview === "blogs") {
          render();
        }
      } catch {
        // 다음 진입 때 다시
      }
    }, 8000);
  }

  // 진입점 — 내비 클릭·뒤로가기(popstate)·새로고침 모두 여기로 온다. 해시가 진실이다.
  async function load() {
    try {
      syncFromHash();
      if (!state.blogsLoaded) {
        await loadBlogs();
      }
      if (state.subview === "posts" && state.postsKey !== state.filter) {
        await loadPosts(true);
      }
      if (state.subview === "post" && state.pendingArticle) {
        await loadArticle(state.pendingArticle);
      }
      render();
    } catch (error) {
      const view = document.querySelector("#bloggerView");
      if (view) {
        view.innerHTML = `<section class="surface" style="padding:16px"><p class="blogger-feedback">${escapeHtml(error.message)}</p></section>`;
      }
    }
  }

  window.AttnBlogger = { load };
})();
