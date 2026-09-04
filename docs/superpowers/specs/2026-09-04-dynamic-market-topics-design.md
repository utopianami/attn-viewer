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
it is never inserted merely because memory data exists. Case-memory context is
used only when the selected topic is actually memory-related.

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
memory company as a default beneficiary. Repeated names across cards are allowed
only when each card supplies an independent causal chain.

## Headline and Reader

The topic selector assigns `leadAxis` from the highest-ranked of macro, topic1,
and topic2. The report headline is that card's audited title. Editorial headlines
remain display overrides without changing original evidence.

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
- A stock without company-specific evidence is rejected or downgraded to sector.
- Topic tabs have unique IDs, correct labels/navigation, and work at mobile and
  desktop widths; a legacy rendering regression also passes.
- Slot allocation returns `2026-09-04-4` for the current active/archive fixture.
- Python, Node contract/API, and browser smoke suites pass before completion.
