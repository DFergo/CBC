"""watchdog-based RAG file watcher.

Watches `/app/data/` recursively. When a file is added, modified, or deleted
under any `documents/` folder we know about, the affected scope is debounced
for `DEBOUNCE_SECONDS` and then `rag_service.reindex(scope_key)` fires.

Per-scope debouncing means bulk-copying N PDFs into a single company
triggers ideally ONE rebuild for that company; unrelated scopes are not
affected.

Sprint 18 changes (the 20-file Amcor upload incident — three full reindex
passes in series, ~150 s total of redundant work):

1. Default debounce raised from 5 s → 30 s. Browser uploads pace at
   "one file every few seconds" while the user clicks through a file
   picker; 5 s isn't enough to coalesce them, 30 s is.
2. Absolute hold ceiling — `MAX_DEBOUNCE_HOLD_SECONDS = 300`. If files
   keep arriving for 5+ minutes the debouncer fires anyway so a slow
   upload doesn't park reindex forever.
3. Lock-aware fire — if `rag_service._build_locks[scope_key]` is held
   when the timer expires (a previous reindex is still running for this
   scope), reschedule the fire 30 s later instead of competing for the
   lock. Sprint 16 #38 fix prevents corruption, but waiting in line for
   the lock still serialises the chat queries; deferring the watcher
   fire keeps that queue empty for users.

iCloud + editor + Office sync artefacts are filtered out (lessons-learned #8).

Module-level singletons; lifecycle is owned by `main.py` lifespan via
`start()` / `stop()`.
"""
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.core.config import config as backend_config
from src.services import rag_service
from src.services._paths import DATA_DIR

logger = logging.getLogger("rag_watcher")

# Sprint 18 Fase 4 — these used to be module-level constants. They're now
# read live from `backend_config.rag_watcher_*` via the helpers below so an
# admin tuning change (PATCH /admin/api/v1/rag/tuning) applies on the next
# debouncer tick — no restart needed. Defaults live in `core/config.py`.

def _debounce_seconds() -> float:
    return float(backend_config.rag_watcher_debounce_seconds)

def _max_hold_seconds() -> float:
    return float(backend_config.rag_watcher_max_hold_seconds)

def _lock_busy_replan_seconds() -> float:
    return float(backend_config.rag_watcher_lock_replan_seconds)

# Files we should never reindex on. Lessons-learned #8.
_IGNORE_PATTERNS = re.compile(
    r"""(?xi)
    \.icloud$    | # iCloud placeholder files
    \.DS_Store$  | # macOS Finder metadata
    ^\._         | # macOS extended attributes
    \.tmp$       | # generic tmp
    \.swp$       | # vim swap
    ^~\$           # Office lock files (~$foo.docx)
    """
)


def _is_ignored(path: Path) -> bool:
    return bool(_IGNORE_PATTERNS.search(path.name))


