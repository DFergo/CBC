"""Per-frontend LLM override.

Per-slot opt-in: each slot (`inference`, `compressor`, `summariser`) can be
overridden independently. Slots set to None inherit the global config.
Compression and routing always inherit from global at the frontend tier —
they're not exposed in the override.

Storage: /app/data/campaigns/{frontend_id}/llm_override.json
Schema:  {"inference": SlotConfig | null, "compressor": SlotConfig | null,
          "summariser": SlotConfig | null}

Sprint 6's llm_provider reads `resolve_llm_config(frontend_id)` which merges
the override on top of the global config per slot.
"""
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.services._paths import atomic_write_json, frontend_dir, read_json
from src.services.llm_config_store import LLMConfig, SlotConfig, load_config as load_global

logger = logging.getLogger("llm_override")


class LLMOverride(BaseModel):
    inference: SlotConfig | None = None
    compressor: SlotConfig | None = None
    summariser: SlotConfig | None = None


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "llm_override.json"


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Old shape was a full LLMConfig (every slot present + compression + routing).
    Translate that to the per-slot override: keep the three slots (treat them
    all as overridden, since the admin had explicitly enabled the override),
    drop compression/routing.
    """
    if "compression" in data or "routing" in data:
        slots = {k: data[k] for k in ("inference", "compressor", "summariser") if k in data}
        return slots
    return data


def load(frontend_id: str) -> LLMOverride:
    """Always returns an LLMOverride. When no file exists, all slots are None
    (i.e. fully inherited)."""
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return LLMOverride()
    try:
        return LLMOverride(**_migrate_legacy(dict(data)))
    except Exception as e:
        logger.warning(f"Invalid llm_override.json for {frontend_id}: {e}; treating as no override")
        return LLMOverride()


def save(frontend_id: str, override: LLMOverride) -> None:
    if all(v is None for v in override.model_dump().values()):
        # Nothing to override — persist as a deletion so disk and intent agree.
        delete(frontend_id)
        return
    atomic_write_json(_path(frontend_id), override.model_dump())
    logger.info(
        f"LLM override saved for frontend {frontend_id}: "
        f"slots overridden={[k for k, v in override.model_dump().items() if v is not None]}"
    )


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"LLM override removed for frontend {frontend_id}")
        return True
    return False


def resolve_llm_config(frontend_id: str | None = None) -> LLMConfig:
    """Effective LLM config for a frontend. Each slot is the override if set,
    otherwise inherited from global. Compression and routing always come from
    global."""
    base = load_global()
    if not frontend_id:
        return base
    override = load(frontend_id)
    return LLMConfig(
        inference=override.inference or base.inference,
        compressor=override.compressor or base.compressor,
        summariser=override.summariser or base.summariser,
        compression=base.compression,
        routing=base.routing,
    )
