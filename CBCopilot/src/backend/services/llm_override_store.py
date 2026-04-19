"""Per-frontend LLM override (Sprint 4B).

D2=B: override is all-or-nothing at the frontend level. When an override file
exists, that frontend's chat uses this config instead of the global one. When
it doesn't, the frontend inherits the global LLM config.

Storage: /app/data/campaigns/{frontend_id}/llm_override.json
Schema: identical to the global LLMConfig. The admin UI hydrates this from a
snapshot of the current global config the moment the admin enables the
override, then lets them edit it.

Sprint 6's llm_provider reads `resolve_llm_config(frontend_id)` to pick the
effective config for a given session.
"""
import logging
from pathlib import Path

from src.services._paths import atomic_write_json, frontend_dir, read_json
from src.services.llm_config_store import LLMConfig, load_config as load_global

logger = logging.getLogger("llm_override")


def _path(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "llm_override.json"


def load(frontend_id: str) -> LLMConfig | None:
    data = read_json(_path(frontend_id))
    if not isinstance(data, dict):
        return None
    try:
        return LLMConfig(**data)
    except Exception as e:
        logger.warning(f"Invalid llm_override.json for {frontend_id}: {e}")
        return None


def save(frontend_id: str, cfg: LLMConfig) -> None:
    atomic_write_json(_path(frontend_id), cfg.model_dump())
    logger.info(f"LLM override saved for frontend {frontend_id}")


def delete(frontend_id: str) -> bool:
    p = _path(frontend_id)
    if p.exists():
        p.unlink()
        logger.info(f"LLM override removed for frontend {frontend_id}")
        return True
    return False


def resolve_llm_config(frontend_id: str | None = None) -> LLMConfig:
    """Per-frontend override if present, else global."""
    if frontend_id:
        override = load(frontend_id)
        if override is not None:
            return override
    return load_global()
