"""Admin API for the Sprint 16 Structured Table Pipeline.

Every scope (global / frontend / company) has a `tables/` directory holding
one sub-directory per source document. The admin panel needs three things:

- list what tables we've extracted for a scope (so the admin can verify
  that a freshly uploaded CBA actually produced the expected salary /
  overtime CSVs),
- trigger a re-extraction on demand (useful when the extractor code
  changes or the admin wants to confirm a fix without waiting for the
  file watcher's 5 s debounce), and
- stream one CSV back to the browser for preview / download.

The list endpoint also returns a per-table row preview so the admin UI
can show the first N rows inline without fetching each CSV separately.
"""
from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from src.api.v1.admin.auth import require_admin
from src.services import rag_service, table_extractor

router = APIRouter(prefix="/admin/api/v1", tags=["admin-tables"])


def _qs(frontend_id: str | None, company_slug: str | None) -> str:
    """Resolve the (frontend_id, company_slug) pair into the scope_key that
    rag_service + table_extractor understand. Same rules as the RAG admin
    router's _qs but simpler here — we always return the resolved scope."""
    if company_slug and not frontend_id:
        raise HTTPException(status_code=400, detail="company_slug requires frontend_id")
    if frontend_id and company_slug:
        return f"{frontend_id}/{company_slug}"
    if frontend_id:
        return frontend_id
    return "global"


def _csv_preview(csv_text: str, max_rows: int = 5) -> list[list[str]]:
    """Return the first N data rows + the header as a list-of-lists. Silently
    truncates malformed rows. Used by the admin UI to show a peek without
    fetching the full CSV file."""
    if not csv_text:
        return []
    reader = csv.reader(io.StringIO(csv_text))
    out: list[list[str]] = []
    for i, row in enumerate(reader):
        if i > max_rows:
            break
        out.append(row)
    return out


@router.get("/tables")
async def list_tables(
    frontend_id: str | None = None,
    company_slug: str | None = None,
    _admin: dict = Depends(require_admin),
):
    """List every extracted table for a scope, grouped by source document.
    Each table carries its preview (first 5 rows) so the admin UI can
    render inline without a second round-trip."""
    scope_key = _qs(frontend_id, company_slug)
    manifests = table_extractor.list_scope_tables(scope_key)

    out_docs: list[dict] = []
    for m in manifests:
        doc_name = m.get("doc_name") or ""
        tables_out: list[dict] = []
        for t in m.get("tables", []):
            csv_text = table_extractor.load_csv(scope_key, doc_name, t.get("id", "")) or ""
            tables_out.append({
                "id": t.get("id"),
                "name": t.get("name"),
                "description": t.get("description"),
                "source_location": t.get("source_location"),
                "columns": t.get("columns") or [],
                "row_count": t.get("row_count") or 0,
                "preview_rows": _csv_preview(csv_text),
            })
        out_docs.append({
            "doc_name": doc_name,
            "tables": tables_out,
        })
    return {
        "scope_key": scope_key,
        "docs": out_docs,
        "doc_count": len(out_docs),
        "total_tables": sum(len(d["tables"]) for d in out_docs),
    }


@router.post("/tables/reextract")
async def reextract_tables(
    frontend_id: str | None = None,
    company_slug: str | None = None,
    _admin: dict = Depends(require_admin),
):
    """Force a re-extraction + re-embed of every table in this scope. Useful
    when the extractor code changes or the admin wants to verify a fix
    without waiting for the file watcher's 5 s debounce.

    Runs the FULL scope reindex (prose + tables) — there's no separate
    table-only ingest path since tables are derived from the same source
    files during `_build_index`. Offloaded to a worker thread so the
    event loop stays responsive (same pattern as Fase 0)."""
    scope_key = _qs(frontend_id, company_slug)
    try:
        result = await asyncio.to_thread(rag_service.reindex, scope_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Re-extract failed: {e}")
    # The reindex result is prose-focused; add a quick count of tables in
    # the scope post-reindex so the UI can show a "now has N tables" line.
    manifests = table_extractor.list_scope_tables(scope_key)
    total_tables = sum(len(m.get("tables", [])) for m in manifests)
    return {
        "status": "ok",
        "scope_key": scope_key,
        "reindex": result,
        "total_tables": total_tables,
    }


@router.get(
    "/tables/{frontend_id}/{company_slug}/{doc_name}/{table_id}.csv",
    response_class=PlainTextResponse,
)
async def download_table_csv(
    frontend_id: str,
    company_slug: str,
    doc_name: str,
    table_id: str,
    _admin: dict = Depends(require_admin),
):
    """Stream one table's CSV back as plain text. Scoped to company-tier
    (frontend + company in path). For global + frontend tiers use the
    query-param variant `/tables/global/{doc}/{id}.csv` below."""
    scope_key = f"{frontend_id}/{company_slug}"
    return _load_csv_or_404(scope_key, doc_name, table_id)


@router.get(
    "/tables-global/{doc_name}/{table_id}.csv",
    response_class=PlainTextResponse,
)
async def download_global_table_csv(
    doc_name: str,
    table_id: str,
    _admin: dict = Depends(require_admin),
):
    """Global-scope table CSV download."""
    return _load_csv_or_404("global", doc_name, table_id)


@router.get(
    "/tables-frontend/{frontend_id}/{doc_name}/{table_id}.csv",
    response_class=PlainTextResponse,
)
async def download_frontend_table_csv(
    frontend_id: str,
    doc_name: str,
    table_id: str,
    _admin: dict = Depends(require_admin),
):
    """Frontend-tier table CSV download."""
    return _load_csv_or_404(frontend_id, doc_name, table_id)


def _load_csv_or_404(scope_key: str, doc_name: str, table_id: str) -> str:
    """Shared loader for the three download routes. Raises 404 if the CSV
    doesn't exist (expired, never extracted, or wrong id)."""
    content = table_extractor.load_csv(scope_key, doc_name, table_id)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail=f"No CSV at scope={scope_key!r} doc={doc_name!r} table={table_id!r}",
        )
    return content
