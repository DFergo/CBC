"""Per-frontend RAG-resolution settings.

Storage: /app/data/campaigns/{frontend_id}/rag_settings.json. Backend-only —
the sidecar doesn't need to know; only the resolver consults this when
deciding whether to include the global RAG in a frontend's effective stack.

Fields:
    combine_global_rag — when True (default), companies in this frontend can
                         pull in the global RAG depending on their own
                         `combine_global_rag` setting. When False, the global
                         RAG is excluded for every chat session this frontend
                         serves, regardless of company settings.
"""
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.services._paths import atomic_write_json, frontend_dir, read_json

logger = logging.getLogger("rag_settings")


class RAGSettings(BaseModel):
    combine_global_rag: bool = True


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Translate the old `global_rag_mode: 'combine'|'ignore'` shape."""
    if "global_rag_mode" in data and "combine_global_rag" not in data:
        data["combine_global_rag"] = data["global_rag_mode"] == "combine"
    data.pop("global_rag_mode", None)
    return data


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "rag_settings.json"


def load(frontend_id: str) -> RAGSettings:
    """Always returns a value — defaults when no file exists."""
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return RAGSettings()
    try:
        return RAGSettings(**_migrate_legacy(dict(data)))
    except Exception as e:
        logger.warning(f"Invalid rag_settings.json for {frontend_id}: {e}; using defaults")
        return RAGSettings()


def save(frontend_id: str, settings: RAGSettings) -> None:
    atomic_write_json(_path(frontend_id), settings.model_dump())
    logger.info(f"RAG settings saved for frontend {frontend_id}: {settings.model_dump()}")


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"RAG settings reset to defaults for frontend {frontend_id}")
        return True
    return False
