"""Global branding defaults (SPEC §5.1 Tab 1 "Branding defaults").

The admin edits these from the General tab. They're the fallback for any
frontend that does NOT have a per-frontend branding override in
`/app/data/campaigns/{fid}/branding.json`.

Resolution order (applied by `resolvers.resolve_branding(fid)`):
1. Per-frontend override exists → use it
2. Else global defaults exist → use them
3. Else → None (sidecar falls back to its deployment_frontend.json baseline)
"""
import logging

from src.services._paths import DATA_DIR, atomic_write_json, read_json
from src.services.branding_store import Branding

logger = logging.getLogger("branding_defaults")

DEFAULTS_FILE = DATA_DIR / "branding_defaults.json"


def load() -> Branding | None:
    data = read_json(DEFAULTS_FILE)
    if not isinstance(data, dict):
        return None
    try:
        return Branding(**data)
    except Exception as e:
        logger.warning(f"Invalid branding_defaults.json: {e}")
        return None


def save(branding: Branding) -> None:
    atomic_write_json(DEFAULTS_FILE, branding.model_dump())
    logger.info("Global branding defaults saved")


def delete() -> bool:
    if DEFAULTS_FILE.exists():
        DEFAULTS_FILE.unlink()
        logger.info("Global branding defaults removed")
        return True
    return False
