"""Admin company registry API (SPEC §4.4)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.v1.admin.auth import require_admin
from src.services import company_registry as registry
from src.services.company_registry import Company

router = APIRouter(prefix="/admin/api/v1/frontends", tags=["admin-companies"])


class CreateCompanyRequest(BaseModel):
    slug: str
    display_name: str
    enabled: bool = True
    sort_order: int = 0
    is_compare_all: bool = False
    prompt_mode: str = "inherit"
    rag_mode: str = "combine_all"
    country_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateCompanyRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    is_compare_all: bool | None = None
    prompt_mode: str | None = None
    rag_mode: str | None = None
    country_tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


@router.get("/{frontend_id}/companies")
async def list_companies(frontend_id: str, _admin: dict = Depends(require_admin)):
    companies = registry.list_companies(frontend_id)
    return {"companies": [c.model_dump() for c in companies]}


@router.post("/{frontend_id}/companies", status_code=201)
async def create_company(frontend_id: str, req: CreateCompanyRequest, _admin: dict = Depends(require_admin)):
    try:
        company = Company(**req.model_dump())
        created = registry.create_company(frontend_id, company)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"company": created.model_dump()}


@router.patch("/{frontend_id}/companies/{slug}")
async def update_company(frontend_id: str, slug: str, req: UpdateCompanyRequest, _admin: dict = Depends(require_admin)):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        updated = registry.update_company(frontend_id, slug, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Company {slug!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"company": updated.model_dump()}


@router.delete("/{frontend_id}/companies/{slug}")
async def delete_company(frontend_id: str, slug: str, _admin: dict = Depends(require_admin)):
    removed = registry.delete_company(frontend_id, slug)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Company {slug!r} not found")
    return {"status": "deleted", "slug": slug}
