# Naver Blog Corpus 수집 가이드

네이버 블로그 글을 Markdown 코퍼스로 저장하는 작업은
`scripts/crawl_naver_blog.mjs`로 실행한다.

현재 방식은 네이버 모바일 블로그의 post-list API로 글 목록을 가져오고,
각 글의 모바일 HTML을 받아 본문을 Markdown으로 변환한다.

## 기본 실행

```bash
node scripts/crawl_naver_blog.mjs --blogId ranto28 --user ryze_yn
```

다른 블로그도 같은 방식으로 `--blogId`만 바꾸면 된다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn
```

예를 들어 블로그 주소가 아래와 같다면:

```text
https://m.blog.naver.com/example_id
https://blog.naver.com/example_id/123456789
```

실행할 `blogId`는 `example_id`다.

```bash
node scripts/crawl_naver_blog.mjs --blogId example_id --user ryze_yn
```

## 저장 위치

수집 데이터는 프로젝트의 사용자별 저장소 아래에 들어간다.

```text
storage/users/<user>/corpus/
  naver/
    <blogId>/
      articles/   # Markdown 변환 글
      raw/        # 원본 HTML
      metadata/   # 글별 JSON 메타데이터
      assets/     # 이미지 파일, --download-images 사용 시 저장
      jobs/       # 실행 로그 JSON
      index.jsonl # 블로그별 글 인덱스
```

`--user ryze_yn`으로 실행하면 실제 위치는 아래와 같다.

```text
storage/users/ryze_yn/corpus/naver/ranto28/
```

## 네이버가 아닌 블로그

괜찮다. 코퍼스 저장 구조는 네이버 블로그 전용이 아니다.
다만 현재 실행 스크립트 `scripts/crawl_naver_blog.mjs`는 네이버 블로그 전용이다.

다른 사이트를 수집할 때는 같은 저장 규칙을 쓰고,
사이트별 crawler만 따로 추가한다.

```text
scripts/crawl_naver_blog.mjs      # 네이버 블로그
scripts/crawl_tistory_blog.mjs    # 티스토리 추가 시
scripts/crawl_substack.mjs        # Substack 추가 시
scripts/crawl_generic_rss.mjs     # RSS 기반 수집 추가 시
```

사이트가 달라도 최종 산출물은 아래 형식을 맞춘다.

```text
<source>/<collection_id>/
  articles/<source>-<source_id>.md
  raw/<source>-<source_id>.html
  metadata/<source>-<source_id>.json
  assets/<source>-<source_id>/
  index.jsonl
```

메타데이터에는 최소한 아래 필드를 유지한다.

```json
{
  "id": "source-id",
  "source": "site_name",
  "author": "author_name",
  "title": "post title",
  "url": "canonical url",
  "publishedAtText": "published text from source",
  "fetchedAt": "ISO timestamp",
  "contentHash": "sha256",
  "markdownPath": "articles/source-id.md"
}
```

즉, 분석 단계에서는 네이버인지 티스토리인지보다
블로그/사이트별 폴더 아래의 `articles/`, `metadata/`, `index.jsonl` 형식이
일정한지가 더 중요하다.

## 자주 쓰는 실행 옵션

### 일부만 테스트

처음 보는 블로그는 전체 수집 전에 `--limit`으로 몇 개만 테스트한다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --limit 5
```

### 요청 간격 조절

기본 요청 간격은 `700ms`다. 너무 빠르게 때리지 않으려면 늘린다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --delayMs 1200
```

### 특정 페이지부터 재시작

목록 페이지 기준으로 중간부터 다시 돌릴 수 있다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --startPage 20
```

### 특정 시각 이후 글만 수집

`--since`에 ISO 8601 시각을 주면 목록의 게시 시각이 그 경계보다 오래된 지점에서
수집을 끝낸다. 제한 백필 뒤 자동 새 글 수집에도 같은 경계를 유지하려면 블로그
레지스트리의 `crawlSince`에 동일한 정규화 시각을 저장한다.

