"""Admin embedding + reranker provider configuration (Sprint 20).

Mirrors `admin/llm.py`'s shape (GET/PUT config, probe/test-connection) plus
the collection-management endpoints needed for the blue-green Chroma
versioning scheme in `rag_service.py`. See docs/SPEC.md for the full
provider-swap flow this API drives.
"""
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services import embedding_config_store, rag_service
from src.services.embedding_config_store import (
    EmbeddingConfig,
    EmbeddingSlotConfig,
    RerankerSlotConfig,
)

router = APIRouter(prefix="/admin/api/v1/embedding-config", tags=["admin-embedding"])


def _pending_reindex(cfg: EmbeddingConfig) -> bool:
    """Whether the configured embedding target differs from what's
    currently active — i.e. a reindex-to-new-provider is needed before the
    saved config actually takes effect for queries."""
    active = rag_service._read_active_collection_pointer()
    target_provider = cfg.embedding.provider
    target_model = (
        rag_service.backend_config.rag_embedding_model
        if target_provider == "local"
        else cfg.embedding.model
    )
    target_name = rag_service._collection_name_for(target_provider, target_model, kind="chunks")
    return target_name != active["chunks_collection"]


@router.get("")
async def get_config(_admin: dict = Depends(require_admin)):
    cfg = embedding_config_store.load_config()
    out = embedding_config_store.redact_for_response(cfg)
    out["pending_reindex"] = _pending_reindex(cfg)
    out["active_collection"] = rag_service._read_active_collection_pointer()
    return out


@router.put("")
async def save_config(cfg: EmbeddingConfig, _admin: dict = Depends(require_admin)):
    embedding_config_store.save_config(cfg)
    # Reranker changes are pure query-time swaps — no reindex needed, so
    # invalidate its cache immediately. Embedding-slot changes must NOT
    # touch the embedder cache here: the active collection is still built
    # with the OLD provider/model until a successful blue-green reindex,
    # and invalidating now would make `_get_embed_model()` re-resolve to
    # the NEW (unreindexed) target on the next call, desyncing queries
    # against the still-old collection.
    rag_service.invalidate_reranker_cache()
    out = embedding_config_store.redact_for_response(cfg)
    out["pending_reindex"] = _pending_reindex(cfg)
    out["active_collection"] = rag_service._read_active_collection_pointer()
    return out


class SlotProbeRequest(BaseModel):
    kind: str  # "embedding" | "reranker"
    slot: dict[str, Any]
    # Sprint 20 followup 3 — when False, only `GET {endpoint}/models` runs
    # (no model name needed at all). The frontend sends this whenever the
    # admin hasn't picked a model yet, so the very first "Test connection"
    # click just lists what the server has instead of failing a real embed/
    # rerank call against a placeholder model name.
    deep: bool = True


@router.post("/test-connection")
async def test_connection(req: SlotProbeRequest, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Probe an in-progress (not-yet-saved) slot config. Resolves the
    redact sentinel against the saved config first, same rule as
    `admin/llm.py`'s `/providers/probe`."""
    if req.kind not in ("embedding", "reranker"):
        raise HTTPException(status_code=400, detail="kind must be 'embedding' or 'reranker'")

    if not req.deep:
        # List-only path — deliberately does NOT construct a validated
        # EmbeddingSlotConfig/RerankerSlotConfig, since that would require a
        # non-empty `model` for provider != "local" and raise before we ever
        # get to list anything. Read the raw fields straight off the dict.
        return await embedding_config_store.list_provider_models(
            req.slot.get("api_endpoint"),
            req.slot.get("api_key"),
            req.slot.get("api_key_env"),
        )

    saved = embedding_config_store.load_config()
    if req.kind == "embedding":
        slot = EmbeddingSlotConfig(**req.slot)
        if slot.provider != "local" and (slot.api_key or "") == embedding_config_store.API_KEY_SENTINEL:
            saved_slot = saved.embedding
            if saved_slot.provider == slot.provider and saved_slot.api_endpoint == slot.api_endpoint:
                slot.api_key = saved_slot.api_key
        return await embedding_config_store.check_embedding_slot_health(slot)

    slot = RerankerSlotConfig(**req.slot)
    if slot.provider != "local" and (slot.api_key or "") == embedding_config_store.API_KEY_SENTINEL:
        saved_slot = saved.reranker
        if saved_slot.provider == slot.provider and saved_slot.api_endpoint == slot.api_endpoint:
            slot.api_key = saved_slot.api_key
    return await embedding_config_store.check_reranker_slot_health(slot)


@router.post("/reindex-to-new-provider")
async def reindex_to_new_provider(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Trigger the blue-green reindex described in `rag_service
    .reindex_all_scopes_into_new_collection`. Offloaded to a worker thread
    (same pattern as `POST /admin/api/v1/rag/wipe-and-reindex-all`) so the
    event loop stays responsive for the — potentially long — corpus-wide
    rebuild."""
    try:
        result = await asyncio.to_thread(rag_service.reindex_all_scopes_into_new_collection)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reindex to new provider failed: {e}")
    return result


@router.get("/collections")
async def list_collections(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Sprint 20 hotfix — this touches ChromaDB (`_ensure_chroma_client()` /
    `_chroma_lock`), which can be the FIRST Chroma access of the process
    lifetime (e.g. right after a fresh deploy, before any chat query or
    reindex has run). `RAGPipelineSection` now calls this unconditionally
    on every admin General-tab mount, so unlike before Sprint 20 — when
    Chroma was only ever touched from an already-offloaded background
    thread (chat queries via `asyncio.to_thread`-wrapped retrieval, or the
    reindex endpoints below) — this became a frequently-hit synchronous
    Chroma touch running directly on the event loop thread. If that first
    touch is ever slow (cold FS cache, concurrent watcher activity holding
    `_chroma_lock`), it froze the ENTIRE server, not just this request,
    because a plain `threading.Lock` blocks whichever thread calls it and
    there is only one event-loop thread. `asyncio.to_thread` — same
    pattern already used correctly by `reindex_to_new_provider` below —
    moves the blocking call to a worker thread so a slow/stuck Chroma
    access degrades to one delayed request instead of a total outage."""
    collections = await asyncio.to_thread(rag_service.list_chroma_collections_with_stats)
    return {"collections": collections}


@router.delete("/collections/{name}")
async def delete_collection(name: str, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Same `asyncio.to_thread` rationale as `list_collections` above —
    `delete_chroma_collection` also touches `_ensure_chroma_client()`."""
    try:
        return await asyncio.to_thread(rag_service.delete_chroma_collection, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete collection: {e}")
