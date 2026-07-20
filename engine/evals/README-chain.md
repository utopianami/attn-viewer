# chain_judgment 전향 케이스 운영 절차

## 목적

사건 기반 eval(chain_judgment)을 위한 불변 evidence bundle을 전향(prospective)으로 수집한다.
holdout 10개 이상 확보가 4부(판정 배포) 전제 조건이다.

## 번들 디렉터리 구조

```
engine/evals/bundles/
  cj-<케이스명>/
    manifest.json       — 색인·해시·가용성 메타
    cards.jsonl         — 섹터 카드 스냅샷 (as_of 기준)
    metrics/
      <metric>.jsonl    — 지표 스냅샷 (as_of 기준)
    ra_docs.jsonl       — RA 문서 (날짜 있는 것만)
    prices.json         — 시세 스냅샷
    macro.json          — 매크로 스냅샷
```

`manifest.json`의 `content_hash`(SHA-256 앞 16자리)는 번들 내용이 변조되지 않았음을 증명한다.
번들은 생성 후 **절대 덮어쓰지 않는다** — `capture_bundle`이 `FileExistsError`로 강제한다.

## 전향 캡처 명령 (proven — 오늘 수집 확인)

```bash
cd /home/ryze_yn/attn-viewer/engine

# auto-live: yahoo 시세·매크로 자동 수집, RA는 회고성 사유로 면제
.venv/bin/python -m evals.build_chain_cases capture \
  --case cj-p$(date -u +%m%d) \
  --as-of $(date -u +%F) \
  --availability proven \
  --auto-live \
  --allow-empty-ra '전향 회고 시점 RA 미수집 — 섹터 카드로 충분'
```

**`--auto-live`**: `tools.price.yahoo.quote()`로 기본 티커셋(005930.KS, 000660.KS, MU, NVDA, ^KS11, KRW=X)을,
`stages.price_macro`의 macro 수집 함수로 매크로를 자동 채운다. 결정적(LLM 없음).

## 캡처 트리거 기준

유의미한 사건 발생 시 **당일** 캡처:

- 섹터 카드 magnitude ≥ 3 수집됨
- 실적 발표일
- 주요 정책 발표일 (수출 통제, 금리 결정 등)

## proven vs unproven

| | proven | unproven |
|---|---|---|
| as_of | 오늘(UTC)만 | 과거 날짜 허용 |
| 빈 채널 | empty_reasons 필수 | 허용 |
| 용도 | 전향 holdout | 회고 분석 |

## 번들 목록 확인

```bash
ls engine/evals/bundles/
cat engine/evals/bundles/<케이스명>/manifest.json | python3 -m json.tool
```

## 4부 배포 전제

holdout 10개 이상 확보 후 chain_judgment 판정 로직 배포.
현재 상태: 0 / 10 케이스 확보.
