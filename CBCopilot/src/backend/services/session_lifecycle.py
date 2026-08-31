"""Background scanner: auto-close idle sessions + auto-destroy post-retention.

Runs every `SCAN_INTERVAL_SECONDS` from `main.py`'s lifespan. For each active
session in `session_store`:

1. If status == "active" AND now - last_activity > frontend.auto_close_hours:
   flip to status=completed, stamp `completed_at`. No summary is generated —
   auto-closed means the user left without saying goodbye; the summary is
   only produced when they explicitly click End Session (the polling
   `_process_close` path).

2. If status == "completed" AND frontend.auto_destroy_hours > 0 AND
   now - completed_at > auto_destroy_hours:
   call `session_store.destroy_session(token)` (rm -rf the tree, drop caches).

`auto_destroy_hours = 0` means "never auto-destroy" (default, SPEC §4.6).

Session settings come from Sprint 4A `session_settings_store` — per-frontend
overrides with concrete defaults (48 / 72 / 0).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.services import session_settings_store
from src.services.session_store import store as session_store

logger = logging.getLogger("session_lifecycle")

SCAN_INTERVAL_SECONDS = 300  # 5 minutes; SPEC §4.6 recommends this


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _load_settings(frontend_id: str) -> dict[str, int]:
    """Resolve effective session settings for a frontend. Falls back to
    defaults when no override exists (Sprint 4A concrete defaults)."""
    s = session_settings_store.load(frontend_id)
    if s is not None:
        return {
            "auto_close_hours": int(s.auto_close_hours),
            "auto_destroy_hours": int(s.auto_destroy_hours),
        }
    # No override: use Sprint 4A defaults (48/72/0)
    from src.services.session_settings_store import SessionSettings
    defaults = SessionSettings()
    return {
        "auto_close_hours": int(defaults.auto_close_hours),
        "auto_destroy_hours": int(defaults.auto_destroy_hours),
    }


async def _tick() -> None:
    """One lifecycle pass over every active/completed session in the cache."""
    now = datetime.now(timezone.utc)
    sessions = session_store.list_sessions()
    closed_count = 0
    destroyed_count = 0

    for s in sessions:
        token = s["token"]
        frontend_id = s.get("frontend_id") or ""
        status = s.get("status", "active")
        cfg = _load_settings(frontend_id)

        if status == "active":
            last = _parse_iso(s.get("last_activity"))
            if not last:
                continue
            idle_hours = (now - last).total_seconds() / 3600.0
            if idle_hours >= cfg["auto_close_hours"]:
                _close_auto(token, now)
                closed_count += 1
            continue

        if status == "completed":
            if cfg["auto_destroy_hours"] <= 0:
                continue  # never destroy
            closed_at = _parse_iso(_fetch_completed_at(token))
            if not closed_at:
                continue
            age_hours = (now - closed_at).total_seconds() / 3600.0
            if age_hours >= cfg["auto_destroy_hours"]:
                if session_store.destroy_session(token):
                    destroyed_count += 1

    if closed_count or destroyed_count:
        logger.info(f"Lifecycle tick: {closed_count} auto-closed, {destroyed_count} auto-destroyed")


def _fetch_completed_at(token: str) -> str | None:
    """The session cache carries the legacy fields; `completed_at` is only
    written when we explicitly close. Read it from the in-memory session dict."""
    session = session_store.get_session(token)
    if not session:
        return None
    return session.get("completed_at")


def _close_auto(token: str, now: datetime) -> None:
    """Mark a session completed without running the summary flow (auto-close
    means the user abandoned it — no summary delivery expected)."""
    session = session_store.get_session(token)
    if not session:
        return
    session["status"] = "completed"
    session["completed_at"] = now.isoformat()
    session.setdefault("auto_closed", True)
    # Persist via the internal API
    session_store.set_status(token, "completed")
    # Bit of a hack: set_status doesn't know about completed_at. The save_meta
    # it triggers picks up the fields we set directly above because session
    # is the same dict reference stored in _cache.
    logger.info(f"Session auto-closed after idle: {token}")


async def lifecycle_loop() -> None:
    """Background task entry point. Survives exceptions — the scanner must
    keep running even when one session's settings are malformed."""
    logger.info(f"Session lifecycle scanner started (interval {SCAN_INTERVAL_SECONDS}s)")
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            logger.info("Session lifecycle scanner cancelled")
            raise
        except Exception as e:
            logger.exception(f"Lifecycle tick crashed: {e}")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
