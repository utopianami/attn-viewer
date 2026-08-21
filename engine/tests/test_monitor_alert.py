"""monitor.alert — 발송 결정(쿨다운·회복)·포맷 테스트 (오프라인)."""
from datetime import datetime, timedelta, timezone

from monitor.alert import decide_sends, format_message
from monitor.contracts import CheckResult

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
COOLDOWN = 6 * 3600


def _r(check="c1", pipeline="collector:rss", level="alert", axis="stability", detail="d"):
    return CheckResult(check=check, pipeline=pipeline, level=level, axis=axis, detail=detail)


def test_first_alert_is_sent():
    to_send, state = decide_sends([_r()], {}, NOW, COOLDOWN)
    assert len(to_send) == 1
    assert state["collector:rss/c1"]["level"] == "alert"


def test_repeat_within_cooldown_suppressed():
    _, state = decide_sends([_r()], {}, NOW, COOLDOWN)
    to_send, _ = decide_sends([_r()], state, NOW + timedelta(hours=1), COOLDOWN)
    assert to_send == []


def test_repeat_after_cooldown_sent_again():
    _, state = decide_sends([_r()], {}, NOW, COOLDOWN)
    to_send, _ = decide_sends([_r()], state, NOW + timedelta(hours=7), COOLDOWN)
    assert len(to_send) == 1


def test_warn_not_resent_after_cooldown():
    # warn은 등장 시 1회만 — ecos missing_key 같은 영구 상태의 반복 스팸 방지
    _, state = decide_sends([_r(level="warn")], {}, NOW, COOLDOWN)
    to_send, _ = decide_sends([_r(level="warn")], state, NOW + timedelta(days=3), COOLDOWN)
    assert to_send == []


def test_escalation_warn_to_alert_bypasses_cooldown():
    _, state = decide_sends([_r(level="warn")], {}, NOW, COOLDOWN)
    to_send, _ = decide_sends([_r(level="alert")], state, NOW + timedelta(minutes=5), COOLDOWN)
    assert len(to_send) == 1


def test_recovery_sent_once():
    _, state = decide_sends([_r()], {}, NOW, COOLDOWN)
    later = NOW + timedelta(hours=1)
    to_send, state = decide_sends([_r(level="ok")], state, later, COOLDOWN)
    assert len(to_send) == 1 and "회복" in to_send[0].detail or to_send[0].level == "ok"
    to_send, _ = decide_sends([_r(level="ok")], state, later + timedelta(hours=1), COOLDOWN)
    assert to_send == []


def test_ok_without_history_not_sent():
    to_send, _ = decide_sends([_r(level="ok")], {}, NOW, COOLDOWN)
    assert to_send == []


def test_format_message_mentions_pipeline_and_level():
    msg = format_message([_r(detail="rss 수집 실패")])
    assert "collector:rss" in msg and "rss 수집 실패" in msg


def test_telegram_failure_retries_next_run(tmp_path, monkeypatch):
    # 발송 실패 시 sent로 기록하면 안 됨 — 다음 주기에 재시도
    import monitor.alert as alert_mod
    monkeypatch.setattr(alert_mod, "send_telegram", lambda *a, **k: False)
    out1 = alert_mod.process_alerts([_r()], tmp_path, NOW, cooldown_s=COOLDOWN,
                                    token="t", chat_id="c")
    assert out1["via"] == "telegram_failed"
    out2 = alert_mod.process_alerts([_r()], tmp_path, NOW + timedelta(minutes=30),
                                    cooldown_s=COOLDOWN, token="t", chat_id="c")
    assert out2["sent"] == 1                      # 재시도됨 (억제 안 됨)
    monkeypatch.setattr(alert_mod, "send_telegram", lambda *a, **k: True)
    out3 = alert_mod.process_alerts([_r()], tmp_path, NOW + timedelta(hours=1),
                                    cooldown_s=COOLDOWN, token="t", chat_id="c")
    assert out3["via"] == "telegram"
    out4 = alert_mod.process_alerts([_r()], tmp_path, NOW + timedelta(hours=2),
                                    cooldown_s=COOLDOWN, token="t", chat_id="c")
    assert out4["sent"] == 0                      # 성공 후에는 쿨다운 억제
