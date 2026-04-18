"""Admin glossary + organizations CRUD (global only for Sprint 3)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services import knowledge_store
from src.services.knowledge_store import GlossaryTerm, Organization

router = APIRouter(prefix="/admin/api/v1/knowledge", tags=["admin-knowledge"])


class GlossaryUpdate(BaseModel):
    terms: list[GlossaryTerm]


class OrganizationsUpdate(BaseModel):
    organizations: list[Organization]


@router.get("/glossary")
async def get_glossary(_admin: dict = Depends(require_admin)):
    terms = knowledge_store.list_glossary()
    return {"terms": [t.model_dump() for t in terms]}


@router.put("/glossary")
async def save_glossary(req: GlossaryUpdate, _admin: dict = Depends(require_admin)):
    knowledge_store.save_glossary(req.terms)
    return {"terms": [t.model_dump() for t in req.terms]}


@router.get("/organizations")
async def get_organizations(_admin: dict = Depends(require_admin)):
    orgs = knowledge_store.list_organizations()
    return {"organizations": [o.model_dump() for o in orgs]}


@router.put("/organizations")
async def save_organizations(req: OrganizationsUpdate, _admin: dict = Depends(require_admin)):
    knowledge_store.save_organizations(req.organizations)
    return {"organizations": [o.model_dump() for o in req.organizations]}
