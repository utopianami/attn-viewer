// 블로거 탭 — 새 글 피드(메인) + 블로그 관리 + 저장본 열람
// 설계: docs/2026-07-08-blogger-tab-phase1-design.md + docs/blogger-tab-layout-mockup.html (2026-07-09 개편)
// index.html의 전역(renderMarkdown, escapeHtml)을 재사용한다. window.AttnBlogger.load()가 진입점.
// 해시: #blogger(피드) / #blogger-posts-<blogId>(블로거 필터 피드) / #blogger-manage(관리) / #blogger-post-<articleId>(저장본)
(() => {
  const state = {
    blogs: [],
    posts: [],
    postsTotal: 0,
    filter: "",
    offset: 0,
    limit: 30,
    subview: "feed", // feed | manage | post
    post: null,
    pendingArticle: null,
    blogsLoaded: false,
    postsKey: null, // 어떤 필터로 불러온 목록인지 (null=미로드)
    loadedAt: 0, // 마지막 데이터 로드 시각 — 오래되면 진입 시 자동 재로드
    feedback: "",
  };
  const STALE_MS = 5 * 60 * 1000;
  let pollTimer = null;

  const style = document.createElement("style");
  style.textContent = `
    .blogger-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
    .blogger-head h2 { margin: 0; font-size: 18px; }
    .blogger-head .sub { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-feedback { color: #f59e0b; font-size: 12px; min-height: 16px; }
    .blogger-gear { margin-left: auto; border: 0; background: none; color: var(--muted-2, #8a94a3);
      font-size: 17px; cursor: pointer; padding: 2px 6px; line-height: 1; }
    .blogger-gear:hover { color: var(--text, #e6ebf2); }
    /* 오늘 요약 스트립 */
    .blogger-hero { display: flex; gap: 18px; align-items: center; border: 1px solid var(--border, #2a3444);
      border-radius: 12px; padding: 13px 16px; margin-bottom: 12px; }
    .blogger-hero .big { font-size: 21px; font-weight: 800; }
    .blogger-hero .big b { color: #22c55e; }
    .blogger-hero .sub2 { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-hero .side { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    /* 필터 칩 */
    .blogger-chips { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 6px; margin-bottom: 4px; }
    .blogger-chips::-webkit-scrollbar { height: 0; }
    .blogger-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border, #2a3444);
      border-radius: 16px; padding: 3px 12px; font-size: 12px; color: var(--muted-2, #8a94a3);
      white-space: nowrap; cursor: pointer; background: transparent; }
    .blogger-chip.on { border-color: #5aa0ff; color: var(--text, #e6ebf2); background: #5aa0ff14; }
    .blogger-chip b { color: #22c55e; font-size: 11px; }
    /* 날짜 그룹 */
    .blogger-daybar { display: flex; align-items: center; gap: 10px; margin: 16px 0 2px; color: var(--muted-2, #8a94a3); font-size: 12px; }
    .blogger-daybar b { color: var(--text, #e6ebf2); font-size: 12.5px; }
    .blogger-daybar .cnt { color: #22c55e; font-weight: 700; }
    .blogger-daybar::after { content: ""; flex: 1; height: 1px; background: var(--border, #2a3444); }
    /* 피드 행 */
    .blogger-post-row { display: flex; gap: 10px; align-items: baseline; padding: 10px 6px; border-bottom: 1px solid var(--border, #2a3444); cursor: pointer; }
    .blogger-post-row:hover { background: #ffffff0a; }
    .blogger-post-row .who { flex: 0 0 88px; color: var(--muted-2, #8a94a3); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .blogger-post-row .mid { flex: 1; min-width: 0; }
    .blogger-post-row .title { display: block; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .blogger-post-row.is-today .title { font-weight: 650; }
    .blogger-post-row .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #22c55e; margin-right: 6px; vertical-align: 1.5px; }
    .blogger-post-row .sum { display: block; color: var(--muted-2, #8a94a3); font-size: 12.5px; margin-top: 4px; line-height: 1.55; white-space: normal; }
    .blogger-post-row .sum.none { color: #5a6472; font-style: italic; }
    .blogger-post-row .when { flex: 0 0 auto; color: var(--muted-2, #8a94a3); font-size: 11.5px; font-variant-numeric: tabular-nums; }
    .blogger-post-row .src { flex: 0 0 auto; font-size: 11.5px; }
    .blogger-post-row .src a { color: var(--muted-2, #8a94a3); }
    .blogger-post-row .src a:hover { color: inherit; }
    /* 관리 화면 */
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
    /* 저장본 */
    .blogger-article-head { margin-bottom: 10px; }
    .blogger-article-head h2 { margin: 6px 0; font-size: 18px; }
    .blogger-article-head .meta { color: var(--muted-2, #8a94a3); font-size: 12px; }
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
    if (hash === "#blogger-manage") {
      state.subview = "manage";
      return;
    }
    if (hash.startsWith("#blogger-posts")) {
      state.subview = "feed";
      state.filter = hash.startsWith("#blogger-posts-") ? hash.slice("#blogger-posts-".length) : "";
      return;
    }
    state.subview = "feed";
    state.filter = "";
  }

  // 탭 내부 이동 — 히스토리에 쌓아 뒤로가기가 화면 단위로 동작
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

  function kstDayKey(iso) {
    const ts = Date.parse(iso || "");
    if (!Number.isFinite(ts)) {
      return "";
    }
    return new Date(ts + 9 * 3600 * 1000).toISOString().slice(0, 10);
  }

  function dayLabel(key) {
    const today = kstDayKey(new Date().toISOString());
    if (key === today) {
      return "오늘";
    }
    const yesterday = kstDayKey(new Date(Date.now() - 24 * 3600 * 1000).toISOString());
    if (key === yesterday) {
      return "어제";
    }
    if (!key) {
      return "날짜 미상";
    }
    const [, month, day] = key.split("-");
    return `${Number(month)}월 ${Number(day)}일`;
  }

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

  function lastCheckLabel() {
    let latest = 0;
    for (const blog of state.blogs) {
      const ts = Date.parse(blog.lastCheck?.checkedAt || "");
      if (Number.isFinite(ts) && ts > latest) {
        latest = ts;
      }
    }
    if (!latest) {
      return "자동 확인 대기 중 · 30분마다";
    }
    return `마지막 확인 ${new Date(latest).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false })} · 30분마다 자동`;
  }

  function renderFeed(parts) {
    const active = state.blogs.filter((blog) => blog.active);
    const todayBlogs = active.filter((blog) => blog.recentCount > 0);
    const todayTotal = todayBlogs.reduce((sum, blog) => sum + blog.recentCount, 0);

    // 오늘 요약 스트립
    parts.push('<div class="blogger-hero">');
    parts.push(`<div><div class="big">오늘 새 글 <b>${todayTotal}</b>편</div><div class="sub2">블로거 ${todayBlogs.length}명 · 전체 ${state.postsTotal ? state.postsTotal.toLocaleString() : "…"}편 수집</div></div>`);
    parts.push('<div class="side">');
    for (const blog of todayBlogs.slice(0, 6)) {
      parts.push(`<button class="blogger-chip" type="button" data-chip="${escapeHtml(blog.id)}">${escapeHtml(blog.name)} <b>+${blog.recentCount}</b></button>`);
    }
    parts.push("</div></div>");

    // 필터 칩 — 오늘 새 글 있는 블로거 먼저
    const ordered = [...todayBlogs, ...active.filter((blog) => !blog.recentCount)];
    parts.push('<div class="blogger-chips">');
    parts.push(`<button class="blogger-chip ${state.filter ? "" : "on"}" type="button" data-chip="">전체</button>`);
    for (const blog of ordered) {
      const plus = blog.recentCount > 0 ? ` <b>+${blog.recentCount}</b>` : "";
      parts.push(`<button class="blogger-chip ${state.filter === blog.id ? "on" : ""}" type="button" data-chip="${escapeHtml(blog.id)}">${escapeHtml(blog.name)}${plus}</button>`);
    }
    parts.push("</div>");

    // 날짜 그룹 피드
    const todayKey = kstDayKey(new Date().toISOString());
    let currentDay = null;
    for (const post of state.posts) {
      const dayKey = kstDayKey(post.publishedAt);
      if (dayKey !== currentDay) {
        currentDay = dayKey;
        const isTodayBar = dayKey === todayKey;
        const count = isTodayBar && !state.filter ? `${todayTotal}편` : "";
        parts.push(`<div class="blogger-daybar"><b>${dayLabel(dayKey)}</b>${count ? ` <span class="cnt">${count}</span>` : ""}</div>`);
      }
      const isToday = dayKey === todayKey;
      let summaryHtml = "";
      if (post.summary) {
        summaryHtml = `<span class="sum">${escapeHtml(post.summary)}</span>`;
      } else if (post.summaryReason === "no_text") {
        summaryHtml = '<span class="sum none">본문 없는 글 (이미지·공지) — 원문 확인</span>';
      } else if (isToday) {
        summaryHtml = '<span class="sum none">요약 준비 중…</span>';
      }
      parts.push(`
        <div class="blogger-post-row ${isToday ? "is-today" : ""}" data-article="${escapeHtml(post.id)}" data-url="${escapeHtml(post.url || "")}" title="클릭하면 네이버 원문이 새 탭으로 열립니다">
          <span class="who">${escapeHtml(blogName(post.blogId))}</span>
          <span class="mid">
            <span class="title">${isToday ? '<span class="dot"></span>' : ""}${escapeHtml(post.title)}</span>
            ${summaryHtml}
          </span>
          <span class="when">${escapeHtml(formatWhen(post))}</span>
          <span class="src"><a href="#blogger-post-${escapeHtml(post.id)}" title="우리가 저장한 사본 보기">저장본</a></span>
        </div>`);
    }
    if (state.posts.length < state.postsTotal) {
      parts.push('<div style="text-align:center;margin-top:10px"><button class="button secondary compact" type="button" data-action="more">더 보기</button></div>');
    }
  }

  function renderManage(parts) {
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

  function renderPost(parts) {
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

  function render() {
    const view = document.querySelector("#bloggerView");
    if (!view) {
      return;
    }
    const parts = [];
    parts.push('<section class="surface" style="padding:16px">');
    parts.push('<div class="blogger-head">');
    if (state.subview === "manage") {
      parts.push('<button class="button secondary compact" type="button" data-action="to-feed">← 피드</button>');
      parts.push("<h2>블로그 관리</h2>");
    } else {
      parts.push("<h2>블로거</h2>");
      parts.push(`<span class="sub">${escapeHtml(lastCheckLabel())}</span>`);
      parts.push('<button class="blogger-gear" type="button" data-action="to-manage" title="블로그 관리 (추가/제거)" aria-label="블로그 관리">⚙</button>');
    }
    parts.push(`<span class="blogger-feedback">${escapeHtml(state.feedback)}</span>`);
    parts.push("</div>");

    if (state.subview === "feed") {
      renderFeed(parts);
    } else if (state.subview === "manage") {
      renderManage(parts);
    } else if (state.subview === "post" && state.post) {
      renderPost(parts);
    }

    parts.push("</section>");
    view.innerHTML = parts.join("");
    bind(view);
    schedulePoll();
  }

  function bind(view) {
    view.querySelector('[data-action="to-manage"]')?.addEventListener("click", () => goto("#blogger-manage"));
    view.querySelector('[data-action="to-feed"]')?.addEventListener("click", () => goto("#blogger"));
    view.querySelectorAll("[data-chip]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const id = chip.dataset.chip;
        goto(id ? `#blogger-posts-${id}` : "#blogger");
      });
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
        const anchor = event.target.closest("a");
        if (anchor) {
          // "저장본" 링크 → 내부 뷰어 (해시 라우팅)
          event.preventDefault();
          goto(anchor.getAttribute("href"));
          return;
        }
        // 행 클릭 → 네이버 원문 새 탭
        if (row.dataset.url) {
          window.open(row.dataset.url, "_blank", "noopener");
        }
      });
    });
    view.querySelector('[data-action="back"]')?.addEventListener("click", () => {
      goto(state.filter ? `#blogger-posts-${state.filter}` : "#blogger");
    });
  }

  // 수집 job이 돌고 있으면 8초마다 상태 갱신 (관리 화면이 보일 때만)
  function schedulePoll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    const visible = !document.querySelector("#bloggerView")?.hidden;
    const running = state.blogs.some((blog) => blog.runningJob);
    if (!visible || !running || state.subview !== "manage") {
      return;
    }
    pollTimer = setTimeout(async () => {
      try {
        await loadBlogs();
        if (state.subview === "manage") {
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
      // 새로고침 버튼 없음 — 5분 넘게 묵은 데이터는 진입 시 자동 재로드
      if (state.loadedAt && Date.now() - state.loadedAt > STALE_MS) {
        state.blogsLoaded = false;
        state.postsKey = null;
      }
      if (!state.blogsLoaded) {
        await loadBlogs();
        state.loadedAt = Date.now();
      }
      if (state.subview === "feed" && state.postsKey !== state.filter) {
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
