"""Connection registry — reusable named LLM provider connections.

Adapted from HRDDHelper/src/backend/services/connection_registry.py. CBC keeps
its own type vocabulary (lm_studio / ollama / api) instead of HRDDHelper's
(openai / anthropic / ollama) so the migration from the old inline-provider
SlotConfig shape is a straight field move, not a semantic remap.

A connection record:
    {id, type: "lm_studio"|"ollama"|"api", api_flavor: "anthropic"|"openai"|
     "openai_compatible"|None, endpoint, api_endpoint, api_key, api_key_env,
     model_ids[] (allowlist), enable}

Persisted at DATA_DIR/connections.json. Atomic writes via the shared
_paths helpers. On first load the registry seeds itself with a lm_studio and
an ollama default connection so a fresh install keeps today's wiring.
"""
import logging
from typing import Any, Literal

from src.core.config import config as backend_config
from src.services._paths import CONNECTIONS_FILE, atomic_write_json, read_json

logger = logging.getLogger("connection_registry")

ConnectionType = Literal["lm_studio", "ollama", "api"]
VALID_TYPES = {"lm_studio", "ollama", "api"}


def _seed_connections() -> list[dict[str, Any]]:
    return [
        {
            "id": "lm_studio-default",
            "type": "lm_studio",
            "api_flavor": None,
            "endpoint": backend_config.lm_studio_endpoint,
            "api_endpoint": None,
            "api_key": None,
            "api_key_env": None,
            "model_ids": [],
            "enable": True,
        },
        {
            "id": "ollama-default",
            "type": "ollama",
            "api_flavor": None,
            "endpoint": backend_config.ollama_endpoint,
            "api_endpoint": None,
            "api_key": None,
            "api_key_env": None,
            "model_ids": [],
            "enable": True,
        },
    ]


class ConnectionRegistry:
    """Persistent registry of provider connections. Atomic JSON writes."""

    def __init__(self):
        self._connections: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        data = read_json(CONNECTIONS_FILE)
        if isinstance(data, dict) and isinstance(data.get("connections"), list):
            self._connections = data["connections"]
            logger.info(f"Loaded {len(self._connections)} connections")
            return
        self._connections = _seed_connections()
        self._save()
        logger.info(f"Seeded {len(self._connections)} default connections")

    def _save(self):
        atomic_write_json(CONNECTIONS_FILE, {"connections": self._connections})

    # --- Queries ---

    def all(self) -> list[dict[str, Any]]:
        return list(self._connections)

    def enabled(self) -> list[dict[str, Any]]:
        return [c for c in self._connections if c.get("enable", True)]

    def get(self, connection_id: str) -> dict[str, Any] | None:
        for c in self._connections:
            if c["id"] == connection_id:
                return c
        return None

    # --- Mutations ---

    def add(self, conn: dict[str, Any]) -> dict[str, Any]:
        record = self._normalise(conn)
        if self.get(record["id"]):
            raise ValueError(f"Connection id already exists: {record['id']}")
        self._connections.append(record)
        self._save()
        logger.info(f"Added connection {record['id']} ({record['type']})")
        return record

    def update(self, connection_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self.get(connection_id)
        if not existing:
            raise ValueError(f"Connection not found: {connection_id}")
        for key in (
            "type", "api_flavor", "endpoint", "api_endpoint",
            "api_key", "api_key_env", "model_ids", "enable",
        ):
            if key in patch:
                existing[key] = patch[key]
        if existing["type"] not in VALID_TYPES:
            raise ValueError(f"Invalid connection type: {existing['type']}")
        self._save()
        logger.info(f"Updated connection {connection_id}")
        return existing

    def delete(self, connection_id: str):
        before = len(self._connections)
        self._connections = [c for c in self._connections if c["id"] != connection_id]
        if len(self._connections) != before:
            self._save()
            logger.info(f"Deleted connection {connection_id}")

    def add_or_reuse(self, conn: dict[str, Any]) -> str:
        """Migration helper: return the id of an existing connection matching
        (type, endpoint/api_endpoint, api_flavor, api_key_env, api_key), or
        create a new one. Lets several legacy slots pointing at the same
        provider collapse into a single connection.
        """
        candidate = self._normalise({**conn, "id": conn.get("id") or "migrated"})
        for existing in self._connections:
            if (
                existing["type"] == candidate["type"]
                and existing.get("endpoint") == candidate.get("endpoint")
                and existing.get("api_endpoint") == candidate.get("api_endpoint")
                and existing.get("api_flavor") == candidate.get("api_flavor")
                and existing.get("api_key_env") == candidate.get("api_key_env")
                and existing.get("api_key") == candidate.get("api_key")
            ):
                return existing["id"]
        # Ensure a unique id.
        base_id = candidate["id"]
        unique_id = base_id
        n = 2
        while self.get(unique_id):
            unique_id = f"{base_id}-{n}"
            n += 1
        candidate["id"] = unique_id
        self._connections.append(candidate)
        self._save()
        logger.info(f"Migrated legacy slot provider into connection {unique_id}")
        return unique_id

    def _normalise(self, conn: dict[str, Any]) -> dict[str, Any]:
        conn_type = conn.get("type")
        if conn_type not in VALID_TYPES:
            raise ValueError(f"Invalid connection type: {conn_type}")
        conn_id = (conn.get("id") or "").strip()
        if not conn_id:
            raise ValueError("Connection id is required")
        return {
            "id": conn_id,
            "type": conn_type,
            "api_flavor": conn.get("api_flavor"),
            "endpoint": conn.get("endpoint"),
            "api_endpoint": conn.get("api_endpoint"),
            "api_key": conn.get("api_key"),
            "api_key_env": conn.get("api_key_env"),
            "model_ids": conn.get("model_ids") or [],
            "enable": conn.get("enable", True),
        }


# Singleton
connections = ConnectionRegistry()
