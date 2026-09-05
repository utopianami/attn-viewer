"""Collection provenance shared by the scheduled and manual publication paths."""
from datetime import datetime, timezone

FRESH_MAX_AGE_S = 3600


def collection_freshness(store, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    status = store.read_status()
    run = status.get("_run") or {}
    collectors = {name: value for name, value in status.items()
                  if not name.startswith("_") and isinstance(value, dict)
                  and value.get("status") != "missing_key"}
    failed = sorted(name for name, value in collectors.items()
                    if value.get("status") != "ok")
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
            "failed_collectors": failed, "stale_collectors": sorted(stale),
            "run_state": run.get("state"), "run_id": run.get("id")}
