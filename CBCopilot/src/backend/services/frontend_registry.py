"""Persistent registry of registered frontends.

Adapted from HRDDHelper/src/backend/services/frontend_registry.py. Unlike HRDD,
CBC frontends have a stable `frontend_id` in their deployment_frontend.json
(e.g. "packaging-eu"). That's the natural key — same ID keys the
/app/data/campaigns/{frontend_id}/ folder for all per-frontend config
(companies, prompts, RAG, branding, session settings). No random hex ID.

Admin registers each frontend manually with:
  - frontend_id (stable, e.g. "packaging-eu")
  - url (where the sidecar lives, e.g. "http://packaging-eu.internal")
  - name (human label, optional)

Registry tracks runtime status (online/offline/unknown) from the polling loop.

Storage: /app/data/frontends.json (atomic writes).
"""
import logging
from datetime import datetime, timezone
from typing import Any

from src.services._paths import DATA_DIR, atomic_write_json, read_json

logger = logging.getLogger("frontend_registry")

REGISTRY_FILE = DATA_DIR / "frontends.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def register(self, frontend_id: str, url: str, name: str = "") -> dict[str, Any]:
        """Register or update a frontend by its stable frontend_id."""
        url = url.rstrip("/")
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
