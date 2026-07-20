# cj-v4 진단 베이스라인 재감사 최종 artifact (2026-07-20)

원본: report-chain-20260720-152545.{md,jsonl} — **원본은 무수정 보존** (원 측정 시점
검출기의 as_of 위반 5건·unresolved 3건 기록 그대로).

## 재감사 결과 (검출기 보정 후, 커밋 66875d3 + full_text + 9ed5fa1 기준)

- 방법: 저장된 24개 answer_md에 대해 보정된 find_violations를 재적용
  (layers는 da_blind 존재로 간주 — DA는 DISPATCH 무조건 실행 브랜치)
- **as_of 위반: 0건** — 원 5건의 판별:
  - cite:da_gpt/da_fable 2건 → DA 레이어 실행 결속으로 정당
  - URL 3건(seekingalpha·digitimes·stocktwits) → 케이스 bundle 카드 raw_quote 본문에
    실재 (bundle_text 150자 절단으로 인한 검출기 오탐)

## 지위

이 리포트의 축 평균(m 0.826 / s 0.739 / v 0.609 / e 0.312 / c 0.304, uncovered 0.66)은
**진단 전용**이다 — 봉인 calibration 미통과 실행이므로 효과크기·배포 판정에 사용 금지
(스펙 1부 완료 스코프 절). 개선 표적 순위(evidence·countercase·uncovered)는 리비전
무관 불변으로 2·3부 설계 근거로 사용한다.
