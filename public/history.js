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
    /* 구조가 눈에 들어오게 — 기본 markdown-body h3/h4는 본문과 구분이 안 됨 (2026-08-06 사용자) */
    .history-article h3 { font-size: 17px; font-weight: 800; margin: 30px 0 10px; padding-top: 16px;
      border-top: 1px solid var(--border, #2a3444); }
    .history-article h4 { font-size: 14.5px; font-weight: 800; color: #5aa0ff; margin: 22px 0 8px; }
    .history-article table { display: block; overflow-x: auto; max-width: 100%; }
    .history-empty { color: var(--muted-2, #8a94a3); font-size: 13px; padding: 30px 8px; text-align: center; }
    /* 근거 라벨 칩 — 〔측정:…〕〔계산:…〕〔해석:…〕〔논쟁:…〕〔미측정〕 (2026-08-06 논증 규약)
       파랑 밀도 = 주장의 신뢰도. 회색뿐인 문단은 아직 가설 수준임이 시각적으로 드러난다. */
    .ev { display: inline; border-radius: 6px; padding: 0.5px 5px; font-size: 0.85em; line-height: 1.4;
      box-decoration-break: clone; -webkit-box-decoration-break: clone; }
    .ev b { font-weight: 800; font-size: 0.92em; letter-spacing: .2px; }
    .ev.measure { background: #5aa0ff1c; color: #8fc0ff; }
    .ev.measure b { color: #5aa0ff; }
    .ev.calc { background: #16a34a1c; color: #7fd6a2; }
    .ev.calc b { color: #22c55e; }
    .ev.press { background: #6b72801f; color: #aab3c0; }
    .ev.press b { color: #9aa4b2; }
    .ev.interp { background: #6b728014; color: #8a94a3; }
    .ev.interp b { color: #8a94a3; }
    .ev.dispute { background: #f59e0b1c; color: #f4c069; }
    .ev.dispute b { color: #f59e0b; }
    .ev.unmeasured { background: #dc26261a; color: #f09b9b; }
    .ev.unmeasured b { color: #f87171; }
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
    // 이미지 라인(![alt](/경로)) — renderMarkdown 미지원이라 플레이스홀더로 치환 후 직접 복원.
    // src는 루트 상대 경로만 허용 (sanitizeHtml 규칙과 동일 취지).
    const pre = String(md || "").split("\n").map((line) => {
      const m = line.match(/^!\[([^\]]*)\]\((\/[A-Za-z0-9._/-]+)\)\s*$/);
      return m ? `%%IMG%%${m[2]}%%${m[1]}%%` : line;
    }).join("\n")
      // 루트 상대 링크([텍스트](/경로)) — renderInlineMd는 http(s)만 지원
      .replace(/\[([^\]]+)\]\((\/[A-Za-z0-9._/-]+)\)/g, "%%LNK%%$2%%$1%%");
    const html = (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(pre))
      : `<pre style="white-space:pre-wrap">${esc(pre)}</pre>`;
    let out = html.replace(/%%IMG%%([A-Za-z0-9._/-]+)%%([^%]*)%%/g,
      '<img src="$1" alt="$2" loading="lazy" style="max-width:100%;border-radius:10px;margin:6px 0">');
    out = out.replace(/%%LNK%%([A-Za-z0-9._/-]+)%%([^%]*)%%/g,
      '<a href="$1" target="_blank" rel="noopener">$2</a>');
    // 근거 라벨 칩 — 〔측정: …〕〔계산: …〕〔보도: …〕〔해석: …〕〔논쟁: …〕〔미측정…〕
    const EV_CLASS = { "측정": "measure", "계산": "calc", "보도": "press", "해석": "interp", "논쟁": "dispute", "미측정": "unmeasured" };
    out = out.replace(/〔(측정|계산|보도|해석|논쟁|미측정)(?::\s*([^〕]{0,300}))?〕/g, (_, kind, body) =>
      `<span class="ev ${EV_CLASS[kind]}"><b>${kind}</b>${body ? ` ${body}` : ""}</span>`);
    // 그 외 〔…〕(출처 표기 등)는 흐린 소형 — 리포트 탭 src-ref와 동일 취지
    out = out.replace(/〔([^〕<]{1,200})〕/g, '<span style="color:var(--muted-2,#8a94a3);font-size:0.8em;opacity:.85">〔$1〕</span>');
    return out;
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
        ${c.hasBody ? "" : `<span class="meta">내용 준비 중</span>`}
      </span>
      <span class="when">${esc(c.updatedAt || "")}</span>
    </div>`).join("");
    el.innerHTML = `<div class="history-wrap">
      <div class="history-head"><h2>히스토리</h2><span class="sub">연도 - 테마 · 과거 시장 사례 학습</span></div>
      ${state.cases.length ? rows : `<div class="history-empty">아직 정리된 사례가 없습니다.</div>`}
    </div>`;
    el.querySelectorAll(".history-row").forEach((row) => {
      row.addEventListener("click", () => {
        // page가 있는 사례는 요약 층 없이 완전판 HTML로 직행 (2026-08-07 사용자 — 뎁스 금지)
        const c = (state.cases || []).find((x) => x.id === row.dataset.id);
        if (c && c.page && /^\/[A-Za-z0-9._/-]+$/.test(c.page)) { location.href = c.page; return; }
        goto(`#history-${row.dataset.id}`);
      });
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
      // 완전판 HTML이 있는 사례는 상세 화면 없이 직행 (딥링크 방문 대비)
      const pg = state.detail && state.detail.page;
      if (pg && /^\/[A-Za-z0-9._/-]+$/.test(pg)) { location.replace(pg); return; }
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
