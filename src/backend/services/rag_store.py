"""Admin RAG file CRUD + bridge to the real indexer.

Owns the on-disk file layout (upload / list / delete) and delegates indexing
to `rag_service`. Sprint 3 shipped a stub here; Sprint 5 keeps this thin
wrapper but reindex now triggers the real LlamaIndex build.

Paths:
- Global:  /app/data/documents/
- Frontend: /app/data/campaigns/{fid}/documents/
- Company:  /app/data/campaigns/{fid}/companies/{slug}/documents/
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from src.services._paths import (
    DOCUMENTS_DIR,
    company_dir,
    frontend_dir,
    safe_filename,
)

logger = logging.getLogger("rag_store")

# Permanent RAG (admin upload) accepts only PDF + plain text.
# Session RAG (chat uploads in Sprint 5+) additionally accepts .docx.
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


@dataclass
class RAGDocument:
    name: str
    size: int
    modified: float


@dataclass
class RAGStats:
    document_count: int
    total_size_bytes: int
    indexed: bool = False
    node_count: int = 0
    note: str = ""


def _tier_dir(frontend_id: str | None, company_slug: str | None) -> Path:
    if frontend_id is None and company_slug is None:
        return DOCUMENTS_DIR
    if frontend_id and company_slug is None:
        return frontend_dir(frontend_id) / "documents"
    if frontend_id and company_slug:
        return company_dir(frontend_id, company_slug) / "documents"
    raise ValueError("company_slug requires frontend_id")


def _check_ext(name: str) -> None:
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type {Path(name).suffix!r} not allowed. Accepted: {sorted(ALLOWED_EXTENSIONS)}"
        )


def list_documents(frontend_id: str | None = None, company_slug: str | None = None) -> list[RAGDocument]:
    d = _tier_dir(frontend_id, company_slug)
    if not d.exists():
        return []
    out: list[RAGDocument] = []
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        st = p.stat()
        out.append(RAGDocument(name=p.name, size=st.st_size, modified=st.st_mtime))
    return out


def save_document(name: str, content: bytes, frontend_id: str | None = None, company_slug: str | None = None) -> RAGDocument:
    from src.services import rag_service

    name = safe_filename(name)
    _check_ext(name)
    d = _tier_dir(frontend_id, company_slug)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    logger.info(f"Saved RAG document {path} ({len(content)} bytes)")
    # Drop the cached index so the next query sees the new doc. Phase B's file
    # watcher will additionally schedule a reindex; until then the admin clicks
    # Reindex (or the next query lazy-rebuilds).
    rag_service.invalidate(rag_service.scope_key_for(frontend_id, company_slug))
    st = path.stat()
    return RAGDocument(name=path.name, size=st.st_size, modified=st.st_mtime)


def delete_document(name: str, frontend_id: str | None = None, company_slug: str | None = None) -> bool:
    from src.services import rag_service

    name = safe_filename(name)
    d = _tier_dir(frontend_id, company_slug)
    path = d / name
    if not path.exists():
        return False
    path.unlink()
    logger.info(f"Deleted RAG document {path}")
    rag_service.invalidate(rag_service.scope_key_for(frontend_id, company_slug))
    return True


def stats(frontend_id: str | None = None, company_slug: str | None = None) -> RAGStats:
    from src.services import rag_service

    docs = list_documents(frontend_id, company_slug)
    total = sum(d.size for d in docs)
    sk = rag_service.scope_key_for(frontend_id, company_slug)
    info = rag_service.index_stats(sk)
    return RAGStats(
        document_count=len(docs),
        total_size_bytes=total,
        indexed=info["indexed"],
    )


def reindex(frontend_id: str | None = None, company_slug: str | None = None) -> RAGStats:
    """Trigger a real LlamaIndex rebuild for this scope and return live stats."""
    from src.services import rag_service

    sk = rag_service.scope_key_for(frontend_id, company_slug)
    result = rag_service.reindex(sk)
    docs = list_documents(frontend_id, company_slug)
    total = sum(d.size for d in docs)
    return RAGStats(
        document_count=result["document_count"],
        total_size_bytes=total,
        indexed=result["document_count"] > 0,
        node_count=result["node_count"],
    )
