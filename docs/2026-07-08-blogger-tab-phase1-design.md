# 블로거 탭 1차 설계 (2026-07-08)

- 목표: attn.ngrok.app에 "블로거" 탭을 추가하고, 웹에서 블로그를 추가/제거하면
  과거 글 백필 + 새 글 감지까지 자동으로 되게 한다.
- 이 문서는 1차 범위만 다룬다. 글 요약·사고(思考) 추출·설계도·QA 엔진 주입은
  2차 이후 (브레인스토밍 합의: 사고 절차 추출이 최종 목표, 추출 품질이 승부처).

## 전체 방향 (합의 요약)

```
크롤러(증분) → 코퍼스 → ①글별 분석(triage→사고 기록+다이제스트)
                          ├ 새 글 피드(탭)          ← 1차는 여기까지의 기반만
                          ├ 연쇄·갱신 패턴 추출
                          └ 대조 집계 → 블로거별 사고 설계도 → QA 엔진(PLAN·SYNTHESIZE·tier별 패널)
```

- 사고 추출 원칙(2차 이후): 추론 글만 골라내기 → 뾰족한 질문 세트로 글별 추출 →
  시간순 연쇄에서 갱신 패턴 → 블로거 간 대조 집계(구별되는 것만) →
  "본인 글 맞히기"(holdout) 검증 → QA 주입 전후 A/B.
- 탭은 열람용이면서 사고 추출 품질을 눈으로 검증하는 도구가 된다.

## 1차 범위

포함:
1. 블로그 레지스트리 (단일 JSON, 웹·크롤러 공용)
2. 웹에서 블로그 추가(ID 검증 → 백필 job) / 제거(비활성화, 데이터 보존)
3. 새 글 감지 (주기 확인 + 증분 수집)
4. 글 열람 (최신순 목록, 블로거 필터, 마크다운 본문)

제외 (2차 이후): 요약·다이제스트, 사고 기록, 설계도, QA 엔진 연동, 네이버 외 소스.

## 확정 사실 (2026-07-08 실측)

- 네이버 post-list API·본문 fetch는 **referer 헤더 필수**
  (`https://m.blog.naver.com/PostList.naver?blogId=<id>` — 없으면 전부 실패).
- ionia17(James Lee Advisors): 목록 API는 정상이나 모든 본문이
  `MobileErrorView.naver?errorType=noPost`로 리다이렉트 — 이웃공개/로그인 필요로 추정.
  → 비로그인 수집 불가. 탭에서 "본문 접근 불가" 상태로 표시하고 재시도 반복하지 않는다.
- 수집 중인 블로그 15개 (사용자 확정 리스트):
  ranto28(메르) yminsong(와이민) ionia17(James Lee Advisors) jakojako(재콩)
  tosoha1(농구천재) mistergray(회색 인간) sungdory(승도리) shinook430(북회귀선)
  crush212121(체리형부) jyt4159(초대현대농업) cybermw(좋은친구)
  zzayofactory(미생에서 완생으로) new10yrs(멘탈거북) furmea21(드리머) morgoth(와시즈)
- 추가 후보 (오늘 API로 ID 검증 완료, 웹 UI에서 추가 가능):
  hodolry(호돌이·반도체) hong8706(홍춘욱·매크로) santa_croce(산타크로체·지정학).

## 부품 설계

### 1. 블로그 레지스트리

`storage/users/<user>/corpus/blogs.json`

```json
{
  "blogs": [
    { "id": "ranto28", "source": "naver", "name": "메르", "tags": [],
      "active": true, "addedAt": "ISO", "note": "" }
  ]
}
```

- 서버 시작 시 파일이 없으면 위 15개로 시드.
- 제거 = `active:false` (코퍼스 데이터는 보존). 재추가 시 다시 활성화.
- 편수·최신 글·job 상태는 레지스트리에 저장하지 않고 디스크(index.jsonl, jobs/)에서 계산
  — 병렬로 도는 수동 크롤과 충돌하지 않기 위해.

