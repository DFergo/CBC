"""Admin RAG management (SPEC §4.2).

Sprint 3: file storage only (stub). Sprint 5 wires real LlamaIndex indexing.
3-tier paths are reused by the Sprint 5 service — no migration needed.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.v1.admin.auth import require_admin
from src.core.config import config
from src.services import rag_store

router = APIRouter(prefix="/admin/api/v1", tags=["admin-rag"])


MAX_UPLOAD_BYTES = config.file_max_size_mb * 1024 * 1024


def _qs(frontend_id: str | None, company_slug: str | None) -> tuple[str | None, str | None]:
    if company_slug and not frontend_id:
        raise HTTPException(status_code=400, detail="company_slug requires frontend_id")
    return frontend_id, company_slug


def _serialize(docs: list[rag_store.RAGDocument]) -> list[dict]:
    return [{"name": d.name, "size": d.size, "modified": d.modified} for d in docs]


@router.get("/rag/documents")
async def list_documents(frontend_id: str | None = None, company_slug: str | None = None, _admin: dict = Depends(require_admin)):
    fid, slug = _qs(frontend_id, company_slug)
    return {"documents": _serialize(rag_store.list_documents(fid, slug))}


@router.post("/rag/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    frontend_id: str | None = None,
    company_slug: str | None = None,
    _admin: dict = Depends(require_admin),
):
    fid, slug = _qs(frontend_id, company_slug)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {config.file_max_size_mb} MB.",
        )
    try:
        doc = rag_store.save_document(file.filename, content, fid, slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"document": {"name": doc.name, "size": doc.size, "modified": doc.modified}}


@router.delete("/rag/documents/{name}")
async def delete_document(name: str, frontend_id: str | None = None, company_slug: str | None = None, _admin: dict = Depends(require_admin)):
    fid, slug = _qs(frontend_id, company_slug)
    try:
        ok = rag_store.delete_document(name, fid, slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"Document {name!r} not found")
    return {"status": "deleted", "name": name}


@router.get("/rag/stats")
async def get_stats(frontend_id: str | None = None, company_slug: str | None = None, _admin: dict = Depends(require_admin)):
    fid, slug = _qs(frontend_id, company_slug)
    s = rag_store.stats(fid, slug)
    return {
        "document_count": s.document_count,
        "total_size_bytes": s.total_size_bytes,
        "note": s.note,
    }


@router.post("/rag/reindex")
async def reindex(frontend_id: str | None = None, company_slug: str | None = None, _admin: dict = Depends(require_admin)):
    fid, slug = _qs(frontend_id, company_slug)
    s = rag_store.reindex(fid, slug)
    return {
        "status": "ok",
        "document_count": s.document_count,
        "total_size_bytes": s.total_size_bytes,
        "note": s.note,
    }
