// 히스토리 탭 — 과거 시장 사례 학습 글 뷰어 (연도-테마)
// 리스트("연도 - 테마", 연도 내림차순) → 상세(markdown 본문)
// window.AttnHistory.load()가 진입점. 해시: #history(리스트) / #history-<id>(상세)
// 데이터: storage/rag/history_cases/*.json (market-reports와 동일한 전역 읽기 전용 패턴)
(() => {
  const state = {
    cases: null,        // 목록 (null=미로드)
    detail: null,       // 현재 상세
    subview: "list",    // list | detail
    detailId: "",
    error: "",
  };

  const style = document.createElement("style");
  style.textContent = `
    .history-wrap { max-width: 860px; margin: 0 auto; }
    .history-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
    .history-head h2 { margin: 0; font-size: 18px; }
    .history-head .sub { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .history-feedback { color: #f59e0b; font-size: 12px; min-height: 16px; }
    /* 리스트 */
    .history-row { display: flex; gap: 12px; align-items: baseline; padding: 13px 8px;
      border-bottom: 1px solid var(--border, #2a3444); cursor: pointer; }
    .history-row:hover { background: #ffffff0a; }
    .history-row .idx { flex: 0 0 auto; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 700; }
    .history-row .idx .theme { color: #5aa0ff; }
    .history-row .mid { flex: 1; min-width: 0; }
    .history-row .title { display: block; font-size: 13.5px; }
    .history-row .meta { display: block; color: var(--muted-2, #8a94a3); font-size: 12px; margin-top: 3px; }
    .history-row .when { flex: 0 0 auto; color: var(--muted-2, #8a94a3); font-size: 11.5px; font-variant-numeric: tabular-nums; }
    /* 상세 */
    .history-back { border: 0; background: none; color: var(--muted-2, #8a94a3); font-size: 13px; cursor: pointer; padding: 4px 0; margin-bottom: 6px; }
    .history-back:hover { color: var(--text, #e6ebf2); }
    .history-title { font-size: 19px; margin: 2px 0 2px; }
    .history-when { color: var(--muted-2, #8a94a3); font-size: 12px; margin-bottom: 16px; }
    .history-article { font-size: 13.5px; line-height: 1.75; margin: 4px 0 14px; }
    .history-article table { display: block; overflow-x: auto; max-width: 100%; }
    .history-empty { color: var(--muted-2, #8a94a3); font-size: 13px; padding: 30px 8px; text-align: center; }
  `;
  document.head.appendChild(style);

  const view = () => document.getElementById("historyView");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function api(path) {
    const res = await fetch(path, { headers: { accept: "application/json" } });
    let data = {};
    try { data = await res.json(); } catch {}
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `요청 실패 (${res.status})`);
    }
    return data;
  }

  function sanitizeHtml(html) {
    // renderMarkdown은 URL 속성 탈출을 안 막는다 — report.js와 동일한 DOM 레벨 소독.
    const t = document.createElement("template");
    t.innerHTML = html;
    t.content.querySelectorAll("script,iframe,object,embed,style").forEach((el) => el.remove());
    t.content.querySelectorAll("*").forEach((el) => {
      [...el.attributes].forEach((a) => {
        const n = a.name.toLowerCase();
        if (n.startsWith("on")) el.removeAttribute(a.name);
        else if ((n === "href" || n === "src")
                 && !/^(https?:|#|\/)/i.test(a.value.trim())) el.removeAttribute(a.name);
      });
    });
    return t.innerHTML;
  }

  function mdToHtml(md) {
    return (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(String(md || "")))
      : `<pre style="white-space:pre-wrap">${esc(md || "")}</pre>`;
  }

  function labelOf(c) {
    return `${c.year} - ${c.theme || "?"}`;
  }

  // ── 렌더 ──────────────────────────────────────────────
  function renderList() {
    const el = view();
    if (state.error) { el.innerHTML = `<div class="history-wrap"><div class="history-feedback">${esc(state.error)}</div></div>`; return; }
    if (!state.cases) { el.innerHTML = `<div class="history-wrap"><div class="history-empty">불러오는 중…</div></div>`; return; }
    const rows = state.cases.map((c) => `<div class="history-row" data-id="${esc(c.id)}">
      <span class="idx">${esc(c.year)} - <span class="theme">${esc(c.theme || "?")}</span></span>
      <span class="mid">
        ${c.title ? `<span class="title">${esc(c.title)}</span>` : ""}
        <span class="meta">${c.hasBody ? "정리 완료" : "내용 준비 중"}</span>
      </span>
      <span class="when">${esc(c.updatedAt || "")}</span>
    </div>`).join("");
    el.innerHTML = `<div class="history-wrap">
      <div class="history-head"><h2>히스토리</h2><span class="sub">연도 - 테마 · 과거 시장 사례 학습</span></div>
      ${state.cases.length ? rows : `<div class="history-empty">아직 정리된 사례가 없습니다.</div>`}
    </div>`;
    el.querySelectorAll(".history-row").forEach((row) => {
      row.addEventListener("click", () => goto(`#history-${row.dataset.id}`));
    });
  }

  function renderDetail() {
    const el = view();
    const c = state.detail;
    if (state.error) { el.innerHTML = `<div class="history-wrap"><button class="history-back">← 목록</button><div class="history-feedback">${esc(state.error)}</div></div>`; bindBack(); return; }
    if (!c) { el.innerHTML = `<div class="history-wrap"><div class="history-empty">불러오는 중…</div></div>`; return; }
    const body = String(c.body || "").trim();
    el.innerHTML = `<div class="history-wrap">
      <button class="history-back">← 목록</button>
      <div class="history-title">${esc(c.title || labelOf(c))}</div>
      <div class="history-when">${c.title ? `${esc(labelOf(c))} · ` : ""}${c.updatedAt ? `갱신 ${esc(c.updatedAt)}` : ""}</div>
      ${body
        ? `<div class="markdown-body history-article">${mdToHtml(body)}</div>`
        : `<div class="history-empty">내용 준비 중 — 아직 정리 전입니다.</div>`}
    </div>`;
    bindBack();
  }

  function bindBack() {
    const b = view().querySelector(".history-back");
    if (b) b.addEventListener("click", () => goto("#history"));
  }

  // ── 라우팅 ────────────────────────────────────────────
  function syncFromHash() {
    const hash = decodeURIComponent(location.hash || "#history");
    if (hash.startsWith("#history-")) {
      state.subview = "detail";
      state.detailId = hash.slice("#history-".length);
    } else {
      state.subview = "list";
      state.detailId = "";
    }
  }

  function goto(hash) {
    history.pushState({ view: "history", historyPath: hash }, "", hash);
    load();
  }

  async function load() {
    syncFromHash();
    state.error = "";
    const el = view();
    if (!el) return;
    if (state.subview === "detail") {
      if (!state.detail || state.detail.id !== state.detailId) {
        state.detail = null;
        renderDetail();
        try {
          const data = await api(`/api/history-cases/${encodeURIComponent(state.detailId)}`);
          state.detail = data.case;
        } catch (e) { state.error = e.message; }
      }
      renderDetail();
    } else {
      renderList();
      try {
        const data = await api("/api/history-cases");
        state.cases = data.cases || [];
      } catch (e) { state.error = e.message; state.cases = []; }
      renderList();
    }
  }

  window.AttnHistory = { load };
})();
