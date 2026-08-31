"""Persistent registry of registered frontends.

Adapted from HRDDHelper/src/backend/services/frontend_registry.py.

Admin registers each frontend with just `url` + `name`. The backend
auto-generates the internal `frontend_id` (slug from name, with a numeric
suffix if it collides with an existing one). That ID is the key for the
config tree under /app/data/campaigns/{frontend_id}/ — admins never see it
in normal operation; the UI shows the human-readable name.

Frontend containers themselves are anonymous: they don't need to know their
backend-side ID. The backend already knows which frontend it's talking to
because it's polling its registered URL.

Registry tracks runtime status (online/offline/unknown) from the polling loop.

Storage: /app/data/frontends.json (atomic writes).
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.services._paths import DATA_DIR, atomic_write_json, read_json

logger = logging.getLogger("frontend_registry")

REGISTRY_FILE = DATA_DIR / "frontends.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    """Lowercase, hyphen-separated, alphanumeric-only. Used to derive
    frontend_id from a display name. Falls back to 'frontend' if the result
    would be empty.
    """
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "frontend"


class FrontendRegistry:
    def __init__(self) -> None:
        self._frontends: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        data = read_json(REGISTRY_FILE, default={})
        if isinstance(data, dict):
            self._frontends = data
            logger.info(f"Loaded {len(self._frontends)} frontends from registry")
        else:
            self._frontends = {}

    def _save(self) -> None:
        atomic_write_json(REGISTRY_FILE, self._frontends)

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._frontends.values())

    def list_enabled(self) -> list[dict[str, Any]]:
        return [f for f in self._frontends.values() if f.get("enabled", True)]

    def get(self, frontend_id: str) -> dict[str, Any] | None:
        return self._frontends.get(frontend_id)

    def _next_unique_id(self, base: str) -> str:
        """Return `base`, or `base-2`, `base-3`, … until we find an unused one."""
        if base not in self._frontends:
            return base
        n = 2
        while f"{base}-{n}" in self._frontends:
            n += 1
        return f"{base}-{n}"

    def register(self, url: str, name: str, frontend_id: str | None = None) -> dict[str, Any]:
        """Register a new frontend. Auto-generates `frontend_id` from `name`
        with a numeric suffix on collision (admins don't pick the ID).

        If `frontend_id` is explicitly provided (e.g. internal callers
        restoring state), it's used as-is and updates any existing entry.
        """
        url = url.rstrip("/")
        if frontend_id is None:
            frontend_id = self._next_unique_id(_slugify(name))

        entry: dict[str, Any] = self._frontends.get(frontend_id, {})
        entry.update({
            "id": frontend_id,
            "frontend_id": frontend_id,
            "url": url,
            "name": name or entry.get("name") or frontend_id,
            "enabled": entry.get("enabled", True),
            "status": entry.get("status", "unknown"),
            "last_seen": entry.get("last_seen"),
            "created_at": entry.get("created_at") or _now(),
            "metadata": entry.get("metadata", {}),
        })
        self._frontends[frontend_id] = entry
        self._save()
        logger.info(f"Registered frontend {frontend_id}: {url} (name={entry['name']})")
        return entry

    def update(self, frontend_id: str, **patch: Any) -> dict[str, Any] | None:
        if frontend_id not in self._frontends:
            return None
        ALLOWED = {"url", "name", "enabled", "metadata"}
        for key, val in patch.items():
            if key in ALLOWED and val is not None:
                if key == "url":
                    val = val.rstrip("/")
                self._frontends[frontend_id][key] = val
        self._save()
        return self._frontends[frontend_id]

    def remove(self, frontend_id: str) -> bool:
        if frontend_id in self._frontends:
            del self._frontends[frontend_id]
            self._save()
            logger.info(f"Removed frontend {frontend_id}")
            return True
        return False

    def set_status(self, frontend_id: str, status: str) -> None:
        """Runtime status update. Does NOT persist — noise would thrash disk."""
        if frontend_id not in self._frontends:
            return
        self._frontends[frontend_id]["status"] = status
        if status == "online":
            self._frontends[frontend_id]["last_seen"] = _now()


registry = FrontendRegistry()
