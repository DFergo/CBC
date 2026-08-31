"""Admin global branding defaults (SPEC §5.1 Tab 1).

Editing global defaults triggers a fan-out push to every registered frontend
that does NOT have its own per-frontend branding override — so the change
takes effect immediately across all default-branding deployments. Frontends
with their own override are untouched (their override still wins).
"""
import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.v1.admin.auth import require_admin
from src.services import branding_defaults_store, branding_store, resolvers
from src.services.branding_store import Branding
from src.services.branding_translator import auto_translate_branding
from src.services.frontend_registry import registry

logger = logging.getLogger("admin.branding")

router = APIRouter(prefix="/admin/api/v1/branding", tags=["admin-branding"])

PUSH_TIMEOUT = 5.0


class TranslationBundle(BaseModel):
    """Portable JSON representation of the translatable-text block.

    Admin downloads this, edits it in a text editor (or pastes it to a translator),
    and uploads it back. `source_language` is the language the admin wrote the
    `disclaimer_text` / `instructions_text` source strings in.
    """
    source_language: str = "en"
    disclaimer_text: str = ""
    instructions_text: str = ""
    disclaimer_text_translations: dict[str, str] = Field(default_factory=dict)
    instructions_text_translations: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_branding(cls, b: Branding) -> "TranslationBundle":
        return cls(
            source_language=b.source_language or "en",
            disclaimer_text=b.disclaimer_text,
            instructions_text=b.instructions_text,
            disclaimer_text_translations=dict(b.disclaimer_text_translations),
            instructions_text_translations=dict(b.instructions_text_translations),
        )

    def apply_to(self, b: Branding) -> Branding:
        """Return a new Branding with translations/source overwritten from this bundle."""
        data = b.model_dump()
        data.update({
            "source_language": self.source_language or "en",
            "disclaimer_text": self.disclaimer_text,
            "instructions_text": self.instructions_text,
            "disclaimer_text_translations": dict(self.disclaimer_text_translations),
            "instructions_text_translations": dict(self.instructions_text_translations),
        })
        return Branding(**data)


async def _push_to_frontend(frontend_id: str, body: dict[str, Any]) -> None:
    fe = registry.get(frontend_id)
    if not fe:
        return
    url = f"{fe['url'].rstrip('/')}/internal/branding"
    try:
        async with httpx.AsyncClient(timeout=PUSH_TIMEOUT) as client:
            r = await client.post(url, json=body)
            if r.status_code // 100 != 2:
                logger.warning(f"Push branding → {url}: HTTP {r.status_code}")
    except httpx.HTTPError as e:
        logger.warning(f"Push branding → {url}: {e}")


async def _fanout_to_defaults_users() -> int:
    """Push effective branding to every registered frontend WITHOUT a per-frontend
    override. Frontends with their own override are untouched.
    """
    count = 0
    for fe in registry.list_enabled():
        fid = fe["frontend_id"]
        if branding_store.load(fid) is not None:
            continue  # has its own override — skip
        payload = resolvers.branding_push_payload(fid)
        await _push_to_frontend(fid, payload)
        count += 1
    return count


@router.get("/defaults")
async def get_defaults(_admin: dict = Depends(require_admin)):
    d = branding_defaults_store.load()
    return {"defaults": d.model_dump() if d else None}


@router.put("/defaults")
async def put_defaults(branding: Branding, _admin: dict = Depends(require_admin)):
    branding_defaults_store.save(branding)
    pushed = await _fanout_to_defaults_users()
    return {"defaults": branding.model_dump(), "pushed_to_frontends": pushed}


@router.delete("/defaults")
async def delete_defaults(_admin: dict = Depends(require_admin)):
    removed = branding_defaults_store.delete()
    pushed = await _fanout_to_defaults_users()
    return {"removed": removed, "pushed_to_frontends": pushed}


# --- Global translation bundle (download / upload) ---

@router.get("/defaults/translations")
async def get_defaults_translations(_admin: dict = Depends(require_admin)):
    """Export the global branding translation bundle as JSON.

    Returns 404 if no global defaults exist — can't export what isn't there.
    The UI should only expose the Download button when defaults are enabled.
    """
    d = branding_defaults_store.load()
    if d is None:
        raise HTTPException(status_code=404, detail="No global branding defaults to export")
    return TranslationBundle.from_branding(d).model_dump()


@router.put("/defaults/translations")
async def put_defaults_translations(bundle: TranslationBundle, _admin: dict = Depends(require_admin)):
    """Import a translation bundle into global branding defaults.

    Overwrites source text + translations; preserves non-text fields (logo,
    colors, app_title, org_name). Creates a defaults record if none exists.
    Pushes the merged branding to every frontend that inherits defaults.
    """
    current = branding_defaults_store.load() or Branding()
    updated = bundle.apply_to(current)
    branding_defaults_store.save(updated)
    pushed = await _fanout_to_defaults_users()
    return {"defaults": updated.model_dump(), "pushed_to_frontends": pushed}


# --- LLM auto-translate (Sprint 8 phase D) ---

@router.post("/defaults/auto-translate")
async def auto_translate_defaults(_admin: dict = Depends(require_admin)):
    """Fill missing language keys in global branding defaults using the summariser LLM.

    404 if no global defaults exist. Existing non-empty translations are preserved.
    After filling, saves + pushes to every frontend that inherits defaults.
    """
    current = branding_defaults_store.load()
    if current is None:
        raise HTTPException(status_code=404, detail="No global branding defaults to translate")
    if not (current.disclaimer_text.strip() or current.instructions_text.strip()):
        raise HTTPException(status_code=400, detail="No source text in disclaimer_text or instructions_text")
    updated, stats = await auto_translate_branding(current, frontend_id=None, overwrite=False)
    branding_defaults_store.save(updated)
    pushed = await _fanout_to_defaults_users()
    return {"defaults": updated.model_dump(), "pushed_to_frontends": pushed, "stats": stats}
