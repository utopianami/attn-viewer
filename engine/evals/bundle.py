# engine/evals/bundle.py
"""frozen evidence bundle (스펙 1부). capture는 불변 — 덮어쓰기 거부 + content hash."""
from __future__ import annotations

import hashlib
import json
import re as _re
import time
from pathlib import Path

from sector.contracts import MetricObservation, SectorCard


_EVALS_DIR = Path(__file__).parent


def resolve_bundle_path(case: dict, base: Path | None = None) -> Path:
    """케이스 row의 bundle 경로를 절대 Path로 변환.

    bundle_path가 절대경로이면 그대로 반환.
    상대경로이면 base (기본값: engine/evals/ 이 모듈 디렉토리) 기준으로 해석.
    bundle_path가 없으면 base/bundles/<case['id']> 기본값 사용.

    base를 명시하면 테스트에서 tmp_path를 주입할 수 있다.
    이 함수 하나만 쓰면 CWD와 무관하게 항상 올바른 경로를 얻는다.
    """
    _base = Path(base) if base is not None else _EVALS_DIR
    raw = case.get("bundle_path")
    if not raw:
        return _base / "bundles" / case["id"]
    p = Path(raw)
    if p.is_absolute():
        return p
    return _base / p


def _content_hash(root: Path, manifest: dict) -> str:
    """상대경로+파일 내용 + content_hash 제외 manifest 정규형을 함께 해시 (r2-B3 —
    manifest의 as_of/availability/urls 변조도 hash로 잡는다)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    canon = {k: v for k, v in manifest.items() if k != "content_hash"}
    h.update(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def capture_bundle(store, out_dir: Path | str, *, as_of: str, availability: str,
                   ra_docs: list[dict], prices: dict, macro: dict,
                   empty_reasons: dict[str, str] | None = None,
                   thesis_store=None) -> Path:
    """proven 불변식은 이 함수가 강제한다 (r3-B4 — CLI·운영 문구가 아니라 코드):
    proven인데 채널이 비면 empty_reasons에 채널별 사유 필수, 없으면 ValueError."""
    out = Path(out_dir)
    empty_reasons = empty_reasons or {}
    if out.exists():
        raise FileExistsError(f"bundle exists — 불변성 위반 금지: {out}")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if availability == "proven":
        if as_of != today:
            raise ValueError(f"proven은 as_of=captured_at({today})만 허용 (스펙 r4-B4)")
        for ch, empty in (("ra", not ra_docs), ("quotes", not prices.get("quotes")),
                          ("macro", not macro)):
            if empty and ch not in empty_reasons:
                raise ValueError(f"proven인데 {ch} 채널이 비어 있음 — 사유 필수 (r3-B4)")
    (out / "metrics").mkdir(parents=True)
    cards = [c for c in store.read_cards(days=None, limit=100_000)
             if c.ts[:10] <= as_of]                     # limit=500 함정 회피 (B4)
    (out / "cards.jsonl").write_text("\n".join(c.model_dump_json() for c in cards))
    metric_names = sorted(p.stem for p in (Path(store.root) / "metrics").glob("*.jsonl"))
    for m in metric_names:
        rows = [o for o in store.read_metric(m, last_n=100_000) if o.ts[:10] <= as_of]
        (out / "metrics" / f"{m}.jsonl").write_text(
            "\n".join(o.model_dump_json() for o in rows))
    dated = [d for d in ra_docs
             if (d.get("published_at") or "")[:10] and d["published_at"][:10] <= as_of]
    (out / "ra_docs.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in dated))
    (out / "prices.json").write_text(json.dumps(prices, ensure_ascii=False))
    (out / "macro.json").write_text(json.dumps(macro, ensure_ascii=False))
    thesis_revisions: list[str] = []
    if thesis_store is not None:
        ids = sorted({e.id for e in thesis_store._read_all()})
        selected = [r for r in (thesis_store.latest_as_of(tid, as_of) for tid in ids)
                    if r is not None]
        (out / "theses.jsonl").write_text(
            "\n".join(r.model_dump_json() for r in selected))
        thesis_revisions = [r.revision_id for r in selected]
    manifest = {"as_of": as_of, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                             time.gmtime()),
                "availability": availability, "card_ids": [c.id for c in cards],
                "urls": sorted({c.url for c in cards if c.url}
                               | {d["url"] for d in dated if d.get("url")}),
                "metric_names": metric_names,
                "thesis_revisions": thesis_revisions,  # 2부 T7 — as_of 날짜 경계로 선택
                "news_ids": [d["id"] for d in dated if d.get("id")],
                # 실제 ref는 yahoo:{q["symbol"]} (price_macro.py:42) — token 폴백 없음
                # (r6: symbol 없는 quote 행은 provenance 등록 불가 = 인용 불가가 맞다)
                "quote_symbols": [q["symbol"] for q in prices.get("quotes", [])
                                  if q.get("symbol")],
                "macro_keys": sorted(macro.keys()),
                "empty_channel_reasons": empty_reasons,   # proven 검증용 (r3-B4)
                "dropped_undated_docs": len(ra_docs) - len(dated)}
    manifest["content_hash"] = _content_hash(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return out


# ---------------------------------------------------------------------------
# 읽기 측: BundleSectorStore / EvalBundle
# ---------------------------------------------------------------------------

_URL_RE = _re.compile(r"https?://[^\s\)\]>\"']+", _re.IGNORECASE)


class BundleSectorStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cards = [SectorCard.model_validate_json(l)
                       for l in (self.root / "cards.jsonl").read_text().splitlines()
                       if l.strip()]

    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   entity: str | None = None, limit: int = 500) -> list[SectorCard]:
        out = self._cards                               # 이미 as_of로 잘림 — days 무시
        if axis:
            out = [c for c in out if c.axis == axis]
        if entity:
            out = [c for c in out if entity in (c.entities or [])]
        return out[:limit]

    def read_metric(self, metric: str, *, last_n: int = 90) -> list[MetricObservation]:
        p = self.root / "metrics" / f"{metric}.jsonl"
        if not p.exists():
            return []
        rows = [MetricObservation.model_validate_json(l)
                for l in p.read_text().splitlines() if l.strip()]
        return rows[-last_n:]

    def get_state(self, key: str):
        return None


class EvalBundle:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())

    def verify_hash(self) -> bool:
        return _content_hash(self.root, self.manifest) == self.manifest.get("content_hash")

    def snapshot(self) -> dict:
        """price_macro 주입용 단일 스냅샷 — prices와 macro를 함께 (r2-B3)."""
        p = self.prices()
        return {"quotes": p.get("quotes", []), "macro": self.macro()}

    def store(self) -> BundleSectorStore:
        return BundleSectorStore(self.root)

    def ra_news_items(self) -> list[dict]:
        p = self.root / "ra_docs.jsonl"
        return ([json.loads(l) for l in p.read_text().splitlines() if l.strip()]
                if p.exists() else [])

    def theses(self) -> list[dict]:
        """캡처 시점 선택된 thesis revision들 (2부 T7) — 없으면 [] (하위호환)."""
        p = self.root / "theses.jsonl"
        return ([json.loads(l) for l in p.read_text().splitlines() if l.strip()]
                if p.exists() else [])

    def prices(self) -> dict:
        return json.loads((self.root / "prices.json").read_text())

    def macro(self) -> dict:
        return json.loads((self.root / "macro.json").read_text())

    def bundle_text(self, max_chars: int = 14000) -> str:
        st = self.store()
        parts = [f"{c.id}: {c.title} — {c.raw_quote[:150]}"
                 for c in st.read_cards(days=None, limit=100_000)]
        for m in self.manifest.get("metric_names", []):
            rows = st.read_metric(m, last_n=6)
            if rows:
                parts.append(f"{m}: " + ", ".join(f"{o.ts}={o.value}{o.unit}"
                                                   for o in rows))
        for q in (self.prices().get("quotes") or []):
            parts.append(f"price:{json.dumps(q, ensure_ascii=False)[:150]}")
        if self.macro():
            parts.append(f"macro:{json.dumps(self.macro(), ensure_ascii=False)[:300]}")
        parts += [f"doc:{d.get('url', '')}: {str(d.get('snippet') or d.get('title', ''))[:150]}"
                  for d in self.ra_news_items()]
        return "\n".join(parts)[:max_chars]

    def full_text(self) -> str:
        """위반 검사 전용 — 카드 raw_quote **전문** 포함 (bundle_text는 150자 절단이라
        본문 깊숙한 URL이 누락돼 오탐 — 2026-07-20 베이스라인 실측)."""
        st = self.store()
        parts = [f"{c.id}: {c.title}\n{c.url}\n{c.raw_quote}"
                 for c in st.read_cards(days=None, limit=100_000)]
        parts.append(json.dumps(self.prices(), ensure_ascii=False))
        parts.append(json.dumps(self.macro(), ensure_ascii=False))
        parts += [json.dumps(d, ensure_ascii=False) for d in self.ra_news_items()]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 관련성 기반 컨텍스트 — judge 입력 전용
    # ------------------------------------------------------------------

    @staticmethod
    def _score_line(line: str, answer_md: str, rubric: dict,
                    answer_nums: list[str], query_tokens: set[str]) -> int:
        """후보 라인의 관련성 점수 계산.

        ①rubric["evidence"] 항목 문자열 포함 +3
        ②답변의 [근거:...] 토큰(쉼표 분해) 포함 +2
        ③답변에 등장하는 숫자 문자열(3자리 이상) 포함 +1
        ④질문·rubric의 mechanism/state_link 텍스트와 공통 명사(2자+ 한글/영문 토큰) 겹침 +1
        """
        score = 0
        for ev in (rubric.get("evidence") or []):
            if str(ev) in line:
                score += 3
                break
        cite_re = _re.compile(r"\[근거:([^\]]+)\]")
        for grp in cite_re.findall(answer_md):
            for tok in (t.strip() for t in grp.split(",") if t.strip()):
                if tok in line:
                    score += 2
                    break
        for num in answer_nums:
            if num in line:
                score += 1
                break
        line_tokens = set(_re.findall(r"[A-Za-z가-힣]{2,}", line))
        if line_tokens & query_tokens:
            score += 1
        return score

    def judge_context(self, answer_md: str, rubric: dict,
                      max_chars: int = 20000) -> str:
        """관련성 선발 컨텍스트 — judge 입력 전용 (head-truncate 아티팩트 해소).

        항상 포함: 지표 라인 전부 + 가격/매크로 라인.
        카드/ra_doc 라인은 관련성 점수 내림차순(동점은 원본 순서 유지)으로
        max_chars까지 채운 뒤, 남는 공간에 미선택 최신 카드 몇 장 추가.
        """
        st = self.store()

        # ── 항상 포함: 지표·가격·매크로 ─────────────────────────────────
        fixed_parts: list[str] = []
        for m in self.manifest.get("metric_names", []):
            rows = st.read_metric(m, last_n=6)
            if rows:
                fixed_parts.append(
                    f"{m}: " + ", ".join(
                        f"{o.ts}={o.value}{o.unit}" for o in rows
                    )
                )
        for q in (self.prices().get("quotes") or []):
            fixed_parts.append(f"price:{json.dumps(q, ensure_ascii=False)[:150]}")
        if self.macro():
            fixed_parts.append(f"macro:{json.dumps(self.macro(), ensure_ascii=False)[:300]}")

        fixed_text = "\n".join(fixed_parts)
        budget = max_chars - len(fixed_text) - (1 if fixed_text else 0)

        # ── 후보: 카드 + ra_doc 라인 ─────────────────────────────────────
        cards = st.read_cards(days=None, limit=100_000)
        card_lines = [
            f"{c.id}: {c.title} — {c.raw_quote[:150]}" for c in cards
        ]
        doc_lines = [
            f"doc:{d.get('url', '')}: "
            f"{str(d.get('snippet') or d.get('title', ''))[:150]}"
            for d in self.ra_news_items()
        ]

        # ── 관련성 사전 계산 ─────────────────────────────────────────────
        answer_nums = _re.findall(r"\d{3,}", answer_md)
        query_tokens: set[str] = set()
        for field in ("mechanism", "state_link"):
            txt = (rubric.get(field) or "")
            query_tokens.update(_re.findall(r"[A-Za-z가-힣]{2,}", txt))

        candidates: list[tuple[int, int, str]] = []  # (score, orig_idx, line)
        for i, line in enumerate(card_lines + doc_lines):
            s = self._score_line(line, answer_md, rubric, answer_nums, query_tokens)
            candidates.append((s, i, line))

        # 점수 내림차순, 동점은 원본 순서(orig_idx) 유지
        candidates.sort(key=lambda x: (-x[0], x[1]))

        selected: list[str] = []
        selected_indices: set[int] = set()
        remaining = budget
        for score, idx, line in candidates:
            needed = len(line) + 1  # +1 for newline
            if remaining <= 0:
                break
            if needed <= remaining:
                selected.append(line)
                selected_indices.add(idx)
                remaining -= needed

        # ── 남는 공간에 미선택 최신 카드 추가 ───────────────────────────
        n_cards = len(card_lines)
        for i, line in enumerate(card_lines):
            if i in selected_indices:
                continue
            needed = len(line) + 1
            if remaining <= 0:
                break
            if needed <= remaining:
                selected.append(line)
                remaining -= needed

        parts = []
        if fixed_text:
            parts.append(fixed_text)
        parts.extend(selected)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# as_of 위반 검출: find_violations
# ---------------------------------------------------------------------------

_CITE_RE = _re.compile(r"\[근거:([^\]]+)\]")           # 브래킷 전체 캡처 (r4-B1)


def _norm_url(u: str) -> str:
    """URL 정규화 — scheme·host 소문자화, path 이하 대소문자 보존, 끝 '/' 제거.

    예: HTTPS://Example.com/Article/ → https://example.com/Article
    path 대소문자는 보존해 대소문자 민감 경로의 위반 누락을 방지 (I-1)."""
    m = _re.match(r"(https?://)([^/]+)(.*)", u, _re.IGNORECASE)
    if not m:
        return u
    scheme_host = m.group(1).lower() + m.group(2).lower()
    path = m.group(3).rstrip("/")
    return scheme_host + path


def _allowed_cite_tokens(manifest: dict, layers: list[dict],
                         extra_toks: set[str] | None = None) -> set[str]:
    """무조건 허용 태그 없음 (r3/r4-B1) — 전부 실제 provenance에 결속:
    - 카드 ID·NewsItem ID·정확 URL·도메인/1레벨 라벨 (manifest)
    - 가격: 실제 ref 형식 그대로 `yahoo:<symbol>` (price_macro.py:42) — quote_symbols
      기반, bare `yahoo`/bare symbol은 등록하지 않음 (정상 인용 오탐·과허용 모두 방지)
    - macro: `macro:<key>` (macro_keys 기반)
    - calc: 이번 실행의 calc 레이어가 실제 생성한 claim id만 (`calc:<id>` — 무조건
      허용 폐지, 실생성 근거 결속)
    - sector_rag: cards 존재 시 `섹터 지표`·`섹터 카드` 별칭
    - da_blind: unit_answers 비어있지 않을 때만 `da_gpt`·`da_fable`
    - extra_toks: full_text 추출 URL의 도메인/1레벨 라벨 (호출측 주입)"""
    toks = (set(manifest.get("card_ids", []))
            | set(manifest.get("news_ids", []))
            | set(manifest.get("urls", [])))
    for u in manifest.get("urls", []):
        host = _re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        toks.add(host)
        toks.add(host.split(".")[0])                   # fnnews.com → fnnews
    toks.update(f"yahoo:{s}" for s in manifest.get("quote_symbols", []))
    toks.update(f"macro:{k}" for k in manifest.get("macro_keys", []))
    for l in layers:                                    # calc 실생성 결속 (r4·r5-B1)
        if l.get("name") == "calc":
            # 실제 레이어 구조는 data.results[*].{metric, ok, value} (orchestrator.py:351)
            ok_metrics = [r["metric"] for r in (l.get("data") or {}).get("results", [])
                          if r.get("ok") and r.get("metric")]
            toks.update(f"calc:{m}" for m in ok_metrics)
            if ok_metrics:
                toks.add("calc")                        # bare calc도 실생성 있을 때만
        if l.get("name") == "sector_rag":               # sector_rag 별칭 (cards 존재 시)
            cards = (l.get("data") or {}).get("cards") or []
            if cards:
                toks.update({"섹터 지표", "섹터 카드"})
        if l.get("name") == "da_blind":                # DA 실행 레이어 결속 (orchestrator.py:290)
            unit_answers = (l.get("data") or {}).get("unit_answers") or []
            models_present = {u.get("model") for u in unit_answers if u.get("model")}
            if "da_gpt" in models_present:              # 모델별 결속 — 존재하는 모델만 허용
                toks.add("da_gpt")
            if "da_fable" in models_present:
                toks.add("da_fable")
    if extra_toks:
        toks.update(extra_toks)
    return toks


def find_violations(layers: list[dict], answer_md: str, manifest: dict,
                    bundle_text: str = "") -> tuple[list[str], list[str], int]:
    """전 레이어 재귀 URL 수집 + 답변 URL + [근거:토큰] 검사 (r2-B1).

    모든 [근거:토큰]은 (쉼표 분해 후) provenance로 해소돼야 한다.
    서술형/식별자형 분리 없음 — 해소 안 되면 전부 violation.

    허용 소스:
      - manifest 파생 토큰(card_ids·news_ids·urls·도메인/1레벨 라벨·yahoo:<symbol>·macro:<key>)
      - bundle full_text에서 정규식으로 추출한 URL들의 정확 정규화 일치 (임의 부분문자열 금지)
        + 그 URL들의 도메인/1레벨 라벨
      - 레이어 결속 별칭: calc ok metric → calc/calc:<metric>;
        sector_rag cards 존재 → 섹터 지표·섹터 카드;
        da_blind unit_answers 비어있지 않을 때만 → da_gpt·da_fable
      - 위 어디에도 해소 안 되면 violation

    URL 검사: manifest.urls ∪ full_text 추출 URL의 정규화 정확 일치만 허용.
    부분문자열 검사 제거.

    반환:
      (violations, [], da_cited)
      - violations: URL 위반 + 미해소 cite 토큰 (서술형 포함 전부)
      - []: 하위호환 빈 리스트 (unresolved_cites 개념 폐지)
      - da_cited: DA 별칭(da_gpt/da_fable)으로 해소된 cite 토큰 수"""
    # allowed URL set: manifest + full_text 추출 URL 정규화 합집합
    allowed_norm: set[str] = {_norm_url(u) for u in manifest.get("urls", [])}

    # full_text(bundle_text) URL 추출 → allowed_norm + 도메인 라벨 (임의 부분문자열 금지)
    _fulltext_domain_toks: set[str] = set()
    if bundle_text:
        for raw_u in _URL_RE.findall(bundle_text):
            raw_u = raw_u.rstrip(".,")
            if raw_u.lower().startswith("http"):
                normed = _norm_url(raw_u)
                allowed_norm.add(normed)
                host = _re.sub(r"^https?://(www\.)?", "", normed).split("/")[0]
                _fulltext_domain_toks.add(host)
                _fulltext_domain_toks.add(host.split(".")[0])

    allowed_toks = _allowed_cite_tokens(manifest, layers, extra_toks=_fulltext_domain_toks)

    found: list[str] = []
    _da_aliases = {"da_gpt", "da_fable"}
    da_cited = 0

    def _check(u):
        if not (isinstance(u, str) and u.lower().startswith("http")):
            return
        if _norm_url(u) in allowed_norm:
            return
        if u not in found:
            found.append(u)

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "url":
                    _check(v)
                else:
                    _walk(v)
        elif isinstance(node, list):
            for it in node:
                _walk(it)

    for l in layers:
        _walk(l.get("data") or {})
    for u in _URL_RE.findall(answer_md or ""):
        _check(u.rstrip(".,"))
    for grp in _CITE_RE.findall(answer_md or ""):      # 쉼표 구분 근거 전수 검사 (r4-B1)
        for tok in (t.strip() for t in grp.split(",")):
            if not tok:
                continue
            if tok in allowed_toks:
                if tok in _da_aliases:
                    da_cited += 1                       # DA 별칭 해소 카운트 (스펙 DA 잔여 위험)
            else:
                if f"cite:{tok}" not in found:
                    found.append(f"cite:{tok}")
    return found, [], da_cited
