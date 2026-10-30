"""Admin LLM configuration (SPEC §4.7).

4 slots (inference, compressor, summariser, translation), each referencing a
named connection from the registry (connection_registry.py) instead of
embedding its own provider/endpoint/api_key. The `api` connection type stores
either a pasted key or an ENV VAR NAME — never both in plaintext in the
response (pasted keys are redacted with a sentinel).
Plus top-level compression settings + summary-routing toggles.
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services import connection_registry, llm_config_store
from src.services.llm_config_store import (
    API_KEY_SENTINEL,
    CompressionSettings,
    LLMConfig,
    RoutingToggles,
    SlotConfig,
)

router = APIRouter(prefix="/admin/api/v1/llm", tags=["admin-llm"])


class LLMSettingsPatch(BaseModel):
    """Everything in LLMConfig that ISN'T one of the 4 slots — saved
    independently via PUT /settings so editing a slot card never touches
    these, and vice versa."""
    compression: CompressionSettings
    routing: RoutingToggles
    max_concurrent_turns: Literal[1, 2, 4, 6]
    # Sprint 22: replaced by the per-slot `reasoning` setting. Still accepted
    # (and ignored) so an admin page loaded before the upgrade can save.
    disable_thinking: bool | None = None


class ConnectionModel(BaseModel):
    id: str
    type: str
    api_flavor: str | None = None
    endpoint: str | None = None
    api_endpoint: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    model_ids: list[str] = []
    enable: bool = True
    # Sprint 22 provider options (see llm_capabilities.py)
    provider: str = ""                 # "" = infer from type/api_endpoint
    prompt_cache_key: bool = False     # send a per-session cache key (hash)
    routing: dict[str, Any] = {}       # OpenRouter `provider` object


def _redact_connection(conn: dict[str, Any]) -> dict[str, Any]:
    out = dict(conn)
    if (out.get("api_key") or "").strip():
        out["api_key"] = API_KEY_SENTINEL
    return out


@router.get("")
async def get_config(_admin: dict = Depends(require_admin)):
    cfg = llm_config_store.load_config()
    return llm_config_store.redact_for_response(cfg)


@router.put("")
async def save_config(cfg: LLMConfig, _admin: dict = Depends(require_admin)):
    llm_config_store.save_config(cfg)
    return llm_config_store.redact_for_response(cfg)


@router.put("/slots/{slot_name}")
async def save_slot(slot_name: str, slot: SlotConfig, _admin: dict = Depends(require_admin)):
    """Save a single slot in isolation — read-modify-write against the
    persisted config, leaving every other slot and the top-level settings
    (compression/routing/max_concurrent_turns) untouched.
    Backs the per-slot Save button in the admin's LLM section."""
    if slot_name not in llm_config_store.SLOT_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown slot: {slot_name!r}")
    cfg = llm_config_store.load_config()
    setattr(cfg, slot_name, slot)
    llm_config_store.save_config(cfg)
    return llm_config_store.redact_for_response(cfg)


@router.put("/settings")
async def save_settings(patch: LLMSettingsPatch, _admin: dict = Depends(require_admin)):
    """Save the non-slot settings in isolation — leaves all 4 slots
    untouched. Backs the "additional settings" Save button (thinking mode,
    concurrency, context compression, summary routing)."""
    cfg = llm_config_store.load_config()
    cfg.compression = patch.compression
    cfg.routing = patch.routing
    cfg.max_concurrent_turns = patch.max_concurrent_turns
    llm_config_store.save_config(cfg)
    return llm_config_store.redact_for_response(cfg)


class CapabilitiesRequest(BaseModel):
    connection: str
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    num_ctx: int | None = None
    reasoning: str | None = None


@router.post("/capabilities")
async def slot_capabilities(req: CapabilitiesRequest, _admin: dict = Depends(require_admin)):
    """Which of a slot's controls are sent, adjusted or ignored on this
    connection + model (Sprint 22) — so the admin never shows a silent no-op.
    Takes the values being edited, not only the saved ones."""
    from src.services import llm_capabilities, llm_provider
    conn = connection_registry.connections.get(req.connection)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    info = await llm_provider.model_info(req.connection, req.model) if req.model else {}
    out = llm_capabilities.describe(conn, req.model, req.model_dump(), info.get("supported_parameters"))
    out["context_length"] = info.get("context_length")
    return out


@router.get("/usage")
async def llm_usage_summary(_admin: dict = Depends(require_admin)):
    """Token and prompt-cache usage per slot/connection/model since the last reset."""
    from src.services import llm_usage
    return {"rows": llm_usage.global_summary()}


@router.post("/usage/reset")
async def llm_usage_reset(_admin: dict = Depends(require_admin)):
    from src.services import llm_usage
    llm_usage.reset_global()
    return {"rows": []}


@router.get("/defaults")
async def get_defaults(_admin: dict = Depends(require_admin)):
    """Auto-detected endpoint per local provider type (for prefilling a NEW
    lm_studio/ollama connection's Endpoint field).

    Probe order: `deployment_backend.json` override first (if set), then
    `host.docker.internal:<port>`, then `localhost:<port>`.
    """
    return await llm_config_store.endpoint_defaults()


# --- Connections registry ---


@router.get("/connections")
async def list_connections(_admin: dict = Depends(require_admin)):
    return [_redact_connection(c) for c in connection_registry.connections.all()]


@router.post("/connections")
async def create_connection(conn: ConnectionModel, _admin: dict = Depends(require_admin)):
    try:
        created = connection_registry.connections.add(conn.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _redact_connection(created)


@router.put("/connections/{connection_id}")
async def update_connection(
    connection_id: str, conn: ConnectionModel, _admin: dict = Depends(require_admin)
):
    patch = conn.model_dump()
    # Sentinel rule — same as the old per-slot api_key handling: if the admin
    # opened the form and didn't retype the key, preserve the stored value.
    if (patch.get("api_key") or "") == API_KEY_SENTINEL:
        existing = connection_registry.connections.get(connection_id)
        patch["api_key"] = (existing or {}).get("api_key")
    try:
        updated = connection_registry.connections.update(connection_id, patch)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _redact_connection(updated)


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, _admin: dict = Depends(require_admin)):
    connection_registry.connections.delete(connection_id)
    return {"ok": True}


@router.get("/connections/status")
async def connections_status(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Live status + model list for every enabled connection. Drives the
    admin's Connections list indicator + every slot's model dropdown. Polled
    every ~15s by the admin UI."""
    return await llm_config_store.fetch_connections_status()


@router.post("/connections/probe")
async def probe_connection(conn: ConnectionModel, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Probe an in-progress (not yet saved) connection so the admin UI can
    show the model catalogue before persisting.

    Sentinel rule: if `api_key` arrives as the redact sentinel, the admin
    opened the form for an EXISTING saved connection and didn't retype the
    key — resolve it from the persisted registry by id.
    """
    conn_dict = conn.model_dump()
    if conn_dict.get("type") == "api" and (conn_dict.get("api_key") or "") == API_KEY_SENTINEL:
        saved = connection_registry.connections.get(conn.id)
        if saved:
            conn_dict["api_key"] = saved.get("api_key")
    return await llm_config_store.check_connection_health(conn_dict)


# --- Per-slot health ---


@router.post("/health")
async def health(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    cfg = llm_config_store.load_config()
    result: dict[str, Any] = {}
    for slot_name in llm_config_store.SLOT_NAMES:
        slot: SlotConfig = getattr(cfg, slot_name)
        r = await llm_config_store.check_slot_health(slot)
        result[slot_name] = {"connection_id": slot.connection_id, **r}
    return result