### 2. 크롤러 보강 (scripts/crawl_naver_blog.mjs)

- `--stopOnKnown N`: 이미 저장된 글을 연속 N개(기본 10) 만나면 종료 — 증분 수집 모드.
  (기본 동작인 "건너뛰고 계속"은 백필용으로 유지)
- 기존 jobs/*.json이 진행률 폴링 소스가 된다 (discovered/saved/lastPage/done).

### 3. server.mjs API (requireAuth, 파일 기반)

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | /api/blogs | 레지스트리 + 블로그별 통계(편수·최신 글·마지막 확인·실행 중 job) |
| POST | /api/blogs | {blogId, name} → post-list API로 ID 검증 → 등록 → 백필 job spawn |
| DELETE | /api/blogs/:blogId | active=false |
| POST | /api/blogs/:blogId/refresh | 증분 수집 job 실행 (--stopOnKnown) |
| GET | /api/blogs/:blogId/posts | index.jsonl 최신순, offset/limit |
| GET | /api/blogs/:blogId/posts/:articleId | 마크다운 본문 + 메타데이터 |

- 백필/증분 job = `spawn("node", ["scripts/crawl_naver_blog.mjs", ...])` 백그라운드,
  블로그당 동시 1개 제한. 진행률은 GET /api/blogs가 최신 jobs/*.json을 읽어 응답.
- 새 글 감지: 서버 setInterval(기본 30분, env로 조절) → active 블로그 순회(순차, 간격 두고)
  → page1 목록과 index 대조 → 새 logNo 있으면 증분 job 실행.
  마지막 확인 시각은 `corpus/naver/<id>/last-check.json`에 기록.
- 본문 접근 불가 블로그: 백필 job에서 discovered>0 & saved==0 & 전부 body marker/noPost 실패면
  레지스트리에 `fetchBlocked: true` 마킹 → 새 글 감지 대상에서 제외, UI에 상태 표시.

### 4. 탭 UI

- primary-nav에 "블로거" 버튼 추가 (홈·검토·채팅·메모리 다음).
- `<section class="view" id="bloggerView" hidden>` + **별도 파일 `public/blogger.js`**
  (index.html이 8,600줄이라 이 탭 로직은 분리, index.html에는 마크업 골격+script 태그만).
- 화면 구성 (한 view 안에서 전환):
  1. **블로그 목록**: 카드(이름·ID·편수·최신 글 제목/시각·새 글 뱃지·백필 진행률·
     본문 접근 불가 표시·제거 버튼) + 추가 폼(ID·이름 → 검증 → 백필 시작) + "지금 새로고침".
  2. **글 목록**: 전체/블로거별 최신순, 제목·블로거·게시일. 페이지네이션.
  3. **글 보기**: 마크다운 렌더(기존 markdown-body 스타일 재사용), 원문 링크.

### 5. 검증

- API: curl로 목록/추가(검증 실패 케이스 포함)/제거/refresh 확인.
- UI: playwright로 로그인 → 블로거 탭 → 스크린샷 → 눈으로 확인 후 완료 보고
  (curl/문법체크만으로 완료 보고 금지).

## 구현 순서

1. 레지스트리 + 크롤러 `--stopOnKnown`
2. server.mjs API + 백필 job + 새 글 감지
3. 탭 UI (blogger.js)
4. 검증 (curl + 스크린샷)

## 2차 이후 백로그

- 글별 분석(triage → 사고 기록 + 다이제스트) — engine/corpus/ Python 모듈
- 연쇄·갱신 패턴, 대조 집계 설계도, holdout 검증
- QA 엔진 주입(PLAN·SYNTHESIZE 통합 지침, tier·DA 불일치 시 블로거별 패널) + A/B
- 네이버 외 소스 크롤러 (tistory/substack/RSS — 코퍼스 규칙은 docs/naver-blog-corpus.md)
- ionia17류 접근 제한 블로그의 로그인 수집 여부 검토
