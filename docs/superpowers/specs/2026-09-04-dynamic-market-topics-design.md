# Dynamic Market Topics Report Design

## Objective

Replace the generated report's fixed `macro / memory / other` content model with
`macro / topic1 / topic2`. `topic1` and `topic2` are the two most important,
evidence-supported non-macro market topics in the report window. Memory-sector
inputs remain available as evidence but no longer receive a reserved card or
headline preference.

The first automatic target is the 2026-09-04 18:30 KST scheduler slot. The
scheduler starts a fresh report-pipeline subprocess after its freshness
collection, so generator modules activate without restarting PM2.

## Compatibility Contract

`format: "axes"` continues to describe the three-card reader layout. New reports
add `axisModel: "topics_v1"`; the absence of `axisModel` means the historical
fixed-axis contract only when the card set is exactly `macro / memory / other`.
No stored report is rewritten.

A new report has exactly three cards:

- `axis: "macro"`, `label: "거시"`, `topicKey: "macro"`
- `axis: "topic1"`, a short dynamic `label`, and a stable semantic `topicKey`
- `axis: "topic2"`, a short dynamic `label`, and a distinct stable `topicKey`

`leadAxis` is one of those three axes and identifies the card whose title becomes
`Report.title`. Card order is presentation order, not topic identity. Previous
dynamic topics are matched by `topicKey`, never by `topic1` or `topic2` position.

OpenAPI is the executable transport contract. It accepts both the historical
fixed-axis payload and `topics_v1`, while rejecting mixed card sets, duplicate
slots, missing labels, and an invalid lead axis. Pydantic applies the same
cross-field rules before a scheduled report can be saved.

## Topic Selection and Evidence

The existing broad SaveTicker raw corpus remains the source; no new collector is
required. Report relevance filtering changes from memory-chain relevance to
listed-equity and cross-asset market materiality. Selected candidates retain
title, excerpt, source, URL, and timestamp instead of falling back to titles only.

The selector always produces a macro plan and ranks two distinct non-macro plans
using:

1. expected market impact and number of affected value-chain layers;
2. freshness and change since the previous report;
3. evidence density and source quality;
4. breadth of direct and second-order transmission;
5. distinctness from the other selected topic.

Memory can win a dynamic slot when its evidence and impact rank in the top two;
it is never inserted merely because memory data exists. There is no one-memory
quota: if distinct DRAM and HBM events genuinely rank first and second, both are
kept. Case-memory context is used only when the matched title/excerpt supports a
memory-primary event; selector labels, focus text, or a downstream HBM mention
alone cannot enable it.

## Scenarios and Transmission

Every successful card has one positive and one negative scenario. Each scenario
has at least one `direct` and one `indirect` impact. Every impact keeps the
existing `kind`, `direction`, `polarity`, `rationale`, and `financials` fields and
adds a non-empty `causalChain` explaining the transmission path.

A `stock` impact must use `회사명 (티커)` and include company-specific evidence in
`evidence`. If that evidence is unavailable, the generator must emit a `sector`
impact instead. Validation rejects incomplete direction coverage; a failed
generation is retried once and then produces an explicit degraded/error card,
never invented company exposure.

Macro scenarios must start from the macro transmission itself and may not use a
memory company as a default beneficiary. Anchor data is routed by selected topic:
the macro card receives macro-market anchors, a memory-primary topic may receive
memory-chain anchors, and a topic does not inherit memory metrics merely because
memory is a possible downstream effect. The selector receives a balanced sample
across metric families rather than the storage-order prefix.

A stock is grounded against assigned event title/excerpt, sourced follow-up
research answer/title, or the exact `entity` of an anchor selected for that card;
URLs, publisher labels, metric IDs, and repeating the company name inside the
model-produced `evidence` field are not identity evidence. Known issuer names and
tickers must agree, and share-class/exchange/dual-listing aliases resolve to one
canonical issuer. An unknown ticker requires company and explicit ticker notation
in the same original evidence record. Model-generated cluster summaries are not
stock identity evidence. A listed or company-shaped issuer cannot evade these
checks by declaring `kind=sector`, and one polarity cannot fill direct and indirect
slots with aliases of the same issuer.
Across cards, an already-used canonical issuer is excluded from later scenario
generations in plan-rank order so that a lower-ranked display slot cannot reserve
a stock ahead of the lead topic. Returned cards remain in the stable
macro/topic1/topic2 display order. The later-ranked card must choose another
independently grounded company or fall back to a sector. The same stock may still
appear in the positive and negative branches of one card because those are
mutually exclusive states of the same exposure.

All selector, phenomenon, assigned-source, research, generated-analysis, and audit
payloads are serialized as untrusted data with delimiter escaping; trusted task
instructions follow the data boundary. Source timestamps remain visible to
scenario generation and audit through per-record caps rather than a whole-block
slice. A missing or schema-invalid beneficiary-audit verdict is retried when
possible and then fails closed for scenarios, including retry timeout; only a
genuine first-call transport outage keeps the existing card-availability behavior.
Every allowlisted report metric must have an explicit axis route so catalog growth
cannot silently disappear from all cards.

