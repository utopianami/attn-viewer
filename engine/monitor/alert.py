"""알림 결정·발송 — 쿨다운/회복은 순수 함수(decide_sends), 발송은 텔레그램+jsonl.

텔레그램(ward 봇)은 .env TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 설정 시에만 발송.
미설정이면 alerts.jsonl 기록만 — 구조는 동일하게 동작해 토큰만 채우면 켜진다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from monitor.contracts import CheckResult

logger = logging.getLogger(__name__)

_LEVEL_ICON = {"alert": "🚨", "warn": "⚠️", "ok": "✅"}


def decide_sends(results: list[CheckResult], state: dict, now: dt.datetime,
                 cooldown_s: float) -> tuple[list[CheckResult], dict]:
    """발송 대상 선별 + 새 state 반환 (순수).

    state: {"{pipeline}/{check}": {"level": str, "sent_at": iso}}
    규칙: warn/alert는 최초·악화·쿨다운 경과 시 발송. ok는 직전이 warn/alert였을 때
    회복 알림 1회만.
    """
    order = {"ok": 0, "warn": 1, "alert": 2}
    to_send: list[CheckResult] = []
    new_state = dict(state)
    for r in results:
        key = f"{r.pipeline}/{r.check}"
        prev = state.get(key) or {}
        prev_level = prev.get("level", "ok")
        prev_sent = None
        try:
            prev_sent = dt.datetime.fromisoformat(prev["sent_at"])
        except (KeyError, ValueError, TypeError):
            pass
        if r.level == "ok":
            if prev_level != "ok":
                to_send.append(r.model_copy(update={"detail": f"회복: {r.detail}"}))
                new_state[key] = {"level": "ok", "sent_at": now.isoformat()}
            continue
        escalated = order[r.level] > order[prev_level]
        # warn은 등장·악화 시 1회만(영구 known-state 스팸 방지), alert만 쿨다운 재발송
        cooled = r.level == "alert" and (
            prev_sent is None or (now - prev_sent).total_seconds() >= cooldown_s)
        if prev_level == "ok" or escalated or cooled:
            to_send.append(r)
            new_state[key] = {"level": r.level, "sent_at": now.isoformat()}
        else:
            new_state[key] = {"level": r.level,
                              "sent_at": prev.get("sent_at", now.isoformat())}
    return to_send, new_state


def format_message(results: list[CheckResult]) -> str:
    lines = ["[attn-viewer 모니터]"]
    for r in results:
        lines.append(f"{_LEVEL_ICON.get(r.level, '')} {r.pipeline} · {r.check}"
                     f" ({r.axis}): {r.detail}")
    return "\n".join(lines)


def send_telegram(text: str, token: str, chat_id: str, timeout: float = 15) -> bool:
    """ward 봇 발송 — 실패해도 예외를 밖으로 내지 않는다 (never-block)."""
    import httpx
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000]}, timeout=timeout)
        if resp.status_code != 200:
            logger.error("monitor: 텔레그램 발송 실패 %s %s",
                         resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("monitor: 텔레그램 발송 예외 — %s", exc)
        return False


def process_alerts(results: list[CheckResult], monitor_dir: Path, now: dt.datetime,
                   *, cooldown_s: float, token: str = "", chat_id: str = "") -> dict:
    """state 로드 → 발송 결정 → jsonl 기록 → (토큰 있으면) 텔레그램 발송 → state 저장."""
    monitor_dir.mkdir(parents=True, exist_ok=True)
    state_path = monitor_dir / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    to_send, new_state = decide_sends(results, state, now, cooldown_s)
    sent_via = "none"
    if to_send:
        with open(monitor_dir / "alerts.jsonl", "a", encoding="utf-8") as f:
            for r in to_send:
                f.write(json.dumps({"at": now.isoformat(), **r.model_dump()},
                                   ensure_ascii=False) + "\n")
        if token and chat_id:
            # 4000자 단일 절단 대신 청크 발송 (codex #8)
            lines = format_message(to_send).splitlines()
            chunks, cur = [], ""
            for line in lines:
                if len(cur) + len(line) + 1 > 3500:
                    chunks.append(cur)
                    cur = ""
                cur = f"{cur}\n{line}" if cur else line
            chunks.append(cur)
            ok = all(send_telegram(c, token, chat_id) for c in chunks)
            sent_via = "telegram" if ok else "telegram_failed"
            if not ok:
                # sent로 기록하면 쿨다운에 묻힌다 — 상태를 되돌려 다음 주기 재시도
                new_state = state
        else:
            sent_via = "file_only"
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(state_path)
    return {"sent": len(to_send), "via": sent_via}
