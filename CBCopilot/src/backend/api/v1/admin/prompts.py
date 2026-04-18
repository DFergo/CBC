"""Admin prompt CRUD across 3 tiers (SPEC §4.1).

Sprint 3 admin UI (GeneralTab) only exposes global prompts. Per-frontend and
per-company endpoints are here too — Sprint 4's FrontendsTab UI will wire them up.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services import prompt_store

router = APIRouter(prefix="/admin/api/v1", tags=["admin-prompts"])


class PromptSaveRequest(BaseModel):
    content: str


def _params(frontend_id: str | None, company_slug: str | None) -> tuple[str | None, str | None]:
    if company_slug and not frontend_id:
        raise HTTPException(status_code=400, detail="company_slug requires frontend_id")
    return frontend_id, company_slug


# --- Global tier ---

@router.get("/prompts")
async def list_global(_admin: dict = Depends(require_admin)):
    prompts = prompt_store.list_prompts()
    return {"prompts": [p.__dict__ for p in prompts]}


@router.get("/prompts/{name}")
async def read_global(name: str, _admin: dict = Depends(require_admin)):
    try:
        content = prompt_store.read_prompt(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found")
    return {"name": name, "content": content}


@router.put("/prompts/{name}")
async def save_global(name: str, req: PromptSaveRequest, _admin: dict = Depends(require_admin)):
    try:
        saved = prompt_store.write_prompt(name, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return saved.__dict__


@router.delete("/prompts/{name}")
async def delete_global(name: str, _admin: dict = Depends(require_admin)):
    ok = prompt_store.delete_prompt(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found")
    return {"status": "deleted", "name": name}


# --- Frontend tier ---

@router.get("/frontends/{frontend_id}/prompts")
async def list_frontend(frontend_id: str, _admin: dict = Depends(require_admin)):
    prompts = prompt_store.list_prompts(frontend_id=frontend_id)
    return {"prompts": [p.__dict__ for p in prompts]}


@router.get("/frontends/{frontend_id}/prompts/{name}")
async def read_frontend(frontend_id: str, name: str, _admin: dict = Depends(require_admin)):
    try:
        content = prompt_store.read_prompt(name, frontend_id=frontend_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found for frontend {frontend_id}")
    return {"name": name, "content": content, "frontend_id": frontend_id}


@router.put("/frontends/{frontend_id}/prompts/{name}")
async def save_frontend(frontend_id: str, name: str, req: PromptSaveRequest, _admin: dict = Depends(require_admin)):
    try:
        saved = prompt_store.write_prompt(name, req.content, frontend_id=frontend_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return saved.__dict__


@router.delete("/frontends/{frontend_id}/prompts/{name}")
async def delete_frontend(frontend_id: str, name: str, _admin: dict = Depends(require_admin)):
    ok = prompt_store.delete_prompt(name, frontend_id=frontend_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found for frontend {frontend_id}")
    return {"status": "deleted", "name": name}


# --- Company tier ---

@router.get("/frontends/{frontend_id}/companies/{company_slug}/prompts")
async def list_company(frontend_id: str, company_slug: str, _admin: dict = Depends(require_admin)):
    prompts = prompt_store.list_prompts(frontend_id=frontend_id, company_slug=company_slug)
    return {"prompts": [p.__dict__ for p in prompts]}


@router.get("/frontends/{frontend_id}/companies/{company_slug}/prompts/{name}")
async def read_company(frontend_id: str, company_slug: str, name: str, _admin: dict = Depends(require_admin)):
    try:
        content = prompt_store.read_prompt(name, frontend_id=frontend_id, company_slug=company_slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found for company {company_slug}")
    return {"name": name, "content": content, "frontend_id": frontend_id, "company_slug": company_slug}


@router.put("/frontends/{frontend_id}/companies/{company_slug}/prompts/{name}")
async def save_company(frontend_id: str, company_slug: str, name: str, req: PromptSaveRequest, _admin: dict = Depends(require_admin)):
    try:
        saved = prompt_store.write_prompt(name, req.content, frontend_id=frontend_id, company_slug=company_slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return saved.__dict__


@router.delete("/frontends/{frontend_id}/companies/{company_slug}/prompts/{name}")
async def delete_company(frontend_id: str, company_slug: str, name: str, _admin: dict = Depends(require_admin)):
    ok = prompt_store.delete_prompt(name, frontend_id=frontend_id, company_slug=company_slug)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found for company {company_slug}")
    return {"status": "deleted", "name": name}
