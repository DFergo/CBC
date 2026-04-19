"""Per-frontend branding override (SPEC §2.4 / §6.2).

Storage: /app/data/campaigns/{frontend_id}/branding.json. When absent, the
frontend's `deployment_frontend.json` baseline is used (read by the sidecar
at boot). Admin saves override → backend pushes it to the sidecar via
POST /internal/branding (sidecar caches + surfaces in /internal/config).
"""
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.services._paths import atomic_write_json, frontend_dir, read_json

logger = logging.getLogger("branding_store")


class Branding(BaseModel):
    app_title: str = ""
    org_name: str = ""  # shown in the top-right of the header + footer (e.g. "UNI Global Union")
    logo_url: str = ""
    primary_color: str = ""
    secondary_color: str = ""
    # Free-text overrides that replace the i18n disclaimer/instructions for this
    # tier. Empty string = no override at this tier (sidecar merges across tiers).
    disclaimer_text: str = ""
    instructions_text: str = ""


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "branding.json"


def load(frontend_id: str) -> Branding | None:
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return None
    try:
        return Branding(**data)
    except Exception as e:
        logger.warning(f"Invalid branding.json for {frontend_id}: {e}")
        return None


def save(frontend_id: str, branding: Branding) -> None:
    atomic_write_json(_path(frontend_id), branding.model_dump())
    logger.info(f"Branding saved for frontend {frontend_id}")


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"Branding override removed for frontend {frontend_id}")
        return True
    return False


def to_push_payload(branding: Branding | None) -> dict[str, Any]:
    """Build the body sent to the sidecar's POST /internal/branding.

    `custom=False` tells the sidecar to clear its cache and fall back to
    `deployment_frontend.json` baseline (HRDD pattern). `custom=True` carries
    the full override.
    """
    if branding is None:
        return {"custom": False}
    return {"custom": True, **branding.model_dump()}