def _scope_for_documents_path(p: Path) -> str | None:
    """Map any path inside `/app/data/` to a scope_key, or None if it's not
    inside a known documents/ folder.

    Recognised shapes:
    - /app/data/documents/...                                     → "global"
    - /app/data/campaigns/{fid}/documents/...                     → "{fid}"
    - /app/data/campaigns/{fid}/companies/{slug}/documents/...    → "{fid}/{slug}"
    """
    try:
        rel = Path(p).resolve().relative_to(DATA_DIR.resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if "documents" not in parts:
        return None
    idx = parts.index("documents")
    prefix = parts[:idx]
    if prefix == ():
        return "global"
    if len(prefix) >= 2 and prefix[0] == "campaigns":
        if len(prefix) == 2:
            return prefix[1]
        if len(prefix) >= 4 and prefix[2] == "companies":
            return f"{prefix[1]}/{prefix[3]}"
    return None


class _ScopeDebouncer:
    """Per-scope timer. Each `schedule(scope_key)` resets the scope's
    `DEBOUNCE_SECONDS` timer; when it expires, `callback(scope_key)` fires.
    Bulk operations on one scope collapse to a single callback as long as
    they pace inside the debounce window.

    Sprint 18 — additionally tracks `_first_event_at[scope]`: the timestamp
    of the first event in the current debounced batch. If the timer would
    keep getting reset past `MAX_DEBOUNCE_HOLD_SECONDS`, it fires anyway,
    so a non-stop upload eventually triggers a reindex.

    Sprint 18 — `_fire` checks the per-scope build lock from `rag_service`
    before invoking the callback. If a build is already running for the
    same scope, the fire reschedules itself instead of queueing behind
    the lock.
    """

    def __init__(self, callback: Callable[[str], Any]) -> None:
        self._callback = callback
        self._timers: dict[str, threading.Timer] = {}
        self._first_event_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def schedule(self, scope_key: str) -> None:
        now = time.monotonic()
        debounce = _debounce_seconds()
        max_hold = _max_hold_seconds()
        with self._lock:
            existing = self._timers.pop(scope_key, None)
            if existing is not None:
                existing.cancel()
            first_seen = self._first_event_at.get(scope_key)
            if first_seen is None:
                self._first_event_at[scope_key] = now
                first_seen = now
            held_for = now - first_seen
            remaining_hold = max_hold - held_for
            # If we've been holding longer than the ceiling, fire ASAP
            # (use a tiny non-zero delay so the timer thread still owns
            # the call rather than blocking the watchdog event thread).
            delay = min(debounce, max(0.1, remaining_hold))
            t = threading.Timer(delay, self._fire, args=(scope_key,))
            t.daemon = True
            self._timers[scope_key] = t
            t.start()

    def _fire(self, scope_key: str) -> None:
        # Check whether the scope's _build_lock is currently held by a
        # running reindex. We use `.acquire(blocking=False)` and release
        # immediately on success so we don't keep the lock — we just need
        # a non-destructive "is it free?" probe. RLock is reentrant; this
        # is safe even if the same thread held it earlier in a different
        # call frame.
        build_locks = getattr(rag_service, "_build_locks", None)
        lock = build_locks.get(scope_key) if build_locks else None
        if lock is not None:
            got = lock.acquire(blocking=False)
            if not got:
                replan_in = _lock_busy_replan_seconds()
                logger.info(
                    f"Debounced reindex deferred for {scope_key}: "
                    f"build lock held; replan in {replan_in}s"
                )
                with self._lock:
                    self._timers.pop(scope_key, None)
                    t = threading.Timer(replan_in, self._fire, args=(scope_key,))
                    t.daemon = True
                    self._timers[scope_key] = t
                    t.start()
                return
            lock.release()

        with self._lock:
            self._timers.pop(scope_key, None)
            self._first_event_at.pop(scope_key, None)
        try:
            result = self._callback(scope_key)
            logger.info(f"Debounced reindex fired for {scope_key}: {result}")
        except Exception as e:
            logger.exception(f"Debounced callback failed for scope {scope_key}: {e}")

    def shutdown(self) -> None:
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
            self._first_event_at.clear()


# Only these event types schedule a reindex. `opened` / `closed_no_write` /
# `closed` are emitted when the indexer reads the file during the rebuild —
# treating them as content changes would create a feedback loop.
_WRITE_EVENTS = {"created", "modified", "deleted", "moved"}


class _Handler(FileSystemEventHandler):
    def __init__(self, debouncer: _ScopeDebouncer) -> None:
        self._d = debouncer

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if event.event_type not in _WRITE_EVENTS:
            return
        # Moves carry both src + dest; both may map to interesting scopes.
        for path_str in (getattr(event, "src_path", None), getattr(event, "dest_path", None)):
            if not path_str:
                continue
            p = Path(path_str)
            if _is_ignored(p):
                continue
            if p.suffix.lower() not in rag_service.ADMIN_ALLOWED_EXTS:
                continue
            scope = _scope_for_documents_path(p)
            if not scope:
                continue
            logger.info(f"Watcher: {event.event_type} {p.name} → scope {scope}")
            self._d.schedule(scope)


# Lifecycle owned by main.py lifespan
_observer: Observer | None = None
_debouncer: _ScopeDebouncer | None = None


def start() -> None:
    global _observer, _debouncer
    if _observer is not None:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _debouncer = _ScopeDebouncer(callback=rag_service.reindex)
    handler = _Handler(_debouncer)
    obs = Observer()
    obs.schedule(handler, str(DATA_DIR), recursive=True)
    obs.daemon = True
    obs.start()
    _observer = obs
    logger.info(f"RAG file watcher started on {DATA_DIR} (debounce {_debounce_seconds()}s)")


def stop() -> None:
    global _observer, _debouncer
    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None
    if _debouncer is not None:
        _debouncer.shutdown()
        _debouncer = None
    logger.info("RAG file watcher stopped")
