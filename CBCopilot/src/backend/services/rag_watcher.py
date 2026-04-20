"""watchdog-based RAG file watcher.

Watches `/app/data/` recursively. When a file is added, modified, or deleted
under any `documents/` folder we know about, the affected scope is debounced
for 5 seconds and then `rag_service.reindex(scope_key)` fires.

Per-scope debouncing means bulk-copying 50 PDFs into a single company
triggers ONE rebuild for that company; unrelated scopes are not affected.

iCloud + editor + Office sync artefacts are filtered out (lessons-learned #8).

Module-level singletons; lifecycle is owned by `main.py` lifespan via
`start()` / `stop()`.
"""
import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.services import rag_service
from src.services._paths import DATA_DIR

logger = logging.getLogger("rag_watcher")

DEBOUNCE_SECONDS = 5.0

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
    """Per-scope timer. Each `schedule(scope_key)` resets the scope's 5 s
    timer. When it expires, `callback(scope_key)` fires. Bulk operations on
    one scope collapse to a single callback.
    """

    def __init__(self, callback: Callable[[str], Any]) -> None:
        self._callback = callback
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(self, scope_key: str) -> None:
        with self._lock:
            existing = self._timers.pop(scope_key, None)
            if existing is not None:
                existing.cancel()
            t = threading.Timer(DEBOUNCE_SECONDS, self._fire, args=(scope_key,))
            t.daemon = True
            self._timers[scope_key] = t
            t.start()

    def _fire(self, scope_key: str) -> None:
        with self._lock:
            self._timers.pop(scope_key, None)
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
    logger.info(f"RAG file watcher started on {DATA_DIR} (debounce {DEBOUNCE_SECONDS}s)")


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
