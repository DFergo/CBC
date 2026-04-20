"""Admin: frontend registry CRUD + per-frontend branding + session settings.

Primary key is `frontend_id` — the stable string the frontend uses in its own
`deployment_frontend.json` (e.g. "packaging-eu"). Same ID keys
/app/data/campaigns/{frontend_id}/ where all per-frontend config lives.

Per-frontend config changes are pushed to the sidecar on save so they take
effect immediately (HRDD push pattern, not polling).
"""
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.api.v1.admin.branding import TranslationBundle
from src.services import (
    branding_store,
    llm_override_store,
    orgs_override_store,
    rag_settings_store,
    resolvers,
    session_settings_store,
)
from src.services.branding_store import Branding
from src.services.frontend_registry import registry
from src.services.llm_override_store import LLMOverride
from src.services.orgs_override_store import OrgsOverride
from src.services.rag_settings_store import RAGSettings
from src.services.session_settings_store import SessionSettings

logger = logging.getLogger("admin.frontends")

router = APIRouter(prefix="/admin/api/v1/frontends", tags=["admin-frontends"])

PUSH_TIMEOUT = 5.0


async def _push(frontend_id: str, path: str, body: dict[str, Any]) -> None:
    """POST to the sidecar. Logs on failure — admin save shouldn't fail just
    because the sidecar is momentarily offline (it'll pick up the override
    from disk on its next boot or periodic refresh).
    """
    fe = registry.get(frontend_id)
    if not fe:
        return
    url = f"{fe['url'].rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PUSH_TIMEOUT) as client:
            r = await client.post(url, json=body)
            if r.status_code // 100 != 2:
                logger.warning(f"Push {path} → {url} returned HTTP {r.status_code}: {r.text[:200]}")
            else:
                logger.info(f"Pushed {path} → {frontend_id} OK")
    except httpx.HTTPError as e:
        logger.warning(f"Push {path} → {url} failed: {e}")


def _serialise(fe: dict[str, Any]) -> dict[str, Any]:
    return {
        "frontend_id": fe["frontend_id"],
        "url": fe["url"],
        "name": fe["name"],
        "enabled": fe.get("enabled", True),
        "status": fe.get("status", "unknown"),
        "last_seen": fe.get("last_seen"),
        "created_at": fe.get("created_at"),
        "metadata": fe.get("metadata", {}),
    }


# --- Registry CRUD ---

class RegisterRequest(BaseModel):
    url: str
    name: str


class UpdateRequest(BaseModel):
    url: str | None = None
    name: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


@router.get("")
async def list_frontends(_admin: dict = Depends(require_admin)):
    return {"frontends": [_serialise(f) for f in registry.list_all()]}


@router.post("", status_code=201)
async def register_frontend(req: RegisterRequest, _admin: dict = Depends(require_admin)):
    if not req.url.strip():
        raise HTTPException(400, "url is required")
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    fe = registry.register(url=req.url.strip(), name=req.name.strip())
    return {"frontend": _serialise(fe)}


@router.get("/{frontend_id}")
async def get_frontend(frontend_id: str, _admin: dict = Depends(require_admin)):
    fe = registry.get(frontend_id)
    if not fe:
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")
    return {"frontend": _serialise(fe)}


@router.patch("/{frontend_id}")
async def update_frontend(frontend_id: str, req: UpdateRequest, _admin: dict = Depends(require_admin)):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = registry.update(frontend_id, **patch)
    if not updated:
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")
    return {"frontend": _serialise(updated)}


@router.delete("/{frontend_id}")
async def delete_frontend(frontend_id: str, _admin: dict = Depends(require_admin)):
    if not registry.remove(frontend_id):
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")
    return {"status": "deleted", "frontend_id": frontend_id}


# --- Per-frontend branding ---

def _require_registered(frontend_id: str) -> None:
    if not registry.get(frontend_id):
        raise HTTPException(404, f"Frontend {frontend_id!r} not registered. Register it first on the Frontends tab.")


@router.get("/{frontend_id}/branding")
async def get_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    b = branding_store.load(frontend_id)
    return {"frontend_id": frontend_id, "branding": b.model_dump() if b else None}


