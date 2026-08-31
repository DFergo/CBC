"""Per-frontend organizations override (SPEC §2.4 orgs_mode).

Storage: /app/data/campaigns/{frontend_id}/orgs_override.json
Schema: {mode: "inherit" | "own" | "combine", organizations: list[dict]}
- inherit: use the global organizations list (no per-frontend data read)
- own: use the per-frontend list only (global ignored)
- combine: per-frontend + global merged, per-frontend wins on name collision
"""
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.services._paths import atomic_write_json, frontend_dir, read_json
from src.services.knowledge_store import Organization

logger = logging.getLogger("orgs_override")

Mode = Literal["inherit", "own", "combine"]


class OrgsOverride(BaseModel):
    mode: Mode = "inherit"
    organizations: list[dict[str, Any]] = Field(default_factory=list)


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "orgs_override.json"


def load(frontend_id: str) -> OrgsOverride | None:
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return None
    try:
        # Validate each org loosely (we store as dicts but filter bad rows)
        orgs = []
        for raw in data.get("organizations", []) or []:
            try:
                Organization(**raw)
                orgs.append(raw)
            except Exception as e:
                logger.warning(f"Dropping malformed org entry in {frontend_id}: {e}")
        return OrgsOverride(mode=data.get("mode", "inherit"), organizations=orgs)
    except Exception as e:
        logger.warning(f"Invalid orgs_override.json for {frontend_id}: {e}")
        return None


def save(frontend_id: str, override: OrgsOverride) -> None:
    atomic_write_json(_path(frontend_id), override.model_dump())
    logger.info(f"Orgs override saved for {frontend_id}: mode={override.mode}, {len(override.organizations)} entries")


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"Orgs override removed for {frontend_id}")
        return True
    return False
