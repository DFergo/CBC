"""Admin preview endpoints for the 3-tier resolvers (Sprint 4B).

These don't alter state — admins hit them from the UI to answer "given
frontend=X, company=Y, which prompt/RAG/orgs would actually be used?". The
chat engine (Sprint 6) calls the same resolver functions.
"""
from fastapi import APIRouter, Depends

from src.api.v1.admin.auth import require_admin
from src.services import resolvers

router = APIRouter(prefix="/admin/api/v1/resolvers", tags=["admin-resolvers"])


@router.get("/prompt/{name}")
async def preview_prompt(
    name: str,
    frontend_id: str | None = None,
    company_slug: str | None = None,
    compare_all: bool = False,
    _admin: dict = Depends(require_admin),
):
    r = resolvers.resolve_prompt(name, frontend_id, company_slug, is_compare_all=compare_all)
    return {
        "name": r.name,
        "tier": r.tier,
        "path": str(r.path) if r.path else None,
        "content": r.content,
        "found": r.content is not None,
    }


@router.get("/rag")
async def preview_rag(
    frontend_id: str,
    company_slug: str | None = None,
    compare_all: bool = False,
    comparison_scope: str | None = None,
    user_country: str | None = None,
    _admin: dict = Depends(require_admin),
):
    r = resolvers.resolve_rag_paths(
        frontend_id=frontend_id,
        company_slug=company_slug,
        is_compare_all=compare_all,
        comparison_scope=comparison_scope,
        user_country=user_country,
    )
    return {
        "paths": r.paths,
        "frontend_standalone": r.frontend_standalone,
        "total_docs": sum(p["doc_count"] for p in r.paths),
    }


@router.get("/orgs")
async def preview_orgs(
    frontend_id: str | None = None,
    _admin: dict = Depends(require_admin),
):
    return resolvers.resolve_orgs(frontend_id)