@router.put("/{frontend_id}/branding")
async def put_branding(frontend_id: str, branding: Branding, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    branding_store.save(frontend_id, branding)
    # Push resolved (override wins here → sends override). Uses the resolver so the
    # logic stays in one place.
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": branding.model_dump()}


@router.delete("/{frontend_id}/branding")
async def delete_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = branding_store.delete(frontend_id)
    # After deleting the override, resolver returns either global defaults (if set)
    # or {custom: False} (sidecar falls back to its deployment_frontend.json baseline).
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend translation bundle (download / upload) ---

@router.get("/{frontend_id}/branding/translations")
async def get_branding_translations(frontend_id: str, _admin: dict = Depends(require_admin)):
    """Export this frontend's translation bundle as JSON.

    404 if no per-frontend override exists — can't export what isn't there.
    """
    _require_registered(frontend_id)
    b = branding_store.load(frontend_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No per-frontend branding override to export")
    return TranslationBundle.from_branding(b).model_dump()


@router.put("/{frontend_id}/branding/translations")
async def put_branding_translations(frontend_id: str, bundle: TranslationBundle, _admin: dict = Depends(require_admin)):
    """Import a translation bundle into this frontend's override.

    Overwrites source text + translations; preserves non-text fields (logo,
    colors, app_title, org_name). Creates an override record if none exists.
    """
    _require_registered(frontend_id)
    current = branding_store.load(frontend_id) or Branding()
    updated = bundle.apply_to(current)
    branding_store.save(frontend_id, updated)
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": updated.model_dump()}


@router.post("/{frontend_id}/branding/auto-translate")
async def auto_translate_frontend_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    """Fill missing language keys in this frontend's branding override using the summariser LLM.

    Uses the frontend's own LLM override if one is set (via resolve_llm_config),
    falling back to the global LLM config otherwise. Existing non-empty
    translations are preserved.
    """
    from src.services.branding_translator import auto_translate_branding
    _require_registered(frontend_id)
    current = branding_store.load(frontend_id)
    if current is None:
        raise HTTPException(status_code=404, detail="No per-frontend branding override to translate")
    if not (current.disclaimer_text.strip() or current.instructions_text.strip()):
        raise HTTPException(status_code=400, detail="No source text in disclaimer_text or instructions_text")
    updated, stats = await auto_translate_branding(current, frontend_id=frontend_id, overwrite=False)
    branding_store.save(frontend_id, updated)
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": updated.model_dump(), "stats": stats}


# --- Per-frontend session settings ---

@router.get("/{frontend_id}/session-settings")
async def get_session_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    s = session_settings_store.load(frontend_id)
    return {"frontend_id": frontend_id, "settings": s.model_dump() if s else None}


@router.put("/{frontend_id}/session-settings")
async def put_session_settings(frontend_id: str, settings: SessionSettings, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    session_settings_store.save(frontend_id, settings)
    await _push(frontend_id, "/internal/session-settings", session_settings_store.to_push_payload(settings))
    return {"frontend_id": frontend_id, "settings": settings.model_dump()}


@router.delete("/{frontend_id}/session-settings")
async def delete_session_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = session_settings_store.delete(frontend_id)
    await _push(frontend_id, "/internal/session-settings", session_settings_store.to_push_payload(None))
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend RAG settings ---

@router.get("/{frontend_id}/rag-settings")
async def get_rag_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    s = rag_settings_store.load(frontend_id)
    return {"frontend_id": frontend_id, "settings": s.model_dump()}


@router.put("/{frontend_id}/rag-settings")
async def put_rag_settings(frontend_id: str, settings: RAGSettings, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    rag_settings_store.save(frontend_id, settings)
    return {"frontend_id": frontend_id, "settings": settings.model_dump()}


@router.delete("/{frontend_id}/rag-settings")
async def delete_rag_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = rag_settings_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed, "settings": rag_settings_store.load(frontend_id).model_dump()}


# --- Per-frontend organizations override ---

@router.get("/{frontend_id}/orgs")
async def get_orgs_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    o = orgs_override_store.load(frontend_id)
    return {"frontend_id": frontend_id, "override": o.model_dump() if o else None}


@router.put("/{frontend_id}/orgs")
async def put_orgs_override(
    frontend_id: str,
    override: OrgsOverride,
    _admin: dict = Depends(require_admin),
):
    _require_registered(frontend_id)
    orgs_override_store.save(frontend_id, override)
    return {"frontend_id": frontend_id, "override": override.model_dump()}


@router.delete("/{frontend_id}/orgs")
async def delete_orgs_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = orgs_override_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend LLM override (per-slot opt-in) ---

@router.get("/{frontend_id}/llm")
async def get_llm_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    override = llm_override_store.load(frontend_id)
    return {"frontend_id": frontend_id, "override": override.model_dump()}


@router.put("/{frontend_id}/llm")
async def put_llm_override(
    frontend_id: str,
    cfg: LLMOverride,
    _admin: dict = Depends(require_admin),
):
    _require_registered(frontend_id)
    llm_override_store.save(frontend_id, cfg)
    return {"frontend_id": frontend_id, "override": cfg.model_dump()}


@router.delete("/{frontend_id}/llm")
async def delete_llm_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = llm_override_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed}
