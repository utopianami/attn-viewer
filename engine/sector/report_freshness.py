"""Collection provenance shared by the scheduled and manual publication paths."""
from datetime import datetime, timezone

FRESH_MAX_AGE_S = 3600


def publication_freshness(snapshot: dict, *, now=None) -> dict:
    """Age the inputs actually used; later collection cannot repair this snapshot."""
    now = now or datetime.now(timezone.utc)
    elapsed = (now - datetime.fromisoformat(snapshot["checked_at"])).total_seconds()
    oldest = snapshot["oldest_age_s"]
    oldest = oldest + elapsed if oldest is not None else None
    state = snapshot["state"]
    if state == "fresh" and (elapsed < 0 or oldest is None
                             or not 0 <= oldest <= FRESH_MAX_AGE_S):
        state = "stale"
    return {**snapshot, "initial_state": snapshot["state"], "state": state,
            "publication_check": {"checked_at": now.isoformat(), "state": state,
                                  "elapsed_since_input_check_s": elapsed,
                                  "oldest_age_s": oldest}}


def collection_freshness(store, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    status = store.read_status()
    run = status.get("_run") or {}
    collectors = {name: value for name, value in status.items()
                  if not name.startswith("_") and isinstance(value, dict)
                  and value.get("status") != "missing_key"}
    def has_usable_output(value: dict) -> bool:
        return any(isinstance(value.get(key), int) and value[key] > 0
                   for key in ("items", "observations"))

    # ``ok`` with zero new rows is a valid empty poll.  A degraded poll is
    # usable only when at least one source still returned current material.
    degraded = sorted(name for name, value in collectors.items()
                      if value.get("status") == "degraded" and has_usable_output(value))
    failed = sorted(name for name, value in collectors.items()
                    if value.get("status") != "ok" and name not in degraded)
    stale = []
    ages = []
    for name, value in collectors.items():
        try:
            stamp = datetime.fromisoformat(value.get("at") or "")
            stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
            age = (now - stamp).total_seconds()
            ages.append(age)
            if not 0 <= age <= FRESH_MAX_AGE_S:
                stale.append(name)
        except (TypeError, ValueError):
            stale.append(name)
    state = ("failed" if failed or run.get("state") not in (None, "completed")
             else "missing" if not collectors
             else "stale" if stale else "fresh")
    return {"state": state, "checked_at": now.isoformat(),
            "max_age_s": FRESH_MAX_AGE_S, "oldest_age_s": max(ages) if ages else None,
            "failed_collectors": failed, "degraded_collectors": degraded,
            "stale_collectors": sorted(stale),
            "run_state": run.get("state"), "run_id": run.get("id")}
