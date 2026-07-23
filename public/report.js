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

  function claimHtml(c) {
    const ev = Array.isArray(c.evidence) ? c.evidence : [];
    return `<div class="claim">
      <div class="claim-top">
        <div class="thesis">${esc(c.title || c.thesis || "")}</div>
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
    const body = (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(md))
      : `<pre style="white-space:pre-wrap">${esc(md)}</pre>`;
    const meta = r.article_meta || {};
    const badge = [
      meta.research_ok != null ? `추가조사 ${meta.research_ok}건` : "",
      (meta.unverified_numbers || []).length
        ? `⚠미확인 수치 ${meta.unverified_numbers.length}건` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="report-section-label">본문${badge ? ` <span class="cnt">${esc(badge)}</span>` : ""}</div>
      <div class="markdown-body report-article" style="font-size:13.5px;line-height:1.75;margin:4px 0 14px">${body}</div>`;
  }

  function renderDetail() {
    const el = view();
    const r = state.report;
    if (state.error) { el.innerHTML = `<div class="report-wrap"><button class="report-back">← 목록</button><div class="report-feedback">${esc(state.error)}</div></div>`; bindBack(); return; }
    if (!r) { el.innerHTML = `<div class="report-wrap"><div class="report-empty">불러오는 중…</div></div>`; return; }
    const f = fmt(r.generatedAt);
    const claims = Array.isArray(r.claims) ? r.claims : [];
    const stages = (r.pipeline && Array.isArray(r.pipeline.stages)) ? r.pipeline.stages : [];
    el.innerHTML = `<div class="report-wrap">
      <button class="report-back">← 목록</button>
      <div class="report-title">${esc(r.title || "메모리 반도체 시황")}</div>
      <div class="report-when">${esc(f.date)} - ${esc(r.seq)} (${esc(f.time)})${r.window ? ` · 구간 ${esc(r.window.from || "")} ~ ${esc(r.window.to || "")}` : ""}</div>

      ${articleHtml(r)}
      ${overviewHtml(r)}
      ${finalOpinionHtml(r)}

      <div class="report-section-label">최종 주장 ${claims.length}개</div>
      ${claims.length ? claims.map(claimHtml).join("") : `<div class="report-empty">주장 없음</div>`}

      <div class="report-section-label">사고흐름</div>
      <div class="section-hint">각 단계를 눌러 펼치면 raw·필터의 근거를 그대로 볼 수 있습니다 (피드백용).</div>
      ${stages.length ? stages.map((s, i) => stageHtml(s, i, stages.length)).join("") : `<div class="report-empty">파이프라인 기록 없음</div>`}
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
})();
