"""Sprint 3 RAG stub: file upload + list + delete + fake-stats reindex.

Real indexing with LlamaIndex + 3-tier + file watcher lands in Sprint 5.
Documents live in the same layout the real indexer will use, so no migration
is needed — Sprint 5 just reads the same folders and builds indexes.

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
    note: str = "Sprint 3 stub — file metadata only. Real indexing arrives in Sprint 5."


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
    name = safe_filename(name)
    _check_ext(name)
    d = _tier_dir(frontend_id, company_slug)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    logger.info(f"Saved RAG document {path} ({len(content)} bytes)")
    st = path.stat()
    return RAGDocument(name=path.name, size=st.st_size, modified=st.st_mtime)


def delete_document(name: str, frontend_id: str | None = None, company_slug: str | None = None) -> bool:
    name = safe_filename(name)
    d = _tier_dir(frontend_id, company_slug)
    path = d / name
    if not path.exists():
        return False
    path.unlink()
    logger.info(f"Deleted RAG document {path}")
    return True


def stats(frontend_id: str | None = None, company_slug: str | None = None) -> RAGStats:
    docs = list_documents(frontend_id, company_slug)
    total = sum(d.size for d in docs)
    return RAGStats(document_count=len(docs), total_size_bytes=total)


def reindex(frontend_id: str | None = None, company_slug: str | None = None) -> RAGStats:
    """Sprint 3 stub — returns current stats. Sprint 5 replaces with real indexing."""
    s = stats(frontend_id, company_slug)
    logger.info(f"Reindex called (stub) — tier={frontend_id}/{company_slug} docs={s.document_count}")
    return s
