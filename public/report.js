// 시황 리포트 탭 — 거시와 당일 핵심 토픽을 읽는 범용 리포트 뷰어
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
    .report-head .sub { min-width: 0; color: var(--muted-2, #8a94a3); font-size: 12px;
      overflow-wrap: anywhere; }
    .report-feedback { color: #f59e0b; font-size: 12px; min-height: 16px; }
    /* 리스트 */
    .report-row { display: flex; gap: 12px; align-items: baseline; padding: 13px 8px;
      border-bottom: 1px solid var(--border, #2a3444); color: inherit; cursor: pointer;
      text-decoration: none; }
    .report-row:hover { background: #ffffff0a; }
    .report-row:focus-visible { outline: 2px solid #5aa0ff; outline-offset: -2px;
      background: #5aa0ff0d; }
    .report-row .idx { flex: 0 0 auto; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 700; }
    .report-row .idx .seq { color: #5aa0ff; }
    .report-row .mid { flex: 1; min-width: 0; }
    .report-row .title { display: block; font-size: 13.5px; }
    .report-row .meta { display: block; color: var(--muted-2, #8a94a3); font-size: 12px; margin-top: 3px; }
    .report-row .when { flex: 0 0 auto; color: var(--muted-2, #8a94a3); font-size: 11.5px; font-variant-numeric: tabular-nums; }
    /* 상세 */
    .report-back { border: 0; background: none; color: var(--muted-2, #8a94a3); font-size: 13px; cursor: pointer; padding: 4px 0; margin-bottom: 6px; }
    .report-back:hover { color: var(--text, #e6ebf2); }
    .report-title-block { margin: 2px 0 4px; }
    .report-title { font-size: 20px; font-weight: 800; line-height: 1.48; overflow-wrap: anywhere; }
    .report-title.is-collapsed { display: -webkit-box; -webkit-box-orient: vertical;
      -webkit-line-clamp: 3; overflow: hidden; }
    .report-title-toggle, .axis-phenom-toggle { border: 0; background: none; color: #5aa0ff;
      cursor: pointer; font-size: 12px; font-weight: 700; line-height: 1.4; padding: 5px 0; }
    .report-title-toggle:hover, .axis-phenom-toggle:hover { color: var(--text, #e6ebf2); }
    .report-title-toggle:focus-visible, .axis-phenom-toggle:focus-visible,
    .axes-tab:focus-visible, .report-process > summary:focus-visible,
    .axis-deep > summary:focus-visible, .axis-analysis > summary:focus-visible,
    .scenario-impact > summary:focus-visible, .editorial-nav-card:focus-visible,
    .editorial-provenance > summary:focus-visible, .dd-sources > summary:focus-visible,
    .dd-numbers > summary:focus-visible {
      outline: 2px solid #5aa0ff; outline-offset: 2px; }
    .report-when { color: var(--muted-2, #8a94a3); font-size: 12px; margin-bottom: 16px; }
    /* 리포트 요약 — 한 줄 결론에서 각 관점으로 바로 이동한다. */
    .editorial-summary { border: 1px solid #5aa0ff55; border-radius: 16px; padding: 17px;
      margin: 8px 0 18px; background: linear-gradient(145deg, #5aa0ff12, #a78bfa0a 58%, transparent); }
    .editorial-heading { margin: 0; color: #8dbdff; font-size: 11px; font-weight: 850;
      letter-spacing: .45px; }
    .editorial-conclusion { margin: 11px 0 15px; border-left: 3px solid #5aa0ff;
      padding: 3px 0 3px 12px; }
    .editorial-conclusion-label { display: block; margin-bottom: 4px; color: var(--muted-2, #8a94a3);
      font-size: 10px; font-weight: 850; letter-spacing: .4px; }
    .editorial-deck { font-size: 15px; font-weight: 680; line-height: 1.68; }
    .editorial-takeaways { display: grid; grid-template-columns: 1fr; gap: 8px; }
    .editorial-nav-card { appearance: none; width: 100%; min-width: 0; border: 1px solid var(--border, #2a3444);
      border-radius: 11px; background: color-mix(in srgb, var(--surface-2) 82%, transparent);
      color: inherit; padding: 11px 12px; text-align: left; cursor: pointer; }
    .editorial-nav-card:hover { border-color: #5aa0ff66; background: #5aa0ff0d; }
    .editorial-nav-top { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
    .editorial-nav-card .label { font-size: 10.5px;
      font-weight: 850; letter-spacing: .35px; }
    .editorial-nav-card.macro .label { color: #c4b5fd; }
    .editorial-nav-card.memory .label { color: #8dbdff; }
    .editorial-nav-card.other .label { color: #fbbf24; }
    .editorial-nav-card.topic1 .label { color: #67e8f9; }
    .editorial-nav-card.topic2 .label { color: #f0abfc; }
    .editorial-nav-arrow { margin-left: auto; color: var(--muted-2, #8a94a3); font-size: 12px; }
    .editorial-nav-card .text { display: block; font-size: 12.5px; line-height: 1.58; }
    .editorial-provenance { margin-top: 12px; border-top: 1px solid var(--border, #2a3444); padding-top: 9px;
      color: var(--muted-2, #8a94a3); font-size: 11px; }
    .editorial-provenance > summary { cursor: pointer; list-style: none; display: flex; align-items: center;
      gap: 6px; width: fit-content; min-height: 28px; color: var(--muted-2, #8a94a3); font-weight: 700; }
    .editorial-provenance > summary::-webkit-details-marker { display: none; }
    .editorial-provenance > summary::before { content: "+"; width: 14px; color: #8dbdff; }
    details.editorial-provenance > summary::after { content: none; }
    .editorial-provenance[open] > summary::before { content: "−"; }
    .editorial-provenance-body { display: grid; gap: 6px; margin: 5px 0 2px 20px; line-height: 1.5; }
    .editorial-provenance-title { overflow-wrap: anywhere; }
    .editorial-provenance a { width: fit-content; color: #8dbdff; text-decoration: none; font-weight: 700; }
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
    /* 생성·검증 과정: 일반 독서 흐름에서는 한 단계 아래로 접어 둔다. */
    .report-process { border: 1px solid var(--border, #2a3444); border-radius: 12px;
      margin: 22px 0 8px; background: color-mix(in srgb, var(--surface-2) 72%, transparent); overflow: hidden; }
    .report-process > summary { cursor: pointer; display: flex; align-items: center; gap: 8px;
      list-style: none; padding: 12px 14px; color: var(--muted-2, #8a94a3);
      font-size: 12.5px; font-weight: 750; }
    .report-process > summary::-webkit-details-marker { display: none; }
    .report-process > summary::before { content: "▸"; font-size: 10px; transition: transform .12s; }
    .report-process[open] > summary::before { transform: rotate(90deg); }
    .report-process > summary .cnt { margin-left: auto; font-size: 11px; font-weight: 500; }
    .report-process-body { border-top: 1px solid var(--border, #2a3444); padding: 12px 14px 14px; }
    .report-process-placeholder { color: var(--muted-2, #8a94a3); font-size: 12px; padding: 6px 0; }
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
    .axes-tabs { position: sticky; top: 8px; z-index: 20; display: flex; gap: 4px;
      margin: 8px 0 14px; background: color-mix(in srgb, var(--surface-2) 94%, transparent);
      border: 1px solid var(--border, #2a3444);
      border-radius: 13px; padding: 4px; box-shadow: 0 4px 14px #0008;
      backdrop-filter: blur(12px); }
    .axes-tab { flex: 1; border: 0; background: none; color: var(--muted-2, #8a94a3);
      border-radius: 10px; padding: 10px 0; font-size: 13.5px; font-weight: 700;
      min-width: 0; line-height: 1.35; overflow-wrap: anywhere; white-space: normal;
      cursor: pointer; transition: background .18s, color .18s; }
    .axes-tab:hover { color: var(--text, #e6ebf2); }
    .axes-tab.on { font-weight: 800; box-shadow: 0 1px 6px #0006; }
    .axes-tab.on.macro { background: #a78bfa; color: #17102a; }
    .axes-tab.on.memory { background: #5aa0ff; color: #0b1626; }
    .axes-tab.on.other { background: #f59e0b; color: #241804; }
    .axes-tab.on.topic1 { background: #22d3ee; color: #082f49; }
    .axes-tab.on.topic2 { background: #e879f9; color: #3b0764; }
    .axes-panel { display: none; scroll-margin-top: 68px; }
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
    .axis-chip.topic1 { background: #22d3ee22; color: #67e8f9; }
    .axis-chip.topic2 { background: #e879f922; color: #f0abfc; }
    .axis-title { font-size: 18px; font-weight: 800; line-height: 1.5; margin: 9px 0 16px; }
    .axis-brief { border-radius: 13px; padding: 13px; margin: 0 0 14px;
      background: color-mix(in srgb, var(--surface-2) 84%, #5aa0ff 4%);
      border: 1px solid #5aa0ff2f; }
    .axis-brief-label { color: #8dbdff; font-size: 10.5px; font-weight: 850;
      letter-spacing: .4px; text-transform: uppercase; }
    .axis-brief-summary { margin: 6px 0 11px; font-size: 13.5px; line-height: 1.65; }
    .axis-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .axis-metric { min-width: 0; border: 1px solid var(--border, #2a3444); border-radius: 9px;
      background: color-mix(in srgb, var(--surface) 76%, transparent); padding: 9px; }
    .axis-metric .metric-label, .axis-metric .metric-context { display: block; color: var(--muted-2, #8a94a3);
      font-size: 10px; line-height: 1.35; }
    .axis-metric .metric-value { display: block; margin: 3px 0; font-size: 16px; font-weight: 850;
      font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .axis-metric.positive .metric-value { color: #4ade80; }
    .axis-metric.negative .metric-value { color: #fb7185; }
    .axis-metric.warning .metric-value { color: #fbbf24; }
    .axis-causal-flow { display: grid; grid-template-columns: 1fr; gap: 17px; margin-top: 11px; }
    .axis-flow-node { position: relative; min-width: 0; border-radius: 9px; padding: 9px 10px;
      border: 1px solid var(--border, #2a3444); background: color-mix(in srgb, var(--surface) 82%, transparent); }
    .axis-flow-node:not(:last-child)::after { content: "↓"; position: absolute; left: 50%; bottom: -17px;
      transform: translateX(-50%); color: var(--muted-2, #8a94a3); font-size: 12px; }
    .axis-flow-node .flow-label { display: block; font-size: 11px; font-weight: 800; }
    .axis-flow-node .flow-detail { display: block; color: var(--muted-2, #8a94a3); font-size: 10.5px;
      line-height: 1.4; margin-top: 2px; }
    .axis-flow-node.positive .flow-label { color: #4ade80; }
    .axis-flow-node.negative .flow-label { color: #fb7185; }
    .axis-flow-node.warning .flow-label { color: #fbbf24; }
    .axis-bottom-line { border-left: 3px solid #5aa0ff; margin-top: 11px; padding: 7px 0 7px 10px;
      font-size: 12.5px; font-weight: 700; line-height: 1.55; }
    .axis-section-title { display: flex; align-items: center; gap: 7px; margin: 18px 0 8px;
      color: var(--text, #e6ebf2); font-size: 12px; font-weight: 800; letter-spacing: .25px; }
    .axis-section-title::before { content: ""; width: 3px; height: 13px; border-radius: 2px;
      background: #5aa0ff; }
    .axis-phenom-shell { position: relative; }
    .axis-phenom-shell.is-collapsed .axis-phenom { max-height: 22rem; overflow: hidden; }
    .axis-phenom-shell.is-collapsed::after { content: ""; position: absolute; inset: auto 0 0;
      height: 5rem; pointer-events: none;
      background: linear-gradient(to bottom, transparent, var(--surface, #111720)); }
    .axis-phenom { font-size: 14px; line-height: 1.82; }
    .axis-phenom h2 { margin: 26px 0 11px; padding-bottom: 8px;
      border-bottom: 1px solid var(--border, #2a3444); font-size: 15px; line-height: 1.45; }
    .axis-phenom h2:first-child { margin-top: 0; }
    .axis-phenom h3 { margin: 22px 0 9px; font-size: 14px; }
    .axis-phenom p { margin: 11px 0; }
    .axis-phenom ul, .axis-phenom ol { margin: 9px 0 18px; padding-left: 21px; }
    .axis-phenom li { margin: 8px 0; padding-left: 2px; }
    .axis-phenom strong { color: color-mix(in srgb, var(--text, #e6ebf2) 94%, white); }
    .axis-phenom .src-ref { color: var(--muted-2, #8a94a3); font-size: 0.78em; opacity: .8; }
    .axis-phenom table { display: block; overflow-x: auto; max-width: 100%; }
    .axis-analysis { border: 1px solid var(--border, #2a3444); border-radius: 12px;
      margin: 14px 0; overflow: hidden; background: color-mix(in srgb, var(--surface-2) 76%, transparent); }
    .axis-analysis > summary { cursor: pointer; list-style: none; display: flex; align-items: center;
      gap: 8px; padding: 12px 14px; color: var(--text, #e6ebf2); font-size: 13px; font-weight: 800; }
    .axis-analysis > summary::-webkit-details-marker { display: none; }
    .axis-analysis > summary::before { content: "▸"; color: #8dbdff; font-size: 10px; }
    .axis-analysis > summary::after { content: none; }
    .axis-analysis[open] > summary::before { transform: rotate(90deg); }
    .axis-analysis > summary .cnt { margin-left: auto; border-radius: 999px; padding: 2px 8px;
      background: #5aa0ff17; color: #8dbdff; font-size: 10.5px; font-weight: 650; white-space: nowrap; }
    .axis-analysis .axis-analysis-body { border-top: 1px solid var(--border, #2a3444); padding: 0; }
    .axis-reading-body { box-sizing: border-box; width: 100%; padding: 18px 18px 23px; }
    .axis-original-title { margin: 0 0 20px; border: 1px solid #5aa0ff30; border-radius: 9px;
      background: #5aa0ff0b; padding: 12px 13px; }
    .axis-original-kicker { display: block; color: #8dbdff; font-size: 10px; font-weight: 850;
      letter-spacing: .38px; }
    .axis-original-text { margin-top: 5px; color: var(--text, #e6ebf2); font-size: 14px;
      font-weight: 700; line-height: 1.65; }
    .analysis-sections { display: grid; gap: 12px; }
    .analysis-section { border: 1px solid var(--border, #2a3444); border-radius: 10px;
      background: color-mix(in srgb, var(--surface, #111720) 76%, transparent); padding: 14px 15px 15px; }
    .analysis-section-title { margin-bottom: 9px; color: #8dbdff; font-size: 12px;
      font-weight: 850; letter-spacing: .2px; }
    .analysis-section .axis-phenom > :first-child { margin-top: 0; }
    .analysis-section .axis-phenom > :last-child { margin-bottom: 0; }
    .axis-sec { font-size: 11px; font-weight: 800; letter-spacing: .4px; text-transform: uppercase;
      color: var(--muted-2, #8a94a3); margin: 14px 0 5px; }
    /* 추가 연구 (deep_dive) — 접이식 */
    /* 추가 연구 — 강조는 유지하되 독서 첫 화면에서는 접힌 상태로 시작한다. */
    .axis-deep { border: 1px solid #a78bfa55; background: #a78bfa0d; border-left: 3px solid #a78bfa;
      border-radius: 10px; margin: 12px 0; }
    .axis-deep > summary { box-sizing: border-box; cursor: pointer; padding: 11px 12px; font-size: 13px;
      font-weight: 800; color: #a78bfa; list-style: none; display: flex; align-items: center;
      gap: 7px; white-space: nowrap; }
    .axis-deep > summary::-webkit-details-marker { display: none; }
    .axis-deep > summary::before { content: ""; width: 3px; height: 13px; border-radius: 2px;
      background: #a78bfa; }
    .axis-deep > summary::after { content: "▾"; color: #a78bfa; font-size: 11px; margin-left: 4px; }
    .axis-deep:not([open]) > summary::after { content: "▸"; }
    .axis-deep-heading { flex: 0 0 auto; }
    .axis-deep > summary .cnt { margin-left: auto; border-radius: 999px; padding: 2px 8px;
      background: #a78bfa17; color: #c4b5fd; font-size: 10.5px; font-weight: 650; }
    .axis-deep .body { border-top: 1px solid #a78bfa2b; padding: 14px;
      font-size: 12.8px; line-height: 1.68; }
    .axis-deep .dd-topic { margin: 0 0 12px; border-radius: 9px; padding: 11px 12px;
      background: #a78bfa0d; }
    .dd-topic-label { display: block; margin-bottom: 4px; color: #c4b5fd; font-size: 10px;
      font-weight: 850; letter-spacing: .35px; }
    .dd-topic-text { color: var(--text, #e6ebf2); font-weight: 650; }
    .axis-deep .dd-conclusion { margin-bottom: 12px; border-left: 2px solid #5aa0ff;
      border-radius: 0 8px 8px 0; background: #5aa0ff0a; padding: 9px 10px; }
    .axis-deep .dd-find-card { border: 1px solid var(--border, #2a3444); border-radius: 9px;
      background: color-mix(in srgb, var(--surface, #111720) 72%, transparent); padding: 12px; }
    .axis-deep .dd-find-card + .dd-find-card { margin-top: 9px; }
    .axis-deep .dd-find-heading { margin-bottom: 8px; }
    .axis-deep .dd-answer { min-width: 0; color: color-mix(in srgb, var(--text, #e6ebf2) 92%, transparent); }
    .axis-deep .dd-answer-paragraph { margin: 0; }
    .axis-deep .dd-answer-paragraph + .dd-answer-paragraph { margin-top: 8px; }
    .axis-deep .dd-src { color: var(--muted-2, #8a94a3); font-size: 11px; margin-top: 3px; }
    .dd-sources { margin-top: 10px; border-top: 1px dashed var(--border, #2a3444); padding-top: 6px; }
    .dd-sources > summary { cursor: pointer; width: fit-content; min-height: 27px; display: flex;
      align-items: center; gap: 5px; list-style: none; color: var(--muted-2, #8a94a3); font-size: 11px; font-weight: 750; }
    .dd-sources > summary::-webkit-details-marker { display: none; }
    .dd-sources > summary::before { content: "+"; width: 13px; color: #c4b5fd; }
    details.dd-sources > summary::after { content: none; }
    .dd-sources[open] > summary::before { content: "−"; }
    .dd-sources-list { padding: 1px 0 3px 18px; }
    .dd-numbers { margin-top: 9px; }
    .dd-numbers > summary { cursor: pointer; width: fit-content; min-height: 27px; display: flex;
      align-items: center; list-style: none; color: #8dbdff; font-size: 11px; font-weight: 750; }
    .dd-numbers > summary::-webkit-details-marker { display: none; }
    .dd-numbers > summary::before { content: "+"; width: 13px; }
    details.dd-numbers > summary::after { content: none; }
    .dd-numbers[open] > summary::before { content: "−"; }
    .dd-number-list { margin: 3px 0 2px; padding-left: 29px; color: var(--muted-2, #8a94a3);
      font-size: 11px; line-height: 1.55; }
    .dd-number + .dd-number { margin-top: 4px; }
    .axis-tag { display: inline-block; font-size: 10px; font-weight: 700; border-radius: 5px; padding: 0 6px; margin-right: 6px; }
    .axis-tag.pos { background: #16a34a22; color: #22c55e; }
    .axis-tag.neutral { background: #6b728022; color: #9aa4b2; }
    /* 시나리오 박스 — positive 초록 / negative 빨강 좌보더 */
    .axis-scenarios { display: grid; grid-template-columns: 1fr; gap: 12px; align-items: start; }
    .axis-scn { border: 1px solid transparent; border-left: 3px solid; border-radius: 10px;
      padding: 15px 16px; margin: 0; }
    .axis-scn.positive { border-left-color: #22c55e; background: #16a34a0f; }
    .axis-scn.negative { border-left-color: #f87171; background: #dc26260f; }
    .axis-scn .scn-label { font-size: 11px; font-weight: 850; letter-spacing: .35px; margin-bottom: 10px; }
    .axis-scn.positive .scn-label { color: #22c55e; }
    .axis-scn.negative .scn-label { color: #f87171; }
    .axis-scn .scn-thesis { font-size: 13.5px; font-weight: 600; line-height: 1.6; }
    .axis-scn .scn-condition, .axis-scn .scn-outcome { display: grid;
      grid-template-columns: 62px minmax(0, 1fr); gap: 9px; align-items: start; line-height: 1.6; }
    .axis-scn .scn-condition { color: color-mix(in srgb, var(--text, #e6ebf2) 78%, var(--muted-2, #8a94a3));
      font-size: 12.5px; }
    .axis-scn .scn-outcome { margin-top: 8px; border-radius: 7px; padding: 9px 10px;
      background: #ffffff08; font-size: 13.5px; font-weight: 700; }
    .scn-key { font-size: 10px; font-weight: 850; letter-spacing: .25px; white-space: nowrap; }
    .axis-scn.positive .scn-key { color: #4ade80; }
    .axis-scn.negative .scn-key { color: #fb7185; }
    .scn-copy { min-width: 0; }
    .scenario-impact { border-top: 1px dashed var(--border, #2a3444); margin-top: 11px; padding-top: 8px; }
    .scenario-impact > summary { cursor: pointer; display: flex; justify-content: flex-start; gap: 3px;
      min-height: 30px; padding: 0; border-radius: 0; color: var(--muted-2, #8a94a3);
      font-size: 11.5px; font-weight: 700; list-style: none; }
    .scenario-impact > summary::-webkit-details-marker { display: none; }
    .scenario-impact > summary::before { content: "+"; display: inline-block; width: 15px; color: #8dbdff; }
    .scenario-impact > summary::after { content: none; }
    .scenario-impact[open] > summary::before { content: "−"; }
    .scn-reason { margin: 5px 0 10px; border-radius: 8px; background: #ffffff07; padding: 10px 11px; }
    .scn-reason-label { color: var(--muted-2, #8a94a3); font-size: 10px; font-weight: 850;
      letter-spacing: .3px; }
    .scn-reason-list { margin: 7px 0 0; padding-left: 18px; color: color-mix(in srgb, var(--text, #e6ebf2) 82%, transparent);
      font-size: 12px; line-height: 1.62; }
    .scn-reason-list li + li { margin-top: 6px; }
    /* 수혜/피해는 종목·섹터별 카드로 분리해 이유와 숫자를 따로 읽게 한다. */
    .bene-card { border: 1px solid var(--border, #2a3444); border-radius: 8px;
      background: color-mix(in srgb, var(--surface, #111720) 72%, transparent); padding: 10px 11px; }
    .bene-card + .bene-card { margin-top: 8px; }
    .bene-card-head { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
    .bene-card .bname { margin-left: 2px; font-size: 12.8px; font-weight: 750; }
    .bene-badge { display: inline-block; font-size: 9.5px; font-weight: 800; border-radius: 5px;
      padding: 1px 5px; margin-right: 4px; vertical-align: 1px; }
    .bene-badge.direct { background: #5aa0ff22; color: #5aa0ff; }
    .bene-badge.indirect { background: #6b728022; color: #9aa4b2; }
    .bene-badge.benefit { background: #16a34a22; color: #22c55e; }
    .bene-badge.damage { background: #dc262622; color: #f87171; }
    .bene-badge.neutral { background: #6b728018; color: #7b8593; }
    .bene-detail { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px;
      margin-top: 8px; font-size: 11.8px; line-height: 1.58; }
    .bene-detail-label { color: var(--muted-2, #8a94a3); font-size: 9.8px; font-weight: 850;
      letter-spacing: .2px; white-space: nowrap; }
    .bene-causal-chain, .bene-evidence { border-top: 1px dashed var(--border, #2a3444); padding-top: 7px; }
    .bene-financials { border-top: 1px dashed var(--border, #2a3444); padding-top: 7px; }
    .bene-raw { border-top: 1px dashed var(--border, #2a3444); margin-top: 8px; padding-top: 7px; }
    .bene-raw > summary { cursor: pointer; color: var(--muted-2, #8a94a3); font-size: 10.5px;
      font-weight: 700; list-style: none; min-height: 26px; }
    .bene-raw > summary::-webkit-details-marker { display: none; }
    .bene-raw > summary::before { content: "+"; display: inline-block; width: 14px; color: #8dbdff; }
    .bene-raw[open] > summary::before { content: "−"; }
    .bene-raw-detail { display: grid; grid-template-columns: 74px minmax(0, 1fr); gap: 8px;
      margin-top: 7px; border-radius: 6px; background: #ffffff06; padding: 7px 8px;
      color: color-mix(in srgb, var(--text, #e6ebf2) 72%, transparent);
      font-size: 10.8px; line-height: 1.58; overflow-wrap: anywhere; }
    .bene-raw-label { color: var(--muted-2, #8a94a3); font-size: 9.5px; font-weight: 800; }
    /* 관찰 신호 */
    .axis-watch { border: 1px solid #5aa0ff2e; background: #5aa0ff0a;
      border-radius: 10px; margin-top: 14px; padding: 10px 12px; }
    .axis-watch .axis-section-title { margin: 0 0 7px; color: #8dbdff; }
    .axis-watch ul { display: grid; gap: 6px; list-style: none; margin: 0; padding: 0;
      font-size: 12.8px; line-height: 1.55; }
    .axis-watch li { position: relative; padding-left: 14px; }
    .axis-watch li::before { content: ""; position: absolute; left: 1px; top: .63em;
      width: 5px; height: 5px; border-radius: 50%; background: #5aa0ff; }
    .axis-watch-grid { display: grid; gap: 7px; }
    .axis-watch-card { border: 1px solid var(--border, #2a3444); border-radius: 8px;
      background: color-mix(in srgb, var(--surface) 76%, transparent); padding: 8px 9px; }
    .axis-watch-card .watch-label { color: #8dbdff; font-size: 11px; font-weight: 800; }
    .axis-watch-card .watch-current { margin-top: 3px; font-size: 11.8px; line-height: 1.45; }
    .axis-watch-card .watch-trigger { margin-top: 2px; color: var(--muted-2, #8a94a3);
      font-size: 11.2px; line-height: 1.45; }
    .axis-watch-original { margin-top: 8px; border-top: 1px dashed var(--border, #2a3444); padding-top: 7px; }
    .axis-watch-original > summary { cursor: pointer; color: var(--muted-2, #8a94a3); font-size: 11px; }
    /* 카드 출처 */
    .axis-srcs { border-top: 1px dashed var(--border, #2a3444); margin-top: 12px; padding-top: 8px; }
    .axis-srcs > summary { cursor: pointer; list-style: none; font-size: 11.5px; color: var(--muted-2, #8a94a3); }
    .axis-srcs > summary::-webkit-details-marker { display: none; }
    .axis-srcs .src-row { font-size: 11px; color: var(--muted-2, #8a94a3); margin-top: 4px; }
    @media (min-width: 760px) {
      .editorial-takeaways { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .axis-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .axis-causal-flow { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
      .axis-flow-node:not(:last-child)::after { content: "→"; left: auto; right: -15px; bottom: 50%;
        transform: translateY(50%); }
    }
    @media (max-width: 600px) {
      .report-title { font-size: 18px; line-height: 1.5; }
      .report-when { margin-bottom: 12px; }
      .axes-tabs { top: 6px; margin-left: -2px; margin-right: -2px; }
      .axes-tab { min-height: 42px; padding: 9px 4px; }
      .axis-card { padding: 15px 13px; }
      .axis-title { font-size: 17px; }
      .axis-phenom { font-size: 14px; line-height: 1.76; }
      .axis-reading-body { padding: 16px 13px 20px; }
      .axis-scn { padding: 14px 13px; }
      .axis-scn .scn-condition, .axis-scn .scn-outcome { grid-template-columns: 56px minmax(0, 1fr); }
      .report-process-body { padding: 10px; }
    }
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
      const editorial = r.editorial && typeof r.editorial === "object" ? r.editorial : null;
      const integratedReading = editorial?.baseReportId === r.id;
      const reportMeta = editorial
        ? (integratedReading
          ? `${esc(editorial.label || "읽기 편집본")} · 자동 생성`
          : `${esc(editorial.label || "읽기 편집본")} · 원본 ${esc(editorial.baseReportId || "-")} · 주장 ${esc(r.claimCount || 0)}건`)
        : `주장 ${esc(r.claimCount || 0)}건`;
      return `<a class="report-row" href="#report-${esc(encodeURIComponent(r.id))}" data-id="${esc(r.id)}">
        <span class="idx">${esc(f.date)} - <span class="seq">${esc(r.seq)}</span></span>
        <span class="mid">
          <span class="title">${esc(editorial?.headline || r.title || "시황 리포트")}</span>
          <span class="meta">${reportMeta}</span>
        </span>
        <span class="when">${esc(fmt(editorial?.editedAt || r.generatedAt).time)}</span>
      </a>`;
    }).join("");
    el.innerHTML = `<div class="report-wrap">
      <div class="report-head"><h2>시황 리포트</h2><span class="sub">매일 06:30·18:30 KST 생성 시작 · 거시·당일 핵심 토픽 · 최신순</span></div>
      ${state.reports.length ? rows : `<div class="report-empty">아직 리포트가 없습니다.</div>`}
    </div>`;
    el.querySelectorAll(".report-row").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0
            || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        goto(row.getAttribute("href"));
      });
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
  const LEGACY_AXIS_LABELS = Object.freeze({ macro: "거시", memory: "메모리", other: "기타" });
  const AXIS_TONES = Object.freeze({
    macro: "macro",
    memory: "memory",
    other: "other",
    topic1: "topic1",
    topic2: "topic2",
  });

  function exactAxis(card) {
    return String(card?.axis || "");
  }

  function cardLabel(card) {
    const label = String(card?.label || "").trim();
    if (label) return label;
    const axis = exactAxis(card);
    return Object.hasOwn(LEGACY_AXIS_LABELS, axis) ? LEGACY_AXIS_LABELS[axis] : (axis || "?");
  }

  function axisTone(card) {
    return AXIS_TONES[exactAxis(card)] || "neutral";
  }

  function axisDomKey(axis, index) {
    const raw = String(axis || "");
    if (/^[A-Za-z][A-Za-z0-9_-]*$/.test(raw)) return raw;
    const encoded = encodeURIComponent(raw).replaceAll("%", "_");
    return encoded || `unknown-${index}`;
  }

  function axisEntries(cards) {
    const used = new Set();
    return cards.map((card, index) => {
      const base = axisDomKey(exactAxis(card), index);
      let key = base;
      let suffix = 2;
      while (used.has(key)) {
        key = `${base}-${suffix}`;
        suffix += 1;
      }
      used.add(key);
      return { card, key };
    });
  }

  function toneClass(tone) {
    return ["positive", "negative", "neutral", "warning"].includes(tone) ? tone : "neutral";
  }

  function editorialSummaryHtml(r) {
    const editorial = r.editorial;
    if (!editorial || typeof editorial !== "object") return "";
    const takeaways = Array.isArray(editorial.takeaways) ? editorial.takeaways : [];
    const cardsByAxis = new Map((Array.isArray(r.cards) ? r.cards : [])
      .map((card) => [exactAxis(card), card]));
    const baseTime = fmt(editorial.baseGeneratedAt);
    const editedTime = fmt(editorial.editedAt);
    const integratedReading = editorial.baseReportId === r.id;
    const hasBaseReport = editorial.baseReportId && editorial.baseReportId !== r.id
      && Array.isArray(state.reports)
      && state.reports.some((report) => report.id === editorial.baseReportId);
    return `<section class="editorial-summary" aria-label="리포트 한눈에 보기">
      <h2 class="editorial-heading">이번 리포트 한눈에 보기</h2>
      ${editorial.deck ? `<div class="editorial-conclusion"><span class="editorial-conclusion-label">한 줄 결론</span><div class="editorial-deck">${esc(editorial.deck)}</div></div>` : ""}
      ${takeaways.length ? `<div class="editorial-takeaways">${takeaways.map((item) => {
        const axis = exactAxis(item);
        const card = cardsByAxis.get(axis) || item;
        const label = String(card?.label || "").trim() ? cardLabel(card) : (item.title || cardLabel(card));
        return `<button class="editorial-nav-card ${axisTone(card)}" type="button" data-axis="${esc(axis)}">
          <span class="editorial-nav-top"><span class="label">${esc(label)}</span><span class="editorial-nav-arrow" aria-hidden="true">→</span></span>
          <span class="text">${esc(item.text || "")}</span>
        </button>`;
      }).join("")}</div>` : ""}
      <details class="editorial-provenance">
        <summary>${integratedReading ? "생성 정보" : "원본 정보"}</summary>
        <div class="editorial-provenance-body">${integratedReading
          ? `<span>생성 ${esc(editedTime.date)} ${esc(editedTime.time)} · ${esc(editorial.label || "읽기 편집본")}</span>
            <span>상세 분석·근거·출처는 아래 카드에 그대로 보존</span>`
          : `<span>원본 ${esc(baseTime.date)} ${esc(baseTime.time)}</span>
            <span>편집 ${esc(editedTime.date)} ${esc(editedTime.time)} · ${esc(editorial.label || "읽기 편집본")}</span>
            <span class="editorial-provenance-title">원문 제목 · ${esc(r.title || "")}</span>
            ${hasBaseReport ? `<a href="#report-${encodeURIComponent(editorial.baseReportId)}">원본과 비교하기 →</a>` : ""}`}
        </div>
      </details>
    </section>`;
  }

  function axisBriefHtml(brief) {
    if (!brief || typeof brief !== "object") return "";
    const numbers = Array.isArray(brief.keyNumbers) ? brief.keyNumbers : [];
    const flow = Array.isArray(brief.flow) ? brief.flow : [];
    return `<section class="axis-brief" aria-label="한눈에 보기">
      <div class="axis-brief-label">한눈에 보기</div>
      ${brief.summary ? `<div class="axis-brief-summary">${esc(brief.summary)}</div>` : ""}
      ${numbers.length ? `<div class="axis-metrics">${numbers.map((number) => `<div class="axis-metric ${toneClass(number.tone)}">
        <span class="metric-label">${esc(number.label || "")}</span>
        <span class="metric-value">${esc(number.value || "")}</span>
        <span class="metric-context">${esc(number.context || "")}</span>
      </div>`).join("")}</div>` : ""}
      ${flow.length ? `<div class="axis-causal-flow" aria-label="인과 흐름">${flow.map((node) => `<div class="axis-flow-node ${toneClass(node.tone)}">
        <span class="flow-label">${esc(node.label || "")}</span>
        <span class="flow-detail">${esc(node.detail || "")}</span>
      </div>`).join("")}</div>` : ""}
      ${brief.bottomLine ? `<div class="axis-bottom-line">${esc(brief.bottomLine)}</div>` : ""}
    </section>`;
  }

  // markdown → 소독 HTML + 〔…〕 라벨 축소 (articleHtml과 동일 규칙 — 현상 분석용)
  function mdToHtml(md) {
    const body = (typeof renderMarkdown === "function")
      ? sanitizeHtml(renderMarkdown(String(md || "")))
      : `<pre style="white-space:pre-wrap">${esc(md || "")}</pre>`;
    return body.replace(/〔([^〕<]{0,200})〕/g, '<span class="src-ref">〔$1〕</span>');
  }

  function readableParts(text) {
    return String(text || "").trim().split(/\n{2,}|(?<=[.!?。！？])\s+(?=\S)/u).filter(Boolean);
  }

  function deepAnswerParts(text, structuredNumbers = []) {
    const raw = String(text || "").trim();
    const normalizedNumbers = Array.isArray(structuredNumbers)
      ? structuredNumbers.filter((number) => number != null && String(number).trim()).map(String)
      : [];
    const transport = raw.match(/<\/answer>\s*<parameter\b[\s\S]*$/i);
    const answer = (transport ? raw.slice(0, transport.index) : raw)
      .replace(/<\/answer>\s*$/i, "").trim();
    if (normalizedNumbers.length) return { answer, numbers: normalizedNumbers };
    const leakedNumbers = raw.match(/<\/answer>\s*<parameter\s+name=["']?numbers["']?\s*>([\s\S]*)$/i);
    if (leakedNumbers) {
      try {
        const parsed = JSON.parse(leakedNumbers[1].replace(/<\/parameter>\s*$/i, "").trim());
        if (Array.isArray(parsed)) return { answer, numbers: parsed };
      } catch {
        // Invalid transport metadata is intentionally omitted from the reading view.
      }
    }
    return { answer, numbers: [] };
  }

  function analysisSectionsHtml(md) {
    const template = document.createElement("template");
    template.innerHTML = mdToHtml(md);
    const sections = [];
    let current = { title: "상세 분석", nodes: [] };
    const flush = () => {
      if (!current.nodes.length) return;
      sections.push(current);
      current = { title: "상세 분석", nodes: [] };
    };
    [...template.content.children].forEach((node) => {
      let heading = "";
      let remainder = "";
      if (["H1", "H2", "H3"].includes(node.tagName)) {
        heading = node.textContent.trim();
      } else if (node.tagName === "P" && node.firstElementChild?.tagName === "STRONG") {
        const candidate = node.firstElementChild.textContent.trim();
        if (/^(무슨 일이 있었나(?:\s*\([^)]*\))?|해석|추가 연구 후 정정)$/.test(candidate)) {
          heading = candidate;
          const clone = node.cloneNode(true);
          clone.firstElementChild.remove();
          remainder = clone.textContent.trim() ? clone.outerHTML : "";
        }
      }
      if (heading) {
        flush();
        current = { title: heading, nodes: remainder ? [remainder] : [] };
      } else {
        current.nodes.push(node.outerHTML);
      }
    });
    flush();
    if (!sections.length) return `<div class="markdown-body axis-phenom">${mdToHtml(md)}</div>`;
    return `<div class="analysis-sections">${sections.map((section) => `<section class="analysis-section">
      <div class="analysis-section-title">${esc(section.title)}</div>
      <div class="markdown-body axis-phenom">${section.nodes.join("")}</div>
    </section>`).join("")}</div>`;
  }

  // 추가 연구(deep_dive) — topic/findings 있을 때만 접이식으로
  function deepDiveHtml(dd) {
    if (!dd || typeof dd !== "object") return "";
    const findings = Array.isArray(dd.findings) ? dd.findings : [];
    if (!dd.topic && !findings.length) return "";
    const finds = findings.map((f) => {
      const sources = Array.isArray(f.sources) ? f.sources : [];
      const parsed = deepAnswerParts(f.answer, f.numbers);
      return `<div class="dd-find-card">
      <div class="dd-find-heading"><span class="axis-tag ${f.label === "근거" ? "pos" : "neutral"}">${esc(f.label || "가정")}</span></div>
      <div class="dd-answer">${readableParts(parsed.answer).map((part) => `<p class="dd-answer-paragraph">${esc(part)}</p>`).join("")}</div>
      ${parsed.numbers.length ? `<details class="dd-numbers"><summary>핵심 수치 ${parsed.numbers.length}개</summary><ul class="dd-number-list">
        ${parsed.numbers.map((number) => `<li class="dd-number">${esc(number)}</li>`).join("")}
      </ul></details>` : ""}
      ${sources.length ? `<details class="dd-sources"><summary>근거 링크 ${sources.length}개</summary><div class="dd-sources-list">
        ${sources.map((s) => `<div class="dd-src">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>${s.published ? ` (${esc(s.published)})` : ""}</div>`).join("")}
      </div></details>` : ""}
    </div>`;
    }).join("");
    return `<details class="axis-deep">
      <summary><span class="axis-deep-heading">추가 연구</span>${findings.length ? `<span class="cnt">${findings.length}건</span>` : ""}</summary>
      <div class="body">
        ${dd.topic ? `<div class="dd-topic"><span class="dd-topic-label">연구 질문</span><div class="dd-topic-text">${esc(dd.topic)}</div></div>` : ""}
        ${dd.research_failed ? `<div class="dd-src" style="color:#f59e0b">⚠ 웹 연구 실패/생략 — ${esc(dd.research_failed)} (관련 논점은 가정)</div>` : ""}
        ${dd.conclusion ? `<div class="dd-conclusion"><b style="color:#5aa0ff">결론</b> · ${esc(dd.conclusion)}</div>` : ""}
        ${finds}
      </div>
    </details>`;
  }

  function beneficiaryDisplayName(beneficiary) {
    const copy = beneficiary?.readerCopy && typeof beneficiary.readerCopy === "object"
      ? beneficiary.readerCopy : null;
    const preferred = String(copy?.displayName || beneficiary?.name || "").trim();
    const suffix = preferred.match(/\s*\([^()\s]{1,64}\)\s*$/);
    if (!suffix) return preferred;
    const code = suffix[0].trim().replace(/^\(|\)$/g, "").toUpperCase();
    const explanatory = new Set([
      "AI", "GPU", "CPU", "HBM", "DRAM", "NAND", "CPI", "PPI", "GDP",
      "ETF", "FX", "USD", "KRW", "JPY", "EUR", "API", "KST", "UTC",
      "ASML", "KLA", "TSMC", "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD",
      "EIA", "IEA", "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ",
      "CME", "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF",
      "NBS", "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS",
      "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP", "MOU",
      "UAE", "EU", "GMT", "EDT", "SGT",
    ]);
    if (beneficiary?.kind !== "stock" && explanatory.has(code)) return preferred;
    return preferred.slice(0, suffix.index).trim();
  }

  function beneficiaryReaderText(beneficiary, field) {
    const copy = beneficiary?.readerCopy && typeof beneficiary.readerCopy === "object"
      ? beneficiary.readerCopy : null;
    const edited = typeof copy?.[field] === "string" ? copy[field].trim() : "";
    return edited || String(beneficiary?.[field] || "").trim();
  }

  function beneficiaryRawDetailsHtml(beneficiary) {
    const copy = beneficiary?.readerCopy && typeof beneficiary.readerCopy === "object"
      ? beneficiary.readerCopy : null;
    if (!copy) return "";
    const rows = [
      ["원문 영향 이유", beneficiary?.rationale],
      ["원문 전이 경로", beneficiary?.causalChain],
      ["원문 근거", beneficiary?.evidence],
      ["원문 재무 숫자", beneficiary?.financials],
    ].filter(([, value]) => String(value || "").trim());
    if (!rows.length) return "";
    return `<details class="bene-raw"><summary>원문 데이터 보기</summary>
      ${rows.map(([label, value]) => `<div class="bene-raw-detail"><span class="bene-raw-label">${esc(label)}</span><span>${esc(String(value).trim())}</span></div>`).join("")}
    </details>`;
  }

  // 시나리오 박스 + 수혜/피해 목록 — positive 초록 / negative 빨강 좌보더
  function scenarioHtml(s, guide = null) {
    const pos = s.polarity === "positive";
    const bens = Array.isArray(s.beneficiaries) ? s.beneficiaries : [];
    const rows = bens.map((b) => {
      const rationale = beneficiaryReaderText(b, "rationale");
      const causalChain = beneficiaryReaderText(b, "causalChain");
      const evidence = beneficiaryReaderText(b, "evidence");
      const financials = beneficiaryReaderText(b, "financials");
      return `<div class="bene-card">
        <div class="bene-card-head"><span class="bene-badge ${b.direction === "direct" ? "direct" : "indirect"}">${b.direction === "direct" ? "직접" : "간접"}</span><span class="bene-badge ${b.polarity === "damage" ? "damage" : "benefit"}">${b.polarity === "damage" ? "피해" : "수혜"}</span><span class="bene-badge neutral">${b.kind === "stock" ? "종목" : "섹터"}</span><span class="bname">${esc(beneficiaryDisplayName(b))}</span></div>
        ${rationale ? `<div class="bene-detail bene-rationale"><span class="bene-detail-label">왜 영향을 받나</span><span>${esc(rationale)}</span></div>` : ""}
        ${causalChain ? `<div class="bene-detail bene-causal-chain"><span class="bene-detail-label">어떻게 번지나</span><span>${esc(causalChain)}</span></div>` : ""}
        ${evidence ? `<div class="bene-detail bene-evidence"><span class="bene-detail-label">확인된 근거</span><span>${esc(evidence)}</span></div>` : ""}
        ${financials ? `<div class="bene-detail bene-financials"><span class="bene-detail-label">숫자로 보면</span><span>${esc(financials)}</span></div>` : ""}
        ${beneficiaryRawDetailsHtml(b)}
      </div>`;
    }).join("");
    const editorialLead = guide
      ? `<div class="scn-condition"><span class="scn-key">조건</span><span class="scn-copy">${esc(guide.condition || "")}</span></div>
        <div class="scn-outcome"><span class="scn-key">예상 결과</span><span class="scn-copy">${esc(guide.outcome || "")}</span></div>`
      : `<div class="scn-thesis">${esc(s.thesis || "")}</div>`;
    const impacts = guide
      ? `<details class="scenario-impact"><summary>원문 근거와 수혜·피해 ${bens.length}개 보기</summary>
          <div class="scn-reason"><div class="scn-reason-label">원문 판단 근거</div><ul class="scn-reason-list">${readableParts(s.thesis).map((part) => `<li>${esc(part)}</li>`).join("")}</ul></div>${rows}</details>`
      : rows;
    return `<div class="axis-scn ${pos ? "positive" : "negative"}">
      <div class="scn-label">${pos ? "긍정 시나리오" : "부정 시나리오"}</div>
      ${editorialLead}
      ${impacts}
    </div>`;
  }

  function watchSignalsHtml(watch, brief) {
    const watchlist = Array.isArray(brief?.watchlist) ? brief.watchlist : [];
    if (!watch.length && !watchlist.length) return "";
    if (!watchlist.length) {
      return `<div class="axis-watch"><div class="axis-section-title">다음에 볼 신호</div><ul>${watch.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>`;
    }
    return `<div class="axis-watch">
      <div class="axis-section-title">다음에 볼 신호</div>
      <div class="axis-watch-grid">${watchlist.map((item) => `<div class="axis-watch-card">
        <div class="watch-label">${esc(item.label || "")}</div>
        <div class="watch-current">현재 · ${esc(item.current || "")}</div>
        <div class="watch-trigger">판정 · ${esc(item.trigger || "")}</div>
      </div>`).join("")}</div>
      ${watch.length ? `<details class="axis-watch-original"><summary>원문 관찰 신호 ${watch.length}개 보기</summary>
        <ul>${watch.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      </details>` : ""}
    </div>`;
  }

  function persistedScenarioGuidesHtml(brief) {
    const guides = Array.isArray(brief?.scenarioGuide) ? brief.scenarioGuide : [];
    if (!guides.length) return "";
    return `<div class="axis-scenarios">${guides.map((guide) => {
      const pos = guide.polarity === "positive";
      return `<div class="axis-scn ${pos ? "positive" : "negative"}">
        <div class="scn-label">${pos ? "긍정 시나리오" : "부정 시나리오"}</div>
        <div class="scn-condition"><span class="scn-key">조건</span><span class="scn-copy">${esc(guide.condition || "")}</span></div>
        <div class="scn-outcome"><span class="scn-key">예상 결과</span><span class="scn-copy">${esc(guide.outcome || "")}</span></div>
      </div>`;
    }).join("")}</div>`;
  }

  function axisCardHtml(c, domKey = axisDomKey(exactAxis(c), 0)) {
    const chip = `<span class="axis-chip ${axisTone(c)}">${esc(cardLabel(c))}</span>`;
    const brief = c.brief && typeof c.brief === "object" ? c.brief : null;
    // 축 생성 실패에도 이미 검증·저장된 읽기 요약은 보존한다.
    if (c.error) {
      return `<div class="axis-card failed">${chip}
        <div class="axis-title">${esc(brief?.headline || c.title || "")}</div>
        ${axisBriefHtml(brief)}
        ${persistedScenarioGuidesHtml(brief)}
        ${watchSignalsHtml([], brief)}
        <div class="axis-fail">⚠ 이 축 생성 실패</div>
        <div class="axis-fail-reason">${esc(c.error)}</div>
      </div>`;
    }
    const scns = Array.isArray(c.scenarios) ? c.scenarios : [];
    const watch = Array.isArray(c.watch_signals) ? c.watch_signals : [];
    const srcs = Array.isArray(c.sources) ? c.sources : [];
    const phenomenon = String(c.phenomenon || "");
    const phenomenonId = `axis-phenomenon-${domKey}`;
    const longPhenomenon = phenomenon.length > 900;
    // 순서(2026-07-24 사용자): 현상 → 긍정 시나리오 → 부정 시나리오 → 추가 연구
    const ordered = [...scns].sort((a, b) =>
      (a.polarity === "positive" ? 0 : 1) - (b.polarity === "positive" ? 0 : 1));
    const scenarioGuides = new Map((Array.isArray(brief?.scenarioGuide) ? brief.scenarioGuide : [])
      .map((guide) => [guide.polarity, guide]));
    const phenomenonHtml = !phenomenon ? "" : brief
      ? `<details class="axis-analysis">
          <summary>근거와 상세 분석 보기<span class="cnt">원문 전체</span></summary>
          <div class="axis-analysis-body">
            <div class="axis-reading-body">
              ${c.title ? `<div class="axis-original-title"><span class="axis-original-kicker">원문 핵심 문장</span><div class="axis-original-text">${esc(c.title)}</div></div>` : ""}
              ${analysisSectionsHtml(phenomenon)}
            </div>
          </div>
        </details>`
      : `<section class="axis-phenomenon">
          <div class="axis-section-title">핵심 현상</div>
          <div class="axis-phenom-shell${longPhenomenon ? " is-collapsed" : ""}" id="${phenomenonId}">
            <div class="markdown-body axis-phenom">${mdToHtml(phenomenon)}</div>
          </div>
          ${longPhenomenon ? `<button class="axis-phenom-toggle" type="button"
            aria-expanded="false" aria-controls="${phenomenonId}"
            data-more-label="현상 전문 보기" data-less-label="현상 접기">현상 전문 보기</button>` : ""}
        </section>`;
    return `<div class="axis-card">
      ${chip}
      <div class="axis-title">${esc(brief?.headline || c.title || "")}</div>
      ${axisBriefHtml(brief)}
      ${phenomenonHtml}
      ${ordered.length ? `<div class="axis-section-title">상승·하락 시나리오</div>
        <div class="axis-scenarios">${ordered.map((scenario) => scenarioHtml(scenario, scenarioGuides.get(scenario.polarity))).join("")}</div>` : ""}
      ${deepDiveHtml(c.deep_dive)}
      ${watchSignalsHtml(watch, brief)}
      ${srcs.length ? `<details class="axis-srcs"><summary>추가 연구 출처 ${srcs.length}건 (웹 검증)</summary>
        ${srcs.map((s) => `<div class="src-row">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>${s.published ? ` (${esc(s.published)})` : ""}</div>`).join("")}
      </details>` : ""}
    </div>`;
  }

  // 카드 축을 그대로 쓰는 WAI-ARIA 탭 패턴과 방향키 탐색 지원.
  function axesHtml(cards) {
    const entries = axisEntries(cards);
    return `<div class="axes-tabs" role="tablist" aria-label="리포트 관점">${entries.map(({ card, key }, i) =>
      `<button class="axes-tab ${axisTone(card)}${i === 0 ? " on" : ""}" type="button"
        id="axis-tab-${esc(key)}" role="tab" aria-controls="axis-panel-${esc(key)}"
        aria-selected="${i === 0 ? "true" : "false"}" tabindex="${i === 0 ? "0" : "-1"}"
        data-i="${i}" data-axis="${esc(exactAxis(card))}">${esc(cardLabel(card))}</button>`).join("")}</div>
      <div class="axes-panels">${entries.map(({ card, key }, i) =>
        `<div class="axes-panel${i === 0 ? " on" : ""}" id="axis-panel-${esc(key)}"
          role="tabpanel" aria-labelledby="axis-tab-${esc(key)}" aria-label="${esc(cardLabel(card))}"
          ${i === 0 ? "" : "hidden"} data-i="${i}" data-axis="${esc(exactAxis(card))}">${axisCardHtml(card, key)}</div>`).join("")}</div>`;
  }

  function bindAxes() {
    const tabs = [...view().querySelectorAll(".axes-tab")];
    const panels = [...view().querySelectorAll(".axes-panel")];
    if (!tabs.length) return;
    const activate = (index, focus = false, resetReadingPosition = false) => {
      tabs.forEach((tab, tabIndex) => {
        const selected = tabIndex === index;
        tab.classList.toggle("on", selected);
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (selected && focus) tab.focus();
      });
      panels.forEach((panel, panelIndex) => {
        const selected = panelIndex === index;
        panel.classList.toggle("on", selected);
        panel.hidden = !selected;
      });
      if (resetReadingPosition) {
        panels[index]?.scrollIntoView({ block: "start", behavior: "auto" });
      }
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activate(index, false, true));
      tab.addEventListener("keydown", (event) => {
        let next = null;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = tabs.length - 1;
        if (next == null) return;
        event.preventDefault();
        activate(next, true, true);
      });
    });
    view().querySelectorAll(".editorial-nav-card").forEach((button) => {
      button.addEventListener("click", () => {
        const index = tabs.findIndex((tab) => tab.dataset.axis === button.dataset.axis);
        if (index >= 0) activate(index, false, true);
      });
    });
  }

  function reportTitleHtml(report) {
    const title = String(report.editorial?.headline || report.title || "시황 리포트");
    const longTitle = title.length > 90;
    return `<div class="report-title-block">
      <div class="report-title${longTitle ? " is-collapsed" : ""}" id="report-detail-title">${esc(title)}</div>
      ${longTitle ? `<button class="report-title-toggle" type="button"
        aria-expanded="false" aria-controls="report-detail-title"
        data-more-label="제목 전체 보기" data-less-label="제목 접기">제목 전체 보기</button>` : ""}
    </div>`;
  }

  function bindReadingDisclosures() {
    view().querySelectorAll(".report-title-toggle, .axis-phenom-toggle").forEach((button) => {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.getAttribute("aria-controls"));
        if (!target) return;
        const expanded = button.getAttribute("aria-expanded") !== "true";
        target.classList.toggle("is-collapsed", !expanded);
        button.setAttribute("aria-expanded", String(expanded));
        button.textContent = expanded ? button.dataset.lessLabel : button.dataset.moreLabel;
      });
    });
  }

  function processHtml(stages) {
    if (!stages.length) return "";
    return `<details class="report-process">
      <summary>생성·검증 과정 보기<span class="cnt">${stages.length}단계</span></summary>
      <div class="report-process-body">
        <div class="section-hint">각 단계를 펼치면 수집 원문, 필터와 검증 근거를 확인할 수 있습니다.</div>
        <div class="report-process-stages"><div class="report-process-placeholder">열 때 상세 과정을 불러옵니다.</div></div>
      </div>
    </details>`;
  }

  function bindProcessDisclosure(stages) {
    const process = view().querySelector(".report-process");
    const container = process?.querySelector(".report-process-stages");
    if (!process || !container) return;
    let rendered = false;
    process.addEventListener("toggle", () => {
      if (!process.open || rendered) return;
      container.innerHTML = stages
        .map((stage, index) => stageHtml(stage, index, stages.length)).join("");
      rendered = true;
    });
  }

  function renderDetail() {
    const el = view();
    const r = state.report;
    if (state.error) { el.innerHTML = `<div class="report-wrap"><button class="report-back">← 목록</button><div class="report-feedback">${esc(state.error)}</div></div>`; bindBack(); return; }
    if (!r) { el.innerHTML = `<div class="report-wrap"><div class="report-empty">불러오는 중…</div></div>`; return; }
    const f = fmt(r.generatedAt);
    const claims = Array.isArray(r.claims) ? r.claims : [];
    const stages = (r.pipeline && Array.isArray(r.pipeline.stages)) ? r.pipeline.stages : [];
    const flowHtml = processHtml(stages);
    // v2 3축 카드 — 독서용 탭을 먼저 보여주고 생성·검증 과정은 필요할 때 연다.
    if (r.format === "axes" && Array.isArray(r.cards) && r.cards.length) {
      el.innerHTML = `<div class="report-wrap">
        <button class="report-back">← 목록</button>
        ${reportTitleHtml(r)}
        <div class="report-when">${esc(f.date)} - ${esc(r.seq)} (${esc(f.time)})${r.window ? ` · 구간 ${esc(fmtShort(r.window.from))} ~ ${esc(fmtShort(r.window.to))}` : ""}</div>
        ${editorialSummaryHtml(r)}
        ${axesHtml(r.cards)}
        ${flowHtml}
      </div>`;
      bindBack();
      bindAxes();
      bindReadingDisclosures();
      bindProcessDisclosure(stages);
      return;
    }
    el.innerHTML = `<div class="report-wrap">
      <button class="report-back">← 목록</button>
      ${reportTitleHtml(r)}
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
    bindReadingDisclosures();
    bindProcessDisclosure(stages);
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
      const needsReport = !state.report || state.report.id !== state.detailId;
      const needsReportList = state.reports === null;
      if (needsReport) {
        state.report = null;
        renderDetail();
      }
      await Promise.all([
        needsReport
          ? api(`/api/market-reports/${encodeURIComponent(state.detailId)}`)
            .then((data) => { state.report = data.report; })
            .catch((error) => { state.error = error.message; })
          : Promise.resolve(),
        needsReportList
          ? api("/api/market-reports")
            .then((data) => { state.reports = data.reports || []; })
            .catch(() => { state.reports = []; })
          : Promise.resolve(),
      ]);
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
