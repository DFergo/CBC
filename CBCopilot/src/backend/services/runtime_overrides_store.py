"""Persistent overrides for admin-editable backend_config fields.

Sprint 15 phase 4 fix. Before this, any setting that lived on `backend_config`
and got mutated in-memory (via admin endpoints) was lost on container
restart — the next boot re-read `deployment_backend.json` bundled in the
image and reverted to its defaults. Daniel hit this on the Contextual
Retrieval toggle: enabled it, deployed the image, restart reset it to off.

The pattern for LLMConfig (`llm_config_store`) already solves this for its
slice of config. This module does the same for the RAG-pipeline fields and
any future backend_config setting the admin can change at runtime.

Current fields tracked:
- rag_chunk_size          (int)
- rag_embedding_model     (str)
- rag_contextual_enabled  (bool)

How it plugs in:
1. `main.py` lifespan calls `apply_startup_overrides()` once, right after
   importing the backend_config. That reads the JSON (if present) and
   mutates `backend_config` in place — everything downstream sees the
   persisted values instead of the deployment JSON defaults.
2. Every admin endpoint that flips one of these fields calls
   `save_override(field, value)` right after updating backend_config, so
   the next restart picks it up.

File format is a flat JSON dict. Missing keys are fine — the value from
`deployment_backend.json` / pydantic default stays. Unknown keys are
ignored at apply time (forward-compat).
"""
import logging
from typing import Any

from src.services._paths import RUNTIME_OVERRIDES_FILE, atomic_write_json, read_json

logger = logging.getLogger("runtime_overrides")


# Fields the admin UI is allowed to flip at runtime. Extend this list when
# exposing a new admin-editable backend_config setting.
_TRACKED_FIELDS: tuple[str, ...] = (
    "rag_chunk_size",
    "rag_embedding_model",
    "rag_contextual_enabled",
)


def _load_raw() -> dict[str, Any]:
    data = read_json(RUNTIME_OVERRIDES_FILE, default={}) or {}
    if not isinstance(data, dict):
        logger.warning(f"{RUNTIME_OVERRIDES_FILE} is not a dict; ignoring")
        return {}
    return data


def apply_startup_overrides() -> None:
    """Read the JSON and mutate `backend_config` in place. Call once at
    backend startup, BEFORE any service that reads backend_config gets
    initialised (otherwise the reader latches the deployment JSON default)."""
    from src.core.config import config as backend_config

    raw = _load_raw()
    applied: list[str] = []
    for field, value in raw.items():
        if field not in _TRACKED_FIELDS:
            logger.warning(f"runtime_overrides: unknown field {field!r} — skipped")
            continue
        if not hasattr(backend_config, field):
            logger.warning(f"runtime_overrides: backend_config has no attr {field!r} — skipped")
            continue
        try:
            setattr(backend_config, field, value)
            applied.append(f"{field}={value!r}")
        except Exception as e:
            logger.warning(f"runtime_overrides: could not set {field}={value!r}: {e}")
    if applied:
        logger.info(f"runtime_overrides applied at startup: {', '.join(applied)}")
    else:
        logger.info("runtime_overrides: no persisted overrides found; using deployment JSON defaults")


def save_override(field: str, value: Any) -> None:
    """Persist one field to disk. Idempotent — if the value already matches
    what's on disk, still rewrites (cost is one small atomic JSON write)."""
    if field not in _TRACKED_FIELDS:
        raise ValueError(
            f"{field!r} is not a tracked override field. "
            f"Allowed: {_TRACKED_FIELDS}"
        )
    raw = _load_raw()
    raw[field] = value
    atomic_write_json(RUNTIME_OVERRIDES_FILE, raw)
    logger.info(f"runtime_overrides: persisted {field}={value!r}")


def save_overrides(**fields: Any) -> None:
    """Batch-save several fields at once (one JSON write instead of N).
    Rejects unknown fields."""
    raw = _load_raw()
    changed: list[str] = []
    for field, value in fields.items():
        if field not in _TRACKED_FIELDS:
            raise ValueError(
                f"{field!r} is not a tracked override field. "
                f"Allowed: {_TRACKED_FIELDS}"
            )
        raw[field] = value
        changed.append(f"{field}={value!r}")
    if changed:
        atomic_write_json(RUNTIME_OVERRIDES_FILE, raw)
        logger.info(f"runtime_overrides: persisted {', '.join(changed)}")


def current_overrides() -> dict[str, Any]:
    """Read-only snapshot of what's on disk. Used by the admin UI if we ever
    want to show "overrides currently persisted vs image defaults"."""
    return dict(_load_raw())