```bash
node scripts/crawl_naver_blog.mjs \
  --blogId BLOG_ID \
  --user ryze_yn \
  --since 2026-07-14T07:40:00.000Z
```

### 기존 글 다시 덮어쓰기

기본값은 이미 저장된 Markdown 파일이 있으면 건너뛴다.
본문 파서 수정 후 다시 저장하려면 `--force`를 쓴다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --force
```

### 이미지까지 다운로드

기본값은 이미지 URL과 placeholder만 기록한다.
이미지 파일까지 저장하려면 `--download-images`를 붙인다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --download-images
```

이미지 다운로드는 훨씬 느리고 저장 공간을 많이 쓴다.
이미지 요청 간격은 따로 조절할 수 있다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --download-images --imageDelayMs 500
```

## 결과 확인

수집된 글 개수:

```bash
find storage/users/ryze_yn/corpus/naver/BLOG_ID/articles -name 'naver-BLOG_ID-*.md' | wc -l
```

전체 인덱스 줄 수:

```bash
wc -l storage/users/ryze_yn/corpus/naver/BLOG_ID/index.jsonl
```

최근 실행 로그:

```bash
ls -t storage/users/ryze_yn/corpus/naver/BLOG_ID/jobs | head
```

특정 실행 로그 보기:

```bash
sed -n '1,220p' storage/users/ryze_yn/corpus/naver/BLOG_ID/jobs/JOB_ID.json
```

실행 로그의 핵심 필드는 아래다.

```text
discovered  발견한 글 수
saved       새로 저장한 글 수
skipped     이미 있어서 건너뛴 글 수
failed      저장 실패한 글 수
lastPage    마지막으로 읽은 목록 페이지
done        정상 종료 여부
errors      실패한 글 목록
```

## 현재 ranto28 수집 결과

2026-07-08 실행 기준:

```text
blogId: ranto28
discovered: 2468
saved: 2465
skipped: 3
failed: 0
lastPage: 104
```

이미 테스트와 단건 수집으로 저장된 3개가 있었기 때문에
전체 실행에서는 2,465개가 새로 저장되었다.
최종 Markdown 파일 수는 2,468개다.
현재 위치는 아래다.

```text
storage/users/ryze_yn/corpus/naver/ranto28/
```

## 막힐 때 확인 순서

먼저 요청 속도를 낮춘다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --delayMs 2000
```

그다음 일부만 테스트해서 목록 API와 글 HTML 중 어디서 막히는지 본다.

```bash
node scripts/crawl_naver_blog.mjs --blogId BLOG_ID --user ryze_yn --limit 3
```

로그에서 `post list failed HTTP ...`가 나오면 목록 API 단계에서 막힌 것이다.
`post fetch failed HTTP ...` 또는 `post body marker not found`가 나오면 개별 글 HTML 단계에서 막힌 것이다.

외부 도구를 검토해야 한다면 `~/longshot-wiki/tools/` 아래의 brave, tavily,
yahoo, toss, nodemaven, cf-bypass 관련 메모를 먼저 확인한다.
다만 우선순위는 아래 순서로 둔다.

```text
1. 공개적으로 열리는 모바일 API 사용
2. 요청 간격 증가
3. 실패 글만 재시도
4. 로그인/권한이 필요한 글인지 확인
5. 그래도 안 되면 별도 브라우저/프록시 기반 수집 도구 검토
```

보호 장치를 우회하기 위한 공격적인 방식보다,
접근 가능한 공개 페이지를 안정적으로 천천히 수집하는 쪽을 기본값으로 둔다.

## 주의

이 코퍼스는 원문 보관용 데이터다.
외부 공개, 재배포, 대량 인용은 저작권 문제가 생길 수 있으니
프로젝트 내부 분석과 개인 연구 용도로만 다룬다.
