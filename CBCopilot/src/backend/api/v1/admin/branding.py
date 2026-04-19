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
from fastapi import APIRouter, Depends

from src.api.v1.admin.auth import require_admin
from src.services import branding_defaults_store, branding_store, resolvers
from src.services.branding_store import Branding
from src.services.frontend_registry import registry

logger = logging.getLogger("admin.branding")

router = APIRouter(prefix="/admin/api/v1/branding", tags=["admin-branding"])

PUSH_TIMEOUT = 5.0


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
