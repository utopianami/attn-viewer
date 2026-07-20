# engine/evals/bundle.py
"""frozen evidence bundle (스펙 1부). capture는 불변 — 덮어쓰기 거부 + content hash."""
from __future__ import annotations

import hashlib
import json
import re as _re
import time
from pathlib import Path

from sector.contracts import MetricObservation, SectorCard


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
                   empty_reasons: dict[str, str] | None = None) -> Path:
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
    manifest = {"as_of": as_of, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                             time.gmtime()),
                "availability": availability, "card_ids": [c.id for c in cards],
                "urls": sorted({c.url for c in cards if c.url}
                               | {d["url"] for d in dated if d.get("url")}),
                "metric_names": metric_names, "thesis_revisions": [],  # 2부에서 채움
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

_URL_RE = _re.compile(r"https?://[^\s\)\]>\"']+")


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


def _allowed_cite_tokens(manifest: dict, layers: list[dict]) -> set[str]:
    """무조건 허용 태그 없음 (r3/r4-B1) — 전부 실제 provenance에 결속:
    - 카드 ID·NewsItem ID·정확 URL·도메인/1레벨 라벨 (manifest)
    - 가격: 실제 ref 형식 그대로 `yahoo:<symbol>` (price_macro.py:42) — quote_symbols
      기반, bare `yahoo`/bare symbol은 등록하지 않음 (정상 인용 오탐·과허용 모두 방지)
    - macro: `macro:<key>` (macro_keys 기반)
    - calc: 이번 실행의 calc 레이어가 실제 생성한 claim id만 (`calc:<id>` — 무조건
      허용 폐지, 실생성 근거 결속)"""
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
        if l.get("name") == "da_blind":                # DA 실행 레이어 결속 (orchestrator.py:290)
            toks.update({"da_gpt", "da_fable"})        # unit_answers 모델 토큰 허용
    return toks


_KOREAN_RE = _re.compile(r"[ㄱ-힣]")


def find_violations(layers: list[dict], answer_md: str, manifest: dict,
                    bundle_text: str = "") -> tuple[list[str], list[str]]:
    """전 레이어 재귀 URL 수집 + 답변 URL + [근거:토큰] 검사 (r2-B1).

    레이어 이름을 열거하지 않는다 — 어떤 증거 레이어(ra_x·ra_web·news_summary·
    sector_rag·이후 추가분)든 dict/list를 재귀로 걸어 'url' 키를 전부 수집.

    URL 비교는 _norm_url로 정규화 후 수행 (I-1 — scheme·host 대소문자 + 끝 슬래시 오탐 제거).
    found에는 진단 편의를 위해 원문 URL을 남긴다.

    반환:
      (violations, unresolved_cites)
      - violations: URL 위반 + 식별자형 미등록 cite 토큰
      - unresolved_cites: 서술형(한글/공백 포함) cite 토큰 — 위반 아님"""
    allowed_norm = {_norm_url(u) for u in manifest.get("urls", [])}
    allowed_toks = _allowed_cite_tokens(manifest, layers)
    found: list[str] = []
    unresolved: list[str] = []

    def _check(u):
        if not (isinstance(u, str) and u.startswith("http")):
            return
        if _norm_url(u) in allowed_norm:
            return
        # URL이 bundle_text 본문에 부분문자열로 존재하면 허용
        # (raw_quote 내 인용 URL은 manifest.urls에 없어도 실재 근거임)
        if bundle_text and _norm_url(u) in bundle_text:
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
            # 서술형 판별: 공백 또는 한글 포함
            if " " in tok or _KOREAN_RE.search(tok):
                if f"cite:{tok}" not in unresolved:
                    unresolved.append(f"cite:{tok}")
            else:
                # 식별자형: allowed_toks 또는 bundle_text 부분일치면 허용
                if tok in allowed_toks:
                    pass
                elif bundle_text and tok in bundle_text:
                    pass
                elif f"cite:{tok}" not in found:
                    found.append(f"cite:{tok}")
    return found, unresolved
