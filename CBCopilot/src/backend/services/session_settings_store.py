"""Per-frontend session settings + feature toggles.

Storage: /app/data/campaigns/{frontend_id}/session_settings.json. Concrete
per-field values — no `inherit` semantics. When the file is absent the
defaults below apply (matching what `deployment_frontend.json` ships with).
RAG-related settings live in `rag_settings_store.py`, not here.

Fields covered:
    auth_required          — enable email-code auth flow on this frontend
    session_resume_hours   — how long a session token stays recoverable after
                             it's created (user can come back with the token
                             and pick up the conversation within this window)
    auto_close_hours       — idle hours before the session is marked complete
                             and the user-summary prompt is triggered
    auto_destroy_hours     — privacy wipe — delete conversation + uploads N
                             hours after the session closes (0 = keep forever)
    disclaimer_enabled     — show or skip the Disclaimer page
    instructions_enabled   — show or skip the Instructions page
    compare_all_enabled    — show or hide the "Compare All" button on
                             CompanySelectPage
    cba_sidepanel_enabled  — show a side panel in ChatShell listing the CBA
                             documents that contributed to each response,
                             with download links
    cba_citations_enabled  — separate toggle (only meaningful when
                             cba_sidepanel_enabled is true): ask the LLM to
                             cite exact page / article numbers inline as
                             `[filename, p. N]` / `[filename, Art. N]`
                             brackets. The chat UI renders those as
                             clickable pills that highlight the matching
                             document in the sidepanel. Defaults off —
                             the LLM occasionally gets citation format
                             wrong, so the admin opts in when they want it.

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
    auth_required: bool = True
    session_resume_hours: int = 48
    auto_close_hours: int = 72
    auto_destroy_hours: int = 0
    disclaimer_enabled: bool = True
    instructions_enabled: bool = True
    compare_all_enabled: bool = True
    cba_sidepanel_enabled: bool = True
    cba_citations_enabled: bool = False


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "session_settings.json"


def load(frontend_id: str) -> SessionSettings | None:
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return None
    # Drop legacy/unknown keys (e.g. `rag_standalone` from before it moved to
    # rag_settings) and replace `null` with the field's default. Old per-tier
    # configs used None to mean "inherit" — under the new model concrete values
    # always win, so Nones get coerced to defaults rather than failing validation.
    cleaned = {k: v for k, v in data.items() if k in SessionSettings.model_fields and v is not None}
    try:
        return SessionSettings(**cleaned)
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

    Empty dict = no override (sidecar uses its baseline). Otherwise we push
    every field as a concrete value — the sidecar layers them on top of the
    deployment_frontend.json baseline.
    """
    if settings is None:
        return {}
    return settings.model_dump()