## Headline and Reader

The topic selector assigns `leadAxis` from the highest-ranked of macro, topic1,
and topic2. The report headline is that card's audited title.

The readable presentation proven by report `2026-09-04-3` is the default output
contract, not a manually published derivative. Every newly generated
`topics_v1` report declares `readerModel: "brief_v1"`, contains an integrated
`editorial` overview, and contains a typed
`brief` on every card, including an explicit degraded/error card. The overview provides a concise headline,
one-paragraph conclusion, and one takeaway for each exact axis. Each card brief
provides a short headline and summary, grounded key numbers, a causal flow,
positive and negative condition/outcome guides, a watchlist, and a bottom line.
Every beneficiary also retains its audited raw fields and receives a typed
`readerCopy`: ticker-free display name plus plain-Korean rationale, causal path,
evidence, and financials. The generator rejects missing rows, internal metric or
ticker syntax, omitted row-local numbers, changed periods/comparison bases,
changed numeric direction, and values rebound to a different financial metric.
These fields only reorder and condense the already audited card; they never
replace or mutate its detailed phenomenon, scenarios, beneficiaries, research,
sources, or pipeline provenance.

Integrated reading metadata keeps the same report ID. Its `baseReportId` is the
report's own ID and all provenance timestamps are deterministic from the report
generation time. Historical manually edited reports may still point
`baseReportId` at a separately retained source report. If the CLI reading pass
fails, violates its structured contract, or introduces an ungrounded number, the
pipeline emits a deterministic brief derived from audited titles, analysis,
scenario theses, watch signals, and beneficiary rows. That fallback expands
known raw units and comparison abbreviations, removes ticker syntax, and remains
total for every upstream-valid string. A new report therefore never falls back to
the dense raw-card presentation merely because the editorial pass failed.

Readable beneficiary fields are deliberately concise. To prevent that length
budget from hiding a late correction or any other source text, the UI places all
unmodified beneficiary fields behind a nested `원문 데이터 보기` disclosure.
Thus the scan path is natural language while the complete source row stays
reachable on both mobile and desktop. The friendlier beneficiary labels also
apply to stored fixed-axis reports; their payload and facts remain unchanged.

The `readerModel` discriminator makes this guarantee executable without
invalidating historical `topics_v1` JSON. A report without it is treated as a
stored pre-reading-layer artifact; when it is `brief_v1`, OpenAPI, the Python
contract, and the validation harness require self provenance, the overview, all
three card briefs, and exact beneficiary `readerCopy` coverage.

The reading pass remains topic-aware rather than visually rigid: a macro event,
company event, policy change, or sector cycle may emphasize different numbers or
causal steps. The invariant is reading order and factual compression, not a
memory-specific set of labels or prose.

The reader derives tab, chip, navigation, and accessible labels from
`card.label`, with the historical label map only as a legacy fallback. DOM IDs and
navigation use exact axis IDs; unknown axes are displayed explicitly rather than
silently normalized to `other`. Topic slots receive distinct responsive styles,
and the existing single-column mobile reading flow remains intact.

## Scheduling and Identity Safety

Report IDs are permanently consumed. Slot allocation considers active JSON,
active reservations, and archived same-date report JSON. With archived
`2026-09-04-1/-2` and active `-3`, the next allocation is `2026-09-04-4`.
Reservations are still created atomically. This prevents an editorial
`baseReportId` from later resolving to an unrelated report.

## Model Execution

OpenAPI is only the data contract. All report model execution remains CLI-only.
The report roles use Claude CLI; no OpenAI or Anthropic HTTP model API is opened.
Existing explicit CLI-to-CLI routing remains a CLI subscription path.

## Acceptance Criteria

- Old fixed-axis reports and the existing editorial report render unchanged.
- A new payload validates only with the exact new card set, labels, distinct
  topic keys, valid `leadAxis`, both scenario polarities, and direct/indirect
  coverage.
- A high-impact non-memory raw story reaches selection with its excerpt/source.
- Topic ranking can select two non-memory topics and can select memory only by
  rank, not quota.
- Swapping a persistent topic between topic1/topic2 keeps continuity by
  `topicKey`; unrelated topics receive no stale prior-card context.
- `Report.title` equals the audited title of `leadAxis`.
- Every newly generated `topics_v1` report includes its own `editorial` overview
  and a `brief` for each of its three cards; no second report ID or manual overlay is
  required.
- `readerModel: "brief_v1"` makes that reading layer mandatory in the executable
  transport and Python contracts while historical unmarked reports remain valid.
- The reading layer contains exactly macro/topic1/topic2 takeaways, both scenario
  polarities per card, and no numerical token absent from the audited source
  material; a deterministic non-empty fallback is emitted on CLI failure.
- A stock without company-specific evidence is rejected or downgraded to sector.
- Topic tabs have unique IDs, correct labels/navigation, and work at mobile and
  desktop widths; a legacy rendering regression also passes.
- Slot allocation returns `2026-09-04-4` for the current active/archive fixture.
- Python, Node contract/API, and browser smoke suites pass before completion.
