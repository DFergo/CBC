"""Per-frontend session settings + feature toggles override (SPEC §6.2).

Storage: /app/data/campaigns/{frontend_id}/session_settings.json. Any field set
to None means "inherit from deployment_frontend.json". Non-None fields override.

Fields covered:
    auth_required          — enable email-code auth flow on this frontend
    session_resume_hours   — how long a session token stays recoverable
    auto_close_hours       — idle before session is marked complete
    auto_destroy_hours     — privacy wipe (0 = never, >0 = delete after N hours)
    disclaimer_enabled     — show or skip the Disclaimer page
    instructions_enabled   — show or skip the Instructions page
    compare_all_enabled    — show or hide the "Compare All" button on CompanySelectPage
    rag_standalone         — if true, global RAG docs are EXCLUDED from this
                             frontend's resolution even when a company is set
                             to inherit_all. Default false = frontend supplements
                             global. Backend-only (NOT pushed to sidecar — the
                             sidecar doesn't need to know; resolver uses it).

Admin saves override → backend pushes to sidecar via POST /internal/session-settings
(sidecar caches + merges into /internal/config).
"""
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.services._paths import atomic_write_json, frontend_dir, read_json

logger = logging.getLogger("session_settings")


class SessionSettings(BaseModel):
    auth_required: bool | None = None
    session_resume_hours: int | None = None
    auto_close_hours: int | None = None
    auto_destroy_hours: int | None = None
    disclaimer_enabled: bool | None = None
    instructions_enabled: bool | None = None
    compare_all_enabled: bool | None = None
    rag_standalone: bool | None = None


# Fields that are backend-only (resolver reads them; sidecar doesn't need to know).
_BACKEND_ONLY_FIELDS = {"rag_standalone"}


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "session_settings.json"


def load(frontend_id: str) -> SessionSettings | None:
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return None
    try:
        return SessionSettings(**data)
    except Exception as e:
        logger.warning(f"Invalid session_settings.json for {frontend_id}: {e}")
        return None


def save(frontend_id: str, settings: SessionSettings) -> None:
    atomic_write_json(_path(frontend_id), settings.model_dump())
    logger.info(f"Session settings saved for frontend {frontend_id}")


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"Session settings override removed for frontend {frontend_id}")
        return True
    return False


def to_push_payload(settings: SessionSettings | None) -> dict[str, Any]:
    """Body sent to the sidecar's POST /internal/session-settings.

    Empty dict = clear cache (fall back to deployment_frontend.json). Otherwise,
    only non-None fields are sent, AND backend-only fields (e.g. rag_standalone,
    which affects resolver behaviour but is invisible to the sidecar) are stripped.
    """
    if settings is None:
        return {}
    return {
        k: v for k, v in settings.model_dump().items()
        if v is not None and k not in _BACKEND_ONLY_FIELDS
    }
