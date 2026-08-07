// 시황 리포트 탭 — 12h 메모리 반도체 시황 리포트 뷰어
// 설계: /html/market-report-design.html
// 리스트(최신순, "날짜 - N (시간)") → 상세(최종 주장 카드 위 / 사고흐름 펼치기 아래)
// window.AttnReport.load()가 진입점. 해시: #report(리스트) / #report-<id>(상세)
(() => {
  const state = {
    reports: null,       // 목록 (null=미로드)
    report: null,        // 현재 상세
    subview: "list",     // list | detail
    detailId: "",
    loading: false,
    error: "",
  };

  const style = document.createElement("style");
  style.textContent = `
    .report-wrap { max-width: 860px; margin: 0 auto; }
    .report-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
    .report-head h2 { margin: 0; font-size: 18px; }
    .report-head .sub { color: var(--muted-2, #8a94a3); font-size: 12px; }
    .report-feedback { color: #f59e0b; font-size: 12px; min-height: 16px; }
    /* 리스트 */
    .report-row { display: flex; gap: 12px; align-items: baseline; padding: 13px 8px;
      border-bottom: 1px solid var(--border, #2a3444); cursor: pointer; }
    .report-row:hover { background: #ffffff0a; }
    .report-row .idx { flex: 0 0 auto; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 700; }
    .report-row .idx .seq { color: #5aa0ff; }
    .report-row .mid { flex: 1; min-width: 0; }
    .report-row .title { display: block; font-size: 13.5px; }
    .report-row .meta { display: block; color: var(--muted-2, #8a94a3); font-size: 12px; margin-top: 3px; }
    .report-row .when { flex: 0 0 auto; color: var(--muted-2, #8a94a3); font-size: 11.5px; font-variant-numeric: tabular-nums; }
    /* 상세 */
    .report-back { border: 0; background: none; color: var(--muted-2, #8a94a3); font-size: 13px; cursor: pointer; padding: 4px 0; margin-bottom: 6px; }
    .report-back:hover { color: var(--text, #e6ebf2); }
    .report-title { font-size: 19px; margin: 2px 0 2px; }
    .report-when { color: var(--muted-2, #8a94a3); font-size: 12px; margin-bottom: 16px; }
    /* 종합 */
    .report-overview { border-left: 3px solid #5aa0ff; padding: 2px 0 2px 14px; margin: 4px 0 10px; font-size: 13.5px; line-height: 1.65; }
    .report-overview p { margin: 0 0 6px; }
    .report-overview ul { margin: 0; padding-left: 18px; }
    .report-overview li { margin: 3px 0; }
    /* 최종 의견 */
    .final-opinion { border: 1px solid #5aa0ff66; background: #5aa0ff12; border-radius: 12px; padding: 14px 16px; margin: 4px 0 10px; display: flex; gap: 12px; align-items: flex-start; }
    .final-opinion .fo-text { flex: 1; font-size: 14.5px; font-weight: 650; line-height: 1.6; }
    .final-opinion .fo-text b { color: #22c55e; }
    .section-hint { color: #5a6472; font-size: 11.5px; margin: -2px 0 8px; }
    /* 검증 상태 배너 (C1) — 본문 위 한 줄, 눈에 띄되 과하지 않게 (2026-07-24) */
    .verify-banner { border: 1px solid #f59e0b55; background: #f59e0b10; border-radius: 10px;
      padding: 9px 13px; margin: 4px 0 12px; font-size: 12.8px; line-height: 1.55; }
    .report-section-label { font-size: 11.5px; font-weight: 800; letter-spacing: .4px; text-transform: uppercase;
      color: var(--muted-2, #8a94a3); margin: 20px 0 8px; }
    /* 주장 카드 */
    .claim { border: 1px solid var(--border, #2a3444); border-radius: 12px; padding: 15px 17px; margin: 10px 0; }
    .claim-top { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
    .claim-top .thesis { font-size: 15px; font-weight: 700; flex: 1; min-width: 0; }
    .claim-conf { flex: 0 0 auto; font-size: 11px; font-weight: 800; border-radius: 20px; padding: 2px 10px; }
    .claim-conf.high { background: #16a34a22; color: #22c55e; }
    .claim-conf.mid { background: #f59e0b22; color: #f59e0b; }
    .claim-conf.low { background: #6b728022; color: #9aa4b2; }
    /* 주장 검증 상태 뱃지 (C2) — .claim-conf 패턴과 동일 (2026-07-24) */
    .claim-status { flex: 0 0 auto; font-size: 11px; font-weight: 800; border-radius: 20px; padding: 2px 10px; }
    .claim-status.verified { background: #16a34a22; color: #22c55e; }
    .claim-status.unverified { background: #6b728022; color: #f59e0b; }
    .claim dl { display: grid; grid-template-columns: 74px 1fr; gap: 5px 14px; margin: 6px 0 0; font-size: 12.8px; }
    .claim dt { color: #5aa0ff; font-weight: 700; }
    .claim dd { margin: 0; color: var(--text, #e6ebf2); line-height: 1.55; }
    .claim dd ul { margin: 2px 0 0; padding-left: 16px; }
    .claim .stance { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border, #2a3444); font-size: 13px; }
    .claim .stance b { color: #22c55e; }
    /* 사고흐름 (펼치기) */
    .flow-stage { border: 1px solid var(--border, #2a3444); border-radius: 10px; margin: 8px 0; overflow: hidden; }
    .flow-stage > summary { cursor: pointer; padding: 11px 14px; font-size: 13px; font-weight: 600;
      display: flex; align-items: center; gap: 8px; list-style: none; }
    .flow-stage > summary::-webkit-details-marker { display: none; }
    .flow-stage > summary::before { content: "▸"; color: var(--muted-2, #8a94a3); font-size: 11px; transition: transform .12s; }
    .flow-stage[open] > summary::before { transform: rotate(90deg); }
    .flow-stage > summary .cnt { margin-left: auto; color: var(--muted-2, #8a94a3); font-size: 11.5px; font-weight: 500; }
    .flow-stage .body { padding: 4px 14px 12px 30px; }
    .flow-stage .note { color: var(--muted-2, #8a94a3); font-size: 12px; margin: 0 0 8px; }
    .flow-src { border-top: 1px dashed var(--border, #2a3444); margin-top: 6px; }
    .flow-src > summary { cursor: pointer; padding: 8px 2px; font-size: 12.5px; color: var(--text, #e6ebf2); list-style: none; display: flex; gap: 8px; align-items: center; }
    .flow-src > summary::-webkit-details-marker { display: none; }
    .flow-src > summary::before { content: "▸"; color: var(--muted-2, #8a94a3); font-size: 10px; }
    .flow-src[open] > summary::before { content: "▾"; }
    .flow-src > summary .cnt { margin-left: auto; color: var(--muted-2, #8a94a3); font-size: 11px; }
    .flow-item { padding: 4px 2px 4px 22px; font-size: 12.5px; color: var(--text, #e6ebf2); line-height: 1.5; }
    .flow-item .tag { display: inline-block; font-size: 10px; font-weight: 700; border-radius: 5px; padding: 0 6px; margin-right: 6px; }
    .flow-item .tag.pos { background: #16a34a22; color: #22c55e; }
    .flow-item .tag.neg { background: #dc262622; color: #f87171; }
    .flow-item .tag.neutral { background: #6b728022; color: #9aa4b2; }
    .flow-arrow { text-align: center; color: var(--muted-2, #8a94a3); font-size: 12px; margin: 2px 0; }
    .report-empty { color: var(--muted-2, #8a94a3); font-size: 13px; padding: 30px 8px; text-align: center; }
    /* 본문 가독성: 근거 라벨은 본문 흐름을 끊지 않게 작고 흐리게 (2026-07-24 사용자) */
    .report-article .src-ref { color: var(--muted-2, #8a94a3); font-size: 0.78em; opacity: .8; }
    .report-article table { display: block; overflow-x: auto; max-width: 100%; }
    /* ── v2 3축 카드 (format:"axes") — 세그먼트 탭 [거시|메모리|기타] (2026-07-24) ── */
    .axes-tabs { display: flex; gap: 4px; margin: 4px 0 14px;
      background: #161c26f2; border: 1px solid var(--border, #2a3444);
      border-radius: 13px; padding: 4px; box-shadow: 0 4px 14px #0005; }
    .axes-tab { flex: 1; border: 0; background: none; color: var(--muted-2, #8a94a3);
      border-radius: 10px; padding: 10px 0; font-size: 13.5px; font-weight: 700;
      cursor: pointer; transition: background .18s, color .18s; }
    .axes-tab:hover { color: var(--text, #e6ebf2); }
    .axes-tab.on { font-weight: 800; box-shadow: 0 1px 6px #0006; }
    .axes-tab.on.macro { background: #a78bfa; color: #17102a; }
    .axes-tab.on.memory { background: #5aa0ff; color: #0b1626; }
    .axes-tab.on.other { background: #f59e0b; color: #241804; }
    .axes-panel { display: none; }
    .axes-panel.on { display: block; animation: axfade .18s ease; }
    @keyframes axfade { from { opacity: 0; transform: translateY(5px); }
      to { opacity: 1; transform: none; } }
    .axis-card { box-sizing: border-box;
      border: 1px solid var(--border, #2a3444); border-radius: 14px; padding: 16px 15px;
      overflow-wrap: break-word; }
    /* 실패 카드는 세로 stretch 금지 — 이웃 카드 높이만큼 빈 테두리가 늘어나는 것 방지 */
    .axis-card.failed { border-color: #f59e0b55; background: #f59e0b08; align-self: flex-start; }
    .axis-fail { color: #f59e0b; font-size: 13.5px; font-weight: 800; margin: 10px 0 6px; }
    .axis-fail-reason { color: var(--muted-2, #8a94a3); font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; }
    /* 내비게이션 — ‹ 도트 › (화살표 클릭으로 이동, 2026-07-24 사용자) */
    .axes-dots { display: flex; align-items: center; justify-content: center; gap: 8px; margin: 10px 0 14px; }
    .axes-dots .dot { width: 8px; height: 8px; border-radius: 50%; background: #6b728055;
      cursor: pointer; transition: background .15s, transform .15s; }
    .axes-dots .dot.on { background: #5aa0ff; transform: scale(1.25); }
    .axes-arrow { border: 1px solid var(--border, #2a3444); background: none; border-radius: 8px;
      color: var(--muted-2, #8a94a3); font-size: 16px; line-height: 1; padding: 4px 12px;
      cursor: pointer; margin: 0 6px; }
    .axes-arrow:active, .axes-arrow:hover { color: #5aa0ff; border-color: #5aa0ff66; }
    .axes-arrow[disabled] { opacity: .3; cursor: default; }
    /* 축 라벨 칩 */
    .axis-chip { display: inline-block; font-size: 10.5px; font-weight: 800; letter-spacing: .4px;
      border-radius: 20px; padding: 2px 10px; }
    .axis-chip.macro { background: #a78bfa22; color: #a78bfa; }
    .axis-chip.memory { background: #5aa0ff22; color: #5aa0ff; }
    .axis-chip.other { background: #f59e0b22; color: #f59e0b; }
    .axis-title { font-size: 16.5px; font-weight: 800; line-height: 1.45; margin: 9px 0 10px; }
    .axis-phenom { font-size: 13.5px; line-height: 1.75; }
    .axis-phenom .src-ref { color: var(--muted-2, #8a94a3); font-size: 0.78em; opacity: .8; }
    .axis-phenom table { display: block; overflow-x: auto; max-width: 100%; }
    .axis-sec { font-size: 11px; font-weight: 800; letter-spacing: .4px; text-transform: uppercase;
      color: var(--muted-2, #8a94a3); margin: 14px 0 5px; }
    /* 추가 연구 (deep_dive) — 접이식 */
    /* 추가 연구 — 눈에 띄게: 보라 강조 박스 + 기본 펼침 (2026-07-24 사용자) */
    .axis-deep { border: 1px solid #a78bfa55; background: #a78bfa0d; border-left: 3px solid #a78bfa;
      border-radius: 10px; margin: 12px 0; }
    .axis-deep > summary { cursor: pointer; padding: 10px 12px; font-size: 13px; font-weight: 800;
      color: #a78bfa; list-style: none; display: flex; align-items: center; gap: 7px; }
    .axis-deep > summary::-webkit-details-marker { display: none; }
    .axis-deep > summary::before { content: "🔍"; font-size: 12px; }
    .axis-deep > summary::after { content: "▾"; color: #a78bfa; font-size: 11px; margin-left: 4px; }
    .axis-deep:not([open]) > summary::after { content: "▸"; }
    .axis-deep > summary .cnt { margin-left: auto; color: var(--muted-2, #8a94a3); font-size: 11px; font-weight: 500; }
    .axis-deep .body { padding: 0 12px 11px; font-size: 12.8px; line-height: 1.6; }
    .axis-deep .dd-topic { margin-bottom: 5px; }
    .axis-deep .dd-topic b { color: #5aa0ff; }
    .axis-deep .dd-conclusion { margin-bottom: 8px; }
    .axis-deep .dd-find { border-top: 1px dashed var(--border, #2a3444); padding: 8px 0 2px; }
    .axis-deep .dd-src { color: var(--muted-2, #8a94a3); font-size: 11px; margin-top: 3px; }
    .axis-tag { display: inline-block; font-size: 10px; font-weight: 700; border-radius: 5px; padding: 0 6px; margin-right: 6px; }
    .axis-tag.pos { background: #16a34a22; color: #22c55e; }
    .axis-tag.neutral { background: #6b728022; color: #9aa4b2; }
    /* 시나리오 박스 — positive 초록 / negative 빨강 좌보더 */
    .axis-scn { border-left: 3px solid; border-radius: 4px; padding: 10px 12px; margin: 10px 0; }
    .axis-scn.positive { border-left-color: #22c55e; background: #16a34a0f; }
    .axis-scn.negative { border-left-color: #f87171; background: #dc26260f; }
    .axis-scn .scn-label { font-size: 11px; font-weight: 800; letter-spacing: .3px; margin-bottom: 4px; }
    .axis-scn.positive .scn-label { color: #22c55e; }
    .axis-scn.negative .scn-label { color: #f87171; }
    .axis-scn .scn-thesis { font-size: 13.5px; font-weight: 600; line-height: 1.6; }
    /* 수혜/피해 목록 행 */
    .bene-row { padding: 8px 0 0; font-size: 12.8px; line-height: 1.5; }
    .bene-row .bname { font-weight: 700; }
    .bene-badge { display: inline-block; font-size: 9.5px; font-weight: 800; border-radius: 5px;
      padding: 1px 5px; margin-right: 4px; vertical-align: 1px; }
    .bene-badge.direct { background: #5aa0ff22; color: #5aa0ff; }
    .bene-badge.indirect { background: #6b728022; color: #9aa4b2; }
    .bene-badge.benefit { background: #16a34a22; color: #22c55e; }
    .bene-badge.damage { background: #dc262622; color: #f87171; }
    .bene-badge.neutral { background: #6b728018; color: #7b8593; }
    .bene-sub { color: var(--muted-2, #8a94a3); font-size: 11.8px; line-height: 1.55; margin: 2px 0 0 2px; }
    /* 관찰 신호 */
    .axis-watch ul { margin: 0; padding-left: 18px; font-size: 12.8px; line-height: 1.6; }
    .axis-watch li { margin: 3px 0; }
    /* 카드 출처 */
    .axis-srcs { border-top: 1px dashed var(--border, #2a3444); margin-top: 12px; padding-top: 8px; }
    .axis-srcs > summary { cursor: pointer; list-style: none; font-size: 11.5px; color: var(--muted-2, #8a94a3); }
    .axis-srcs > summary::-webkit-details-marker { display: none; }
    .axis-srcs .src-row { font-size: 11px; color: var(--muted-2, #8a94a3); margin-top: 4px; }
  `;
  document.head.appendChild(style);

  const view = () => document.getElementById("reportView");

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

  // "2026-07-21T21:00:00+09:00" → { date:"2026-07-21", time:"21:00", seq }
  function fmt(generatedAt) {
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(generatedAt || ""));
    return { date: m ? m[1] : "-", time: m ? m[2] : "--:--" };
  }

  // ISO 타임스탬프 → "07-24 02:36" (구간 표시용 — raw ISO는 읽기 괴로움)
  function fmtShort(iso) {
    const m = /^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ""));
    return m ? `${m[1]} ${m[2]}` : String(iso || "");
  }

  function confClass(c) {
    if (/높|high/i.test(c)) return "high";
    if (/낮|low/i.test(c)) return "low";
    return "mid";
  }

  // ── 렌더 ──────────────────────────────────────────────
  function renderList() {
    const el = view();
    if (state.error) { el.innerHTML = `<div class="report-wrap"><div class="report-feedback">${esc(state.error)}</div></div>`; return; }
    if (!state.reports) { el.innerHTML = `<div class="report-wrap"><div class="report-empty">불러오는 중…</div></div>`; return; }
    const rows = state.reports.map((r) => {
      const f = fmt(r.generatedAt);
      return `<div class="report-row" data-id="${esc(r.id)}">
        <span class="idx">${esc(f.date)} - <span class="seq">${esc(r.seq)}</span></span>
        <span class="mid">
          <span class="title">${esc(r.title || "메모리 반도체 시황")}</span>
          <span class="meta">주장 ${esc(r.claimCount || 0)}건</span>
        </span>
        <span class="when">${esc(f.time)}</span>
      </div>`;
    }).join("");
    el.innerHTML = `<div class="report-wrap">
      <div class="report-head"><h2>시황 리포트</h2><span class="sub">12시간마다 · 메모리 반도체 밸류체인 · 최신순</span></div>
      ${state.reports.length ? rows : `<div class="report-empty">아직 리포트가 없습니다.</div>`}
    </div>`;
    el.querySelectorAll(".report-row").forEach((row) => {
      row.addEventListener("click", () => goto(`#report-${row.dataset.id}`));
    });
  }

  // 주장 검증 상태 뱃지 (C2) — verified=검증됨(초록), unverified=미검증(주황), 기타=원문 표기
  function claimStatusHtml(status) {
    if (status === "verified") return `<span class="claim-status verified">검증됨</span>`;
    if (status === "unverified") return `<span class="claim-status unverified">미검증</span>`;
    return status ? `<span class="claim-status unverified">${esc(status)}</span>` : "";
  }

  function claimHtml(c) {
    const ev = Array.isArray(c.evidence) ? c.evidence : [];
    return `<div class="claim">
      <div class="claim-top">
        <div class="thesis">${esc(c.title || c.thesis || "")}</div>
        ${claimStatusHtml(c.status)}
        ${c.confidence ? `<span class="claim-conf ${confClass(c.confidence)}">확신도 ${esc(c.confidence)}</span>` : ""}
      </div>
      <dl>
        ${c.trigger ? `<dt>촉발</dt><dd>${esc(c.trigger)}</dd>` : ""}
        ${c.mechanism ? `<dt>논증</dt><dd>${esc(c.mechanism)}</dd>` : ""}
        ${ev.length ? `<dt>데이터 근거</dt><dd><ul>${ev.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></dd>` : ""}
        ${c.precedent ? `<dt>과거사례</dt><dd>${esc(c.precedent)}</dd>` : ""}
        ${c.counter ? `<dt>반론</dt><dd>${esc(c.counter)}</dd>` : ""}
      </dl>
      ${c.stance ? `<div class="stance"><b>스탠스</b> · ${esc(c.stance)}</div>` : ""}
    </div>`;
  }

  function itemHtml(it) {
    if (typeof it === "string") return `<div class="flow-item">${esc(it)}</div>`;
    const dir = (it.direction || "").toLowerCase();
    const tag = ["pos", "neg", "neutral"].includes(dir) ? `<span class="tag ${dir}">${esc(it.direction)}</span>` : "";
    return `<div class="flow-item">${tag}${esc(it.title || it.text || "")}</div>`;
  }

  function withMore(htmlItems, visible = 50) {
    // 처음 visible건 표시 + 나머지는 네이티브 더보기(전량 — 디버깅 우선, 2026-07-22)
    if (htmlItems.length <= visible) return htmlItems.join("");
    const head = htmlItems.slice(0, visible).join("");
    const rest = htmlItems.slice(visible);
    return `${head}<details class="flow-more">
      <summary>더보기 — 외 ${rest.length}건 전체 표시</summary>
      ${rest.join("")}
    </details>`;
  }

  function stageIoHtml(io) {
    // 파이프라인 관측치(additive io) — 드롭 사유·검증 사유 전량 펼치기 (2026-07-22)
    if (!io || typeof io !== "object") return "";
    let out = "";
    const health = io.collection_health;
    if (health && typeof health === "object") {
      const rows = Object.entries(health).map(([k, v]) =>
        `<div class="flow-item"><b>${esc(k)}</b>: ${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</div>`);
      out += `<details class="flow-src" open>
        <summary>수집 건강 — 비어있는 것/안 온 것<span class="cnt">${rows.length}항목</span></summary>
        ${rows.join("")}
      </details>`;
    }
    const anchors = Array.isArray(io.anchor_details) ? io.anchor_details : [];
    if (anchors.length) {
      out += `<details class="flow-src">
        <summary>수치 앵커 — 값·시점·출처<span class="cnt">${anchors.length}건</span></summary>
        <div style="overflow-x:auto"><table style="font-size:11px;border-collapse:collapse;width:100%">
          <tr><th style="text-align:left;padding:2px 6px">앵커</th><th style="text-align:right;padding:2px 6px">값</th><th style="text-align:right;padding:2px 6px">Δ%</th><th style="text-align:left;padding:2px 6px">기준시점</th><th style="text-align:left;padding:2px 6px">출처</th></tr>
          ${anchors.map((a) => `<tr>
            <td style="padding:2px 6px;white-space:nowrap">${esc(a.anchor_id || "")}</td>
            <td style="padding:2px 6px;text-align:right;white-space:nowrap">${esc(String(a.value ?? ""))}${esc(a.unit || "")}</td>
            <td style="padding:2px 6px;text-align:right">${a.delta_pct == null ? "—" : esc(Number(a.delta_pct).toFixed(1))}</td>
            <td style="padding:2px 6px;white-space:nowrap">${esc(a.as_of || a.period || "")}</td>
            <td style="padding:2px 6px">${esc(a.source || "")}</td>
          </tr>`).join("")}
        </table></div>
      </details>`;
    }
    const calls = Array.isArray(io.llm_calls) ? io.llm_calls : [];
    if (calls.length) {
      out += `<details class="flow-src">
        <summary>LLM 콜 전문 — 프롬프트·응답<span class="cnt">${calls.length}건</span></summary>
        ${calls.map((c, i) => `<details class="flow-src">
          <summary>콜 ${i + 1}${c.error ? " (실패)" : ""}</summary>
          <div class="flow-item"><b>지시</b><pre style="white-space:pre-wrap;font-size:11px">${esc(c.instructions || "")}</pre></div>
          <div class="flow-item"><b>프롬프트</b><pre style="white-space:pre-wrap;font-size:11px">${esc(c.prompt || "")}</pre></div>
          <div class="flow-item"><b>${c.error ? "오류" : "응답"}</b><pre style="white-space:pre-wrap;font-size:11px">${esc(c.error || (typeof c.response === "object" ? JSON.stringify(c.response, null, 1) : String(c.response ?? "")))}</pre></div>
        </details>`).join("")}
      </details>`;
    }
    const dropped = Array.isArray(io.dropped) ? io.dropped : [];
    if (dropped.length) {
      out += `<details class="flow-src">
        <summary>걸러진 항목<span class="cnt">${dropped.length}건</span></summary>
        ${withMore(dropped.map((d) =>
          `<div class="flow-item">${esc(d.title || "")} <span class="tag neg">${esc(d.reason || "")}</span></div>`))}
      </details>`;
    }
    const findings = Array.isArray(io.findings) ? io.findings : [];
    if (findings.length) {
      out += `<details class="flow-src" open>
        <summary>추가 조사 결과 — 답·출처<span class="cnt">${findings.length}건</span></summary>
        ${findings.map((f) => `<div class="flow-item">
          <b>${esc(f.qid)}</b> <span class="tag ${f.error ? "neg" : (f.label === "근거" ? "pos" : "neutral")}">${esc(f.error ? "실패" : f.label)}</span>
          <div style="white-space:pre-wrap">${esc(f.error || f.answer || "")}</div>
          ${(f.sources || []).map((s) => `<div style="font-size:11px">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>${s.published ? ` (${esc(s.published)})` : ""}</div>`).join("")}
        </div>`).join("")}
      </details>`;
    }
    const verdicts = Array.isArray(io.verdicts) ? io.verdicts : [];
    if (verdicts.length) {
      out += `<details class="flow-src">
        <summary>판정 사유<span class="cnt">${verdicts.length}건</span></summary>
        ${withMore(verdicts.map((v) =>
          `<div class="flow-item"><b>${esc(v.claim_id)}</b> ${esc(v.status)}${(v.reasons || []).length ? ` — ${esc(v.reasons.join("; "))}` : ""}</div>`))}
      </details>`;
    }
    return out;
  }

  function stageHtml(stage, i, total) {
    let inner = "";
    if (Array.isArray(stage.sources) && stage.sources.length) {
      inner = stage.sources.map((s) => {
        const items = Array.isArray(s.items) ? s.items : [];
        return `<details class="flow-src">
          <summary>${esc(s.name)}<span class="cnt">${items.length}건</span></summary>
          ${withMore(items.map(itemHtml))}
        </details>`;
      }).join("");
    } else if (Array.isArray(stage.items)) {
      inner = withMore(stage.items.map(itemHtml));
    }
    const io = stage.io && typeof stage.io === "object" ? stage.io : null;
    const count = io && typeof io.in_count === "number"
      ? `${io.in_count}→${io.out_count}`
      : String(Array.isArray(stage.sources)
        ? stage.sources.reduce((n, s) => n + (s.items ? s.items.length : 0), 0)
        : (Array.isArray(stage.items) ? stage.items.length : 0));
    const arrow = i < total - 1 ? `<div class="flow-arrow">↓</div>` : "";
    return `<details class="flow-stage"${i === 0 ? " open" : ""}>
      <summary>${esc(stage.label || stage.key)}<span class="cnt">${esc(count)}건</span></summary>
      <div class="body">
        ${stage.note ? `<p class="note">${esc(stage.note)}</p>` : ""}
        ${inner}
        ${stageIoHtml(io)}
      </div>
    </details>${arrow}`;
  }

  function overviewHtml(r) {
    if (!r.overview) return "";
    const body = Array.isArray(r.overview)
      ? `<ul>${r.overview.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
      : `<p>${esc(r.overview)}</p>`;
    return `<div class="report-section-label">종합</div><div class="report-overview">${body}</div>`;
  }

  function finalOpinionHtml(r) {
    const fo = r.finalOpinion;
    if (!fo) return "";
    const text = typeof fo === "string" ? fo : (fo.text || fo.view || "");
    const conf = (typeof fo === "object" && fo.confidence) ? fo.confidence : "";
    return `<div class="report-section-label">최종 의견</div>
      <div class="final-opinion">
        <div class="fo-text">${esc(text)}</div>
        ${conf ? `<span class="claim-conf ${confClass(conf)}">확신도 ${esc(conf)}</span>` : ""}
      </div>`;
  }

  function sanitizeHtml(html) {
    // LLM 생성 markdown → renderMarkdown은 URL 속성 탈출을 안 막는다
    // (codex P4 B1: href 큰따옴표 탈출로 onmouseover 주입 재현) — DOM 레벨 소독.
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

  function articleHtml(r) {
    // Phase 4 완결 글(markdown) — 본문 h1은 상단 타이틀과 중복이라 첫 h1 제거
    // (엔진 headline_from_article과 동일 규칙: 위치 무관 첫 h1).
    if (!r.article) return "";
    const md = String(r.article).replace(/^\s*# .*$\n?/m, "");
    let body = (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(md))
      : `<pre style="white-space:pre-wrap">${esc(md)}</pre>`;
    // 〔근거/가정/계산 …〕 라벨을 흐린 소형 스팬으로 — 본문 읽기 흐름 보존
    body = body.replace(/〔([^〕<]{0,200})〕/g, '<span class="src-ref">〔$1〕</span>');
    const meta = r.article_meta || {};
    // C3: 출처/실패 내역이 있으면 상세 병기 — null이면 기존 형태 유지
    const researchDetail = (meta.research_sourced != null && meta.research_failed != null)
      ? ` (출처 ${meta.research_sourced}·실패 ${meta.research_failed})` : "";
    const badge = [
      meta.research_ok != null ? `추가조사 ${meta.research_ok}건${researchDetail}` : "",
      (meta.unverified_numbers || []).length
        ? `⚠미확인 수치 ${meta.unverified_numbers.length}건` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="report-section-label">본문${badge ? ` <span class="cnt">${esc(badge)}</span>` : ""}</div>
      <div class="markdown-body report-article" style="font-size:13.5px;line-height:1.75;margin:4px 0 14px">${body}</div>`;
  }

  // C1: 검증 상태 배너 — 주장 검증 요약 + 최종 의견 한 줄 (본문 위 고정, 2026-07-24)
  function verifyBannerHtml(r) {
    const claims = Array.isArray(r.claims) ? r.claims : [];
    // publish_status(hold)는 claim 유무와 무관하게 표시 — claim 개수만 보면
    // 주장 없는 hold 리포트에 배너가 사라진다 (2026-07-24 codex M4)
    const hold = r.publish_status === "hold";
    if (!claims.length && !hold) return "";
    const verified = claims.filter((c) => c.status === "verified").length;
    const total = claims.length;
    let summary;
    if (!total) summary = "⚠ 발행 보류(hold) — 검증 통과 주장 없음";
    else if (verified === 0) summary = `⚠ 주장 ${total}건 모두 미검증`;
    else if (verified === total) summary = `주장 ${total}건 모두 검증 통과`;
    else summary = `주장 ${total}건 중 ${verified}건 검증 통과`;
    if (hold && total) summary += " · 발행 보류(hold)";
    const audit = (r.article_meta || {}).semantic_audit;
    const auditNote = (audit && audit.ok === false && (audit.problems || []).length)
      ? ` · 의미론 감사 위반 ${audit.problems.length}건` : "";
    const fo = r.finalOpinion;
    const foText = typeof fo === "string" ? fo : ((fo && (fo.text || fo.view)) || "");
    return `<div class="verify-banner">${esc(summary)}${esc(auditNote)}${foText ? ` · 최종 의견: ${esc(foText)}` : ""}</div>`;
  }

  // ── v2 3축 카드 (format:"axes") ───────────────────────
  const AXIS_LABELS = { macro: "거시", memory: "메모리", other: "기타" };

  // markdown → 소독 HTML + 〔…〕 라벨 축소 (articleHtml과 동일 규칙 — 현상 분석용)
  function mdToHtml(md) {
    const body = (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(String(md || "")))
      : `<pre style="white-space:pre-wrap">${esc(md || "")}</pre>`;
    return body.replace(/〔([^〕<]{0,200})〕/g, '<span class="src-ref">〔$1〕</span>');
  }

  // 추가 연구(deep_dive) — topic/findings 있을 때만 접이식으로
  function deepDiveHtml(dd) {
    if (!dd || typeof dd !== "object") return "";
    const findings = Array.isArray(dd.findings) ? dd.findings : [];
    if (!dd.topic && !findings.length) return "";
    const finds = findings.map((f) => `<div class="dd-find">
      <span class="axis-tag ${f.label === "근거" ? "pos" : "neutral"}">${esc(f.label || "가정")}</span>${esc(f.answer || "")}
      ${(Array.isArray(f.sources) ? f.sources : []).map((s) => `<div class="dd-src">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>${s.published ? ` (${esc(s.published)})` : ""}</div>`).join("")}
    </div>`).join("");
    return `<details class="axis-deep" open>
      <summary>추가 연구${dd.topic ? ` — ${esc(dd.topic)}` : ""}${findings.length ? `<span class="cnt">${findings.length}건</span>` : ""}</summary>
      <div class="body">
        ${dd.research_failed ? `<div class="dd-src" style="color:#f59e0b">⚠ 웹 연구 실패/생략 — ${esc(dd.research_failed)} (관련 논점은 가정)</div>` : ""}
        ${dd.conclusion ? `<div class="dd-conclusion"><b style="color:#5aa0ff">결론</b> · ${esc(dd.conclusion)}</div>` : ""}
        ${finds}
      </div>
    </details>`;
  }

  // 시나리오 박스 + 수혜/피해 목록 — positive 초록 / negative 빨강 좌보더
  function scenarioHtml(s) {
    const pos = s.polarity === "positive";
    const bens = Array.isArray(s.beneficiaries) ? s.beneficiaries : [];
    const rows = bens.map((b) => {
      const sub = [b.rationale, b.financials].filter(Boolean).join(" · ");
      return `<div class="bene-row">
        <span class="bene-badge ${b.direction === "direct" ? "direct" : "indirect"}">${b.direction === "direct" ? "직접" : "간접"}</span><span class="bene-badge ${b.polarity === "damage" ? "damage" : "benefit"}">${b.polarity === "damage" ? "피해" : "수혜"}</span><span class="bene-badge neutral">${b.kind === "stock" ? "종목" : "섹터"}</span> <span class="bname">${esc(b.name || "")}</span>
        ${sub ? `<div class="bene-sub">${esc(sub)}</div>` : ""}
      </div>`;
    }).join("");
    return `<div class="axis-scn ${pos ? "positive" : "negative"}">
      <div class="scn-label">${pos ? "긍정 시나리오" : "부정 시나리오"}</div>
      <div class="scn-thesis">${esc(s.thesis || "")}</div>
      ${rows}
    </div>`;
  }

  function axisCardHtml(c) {
    const axis = ["macro", "memory", "other"].includes(c.axis) ? c.axis : "other";
    const chip = `<span class="axis-chip ${axis}">${esc(AXIS_LABELS[c.axis] || c.axis || "?")}</span>`;
    // 축 생성 실패 카드 — 사유만 표시
    if (c.error) {
      return `<div class="axis-card failed">${chip}
        <div class="axis-fail">⚠ 이 축 생성 실패</div>
        <div class="axis-fail-reason">${esc(c.error)}</div>
      </div>`;
    }
    const scns = Array.isArray(c.scenarios) ? c.scenarios : [];
    const watch = Array.isArray(c.watch_signals) ? c.watch_signals : [];
    const srcs = Array.isArray(c.sources) ? c.sources : [];
    // 순서(2026-07-24 사용자): 현상 → 긍정 시나리오 → 부정 시나리오 → 추가 연구
    const ordered = [...scns].sort((a, b) =>
      (a.polarity === "positive" ? 0 : 1) - (b.polarity === "positive" ? 0 : 1));
    return `<div class="axis-card">
      <div class="axis-title">${esc(c.title || "")}</div>
      ${c.phenomenon ? `<div class="markdown-body axis-phenom">${mdToHtml(c.phenomenon)}</div>` : ""}
      ${ordered.map(scenarioHtml).join("")}
      ${deepDiveHtml(c.deep_dive)}
      ${watch.length ? `<div class="axis-watch"><div class="axis-sec">관찰 신호</div><ul>${watch.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      ${srcs.length ? `<details class="axis-srcs"><summary>추가 연구 출처 ${srcs.length}건 (웹 검증)</summary>
        ${srcs.map((s) => `<div class="src-row">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>${s.published ? ` (${esc(s.published)})` : ""}</div>`).join("")}
      </details>` : ""}
    </div>`;
  }

  // 탭 형태 [거시][메모리][기타] — 스와이프 대신 탭 전환 (2026-07-24 사용자)
  function axesHtml(cards) {
    return `<div class="axes-tabs">${cards.map((c, i) =>
      `<button class="axes-tab ${esc(c.axis)}${i === 0 ? " on" : ""}" data-i="${i}">${esc(AXIS_LABELS[c.axis] || c.axis)}</button>`).join("")}</div>
      <div class="axes-panels">${cards.map((c, i) =>
        `<div class="axes-panel${i === 0 ? " on" : ""}" data-i="${i}">${axisCardHtml(c)}</div>`).join("")}</div>`;
  }

  function bindAxes() {
    const tabs = [...view().querySelectorAll(".axes-tab")];
    const panels = [...view().querySelectorAll(".axes-panel")];
    if (!tabs.length) return;
    tabs.forEach((t, i) => t.addEventListener("click", () => {
      tabs.forEach((x, k) => x.classList.toggle("on", k === i));
      panels.forEach((p, k) => p.classList.toggle("on", k === i));
    }));
  }

  function renderDetail() {
    const el = view();
    const r = state.report;
    if (state.error) { el.innerHTML = `<div class="report-wrap"><button class="report-back">← 목록</button><div class="report-feedback">${esc(state.error)}</div></div>`; bindBack(); return; }
    if (!r) { el.innerHTML = `<div class="report-wrap"><div class="report-empty">불러오는 중…</div></div>`; return; }
    const f = fmt(r.generatedAt);
    const claims = Array.isArray(r.claims) ? r.claims : [];
    const stages = (r.pipeline && Array.isArray(r.pipeline.stages)) ? r.pipeline.stages : [];
    const flowHtml = `<div class="report-section-label">사고흐름</div>
      <div class="section-hint">각 단계를 눌러 펼치면 raw·필터의 근거를 그대로 볼 수 있습니다 (피드백용).</div>
      ${stages.length ? stages.map((s, i) => stageHtml(s, i, stages.length)).join("") : `<div class="report-empty">파이프라인 기록 없음</div>`}`;
    // v2 3축 카드 — 주장 카드·최종의견·종합·본문·검증 배너 대신 스와이프 UI만 (사고흐름 디버그는 유지)
    if (r.format === "axes" && Array.isArray(r.cards) && r.cards.length) {
      el.innerHTML = `<div class="report-wrap">
        <button class="report-back">← 목록</button>
        <div class="report-title">${esc(r.title || "메모리 반도체 시황")}</div>
        <div class="report-when">${esc(f.date)} - ${esc(r.seq)} (${esc(f.time)})${r.window ? ` · 구간 ${esc(fmtShort(r.window.from))} ~ ${esc(fmtShort(r.window.to))}` : ""}</div>
        ${axesHtml(r.cards)}
        ${flowHtml}
      </div>`;
      bindBack();
      bindAxes();
      return;
    }
    el.innerHTML = `<div class="report-wrap">
      <button class="report-back">← 목록</button>
      <div class="report-title">${esc(r.title || "메모리 반도체 시황")}</div>
      <div class="report-when">${esc(f.date)} - ${esc(r.seq)} (${esc(f.time)})${r.window ? ` · 구간 ${esc(fmtShort(r.window.from))} ~ ${esc(fmtShort(r.window.to))}` : ""}</div>

      ${verifyBannerHtml(r)}
      ${articleHtml(r)}
      ${overviewHtml(r)}
      ${finalOpinionHtml(r)}

      <div class="report-section-label">최종 주장 ${claims.length}개</div>
      ${claims.length ? claims.map(claimHtml).join("") : `<div class="report-empty">주장 없음</div>`}

      ${flowHtml}
    </div>`;
    bindBack();
  }

  function bindBack() {
    const b = view().querySelector(".report-back");
    if (b) b.addEventListener("click", () => goto("#report"));
  }

  // ── 라우팅 ────────────────────────────────────────────
  function syncFromHash() {
    const hash = decodeURIComponent(location.hash || "#report");
    if (hash.startsWith("#report-")) {
      state.subview = "detail";
      state.detailId = hash.slice("#report-".length);
    } else {
      state.subview = "list";
      state.detailId = "";
    }
  }

  function goto(hash) {
    history.pushState({ view: "report", reportPath: hash }, "", hash);
    load();
  }

  async function load() {
    syncFromHash();
    state.error = "";
    const el = view();
    if (!el) return;
    if (state.subview === "detail") {
      if (!state.report || state.report.id !== state.detailId) {
        state.report = null;
        renderDetail();
        try {
          const data = await api(`/api/market-reports/${encodeURIComponent(state.detailId)}`);
          state.report = data.report;
        } catch (e) { state.error = e.message; }
      }
      renderDetail();
    } else {
      renderList();
      try {
        const data = await api("/api/market-reports");
        state.reports = data.reports || [];
      } catch (e) { state.error = e.message; state.reports = []; }
      renderList();
    }
  }

  window.AttnReport = { load };

  // 부트 경합 가드 — 앱 초기화가 스크립트 로드보다 먼저 끝나면 빈 화면 (history.js와 동일)
  if (/^#report(-|$)/.test(location.hash || "")) load();
})();
