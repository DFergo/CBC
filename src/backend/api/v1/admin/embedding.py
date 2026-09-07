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


@router.post("/test-connection")
async def test_connection(req: SlotProbeRequest, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Probe an in-progress (not-yet-saved) slot config. Resolves the
    redact sentinel against the saved config first, same rule as
    `admin/llm.py`'s `/providers/probe`."""
    if req.kind not in ("embedding", "reranker"):
        raise HTTPException(status_code=400, detail="kind must be 'embedding' or 'reranker'")

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
    return {"collections": rag_service.list_chroma_collections_with_stats()}


@router.delete("/collections/{name}")
async def delete_collection(name: str, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    try:
        return rag_service.delete_chroma_collection(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete collection: {e}")
