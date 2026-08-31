"""Admin LLM configuration (SPEC §4.7).

3 slots (inference, compressor, summariser) × 3 provider types (lm_studio, ollama, api).
The `api` provider stores only the ENV VAR NAME for the key — never the key itself.
Plus top-level compression settings + summary-routing toggles.
"""
from typing import Any

from fastapi import APIRouter, Depends

from src.api.v1.admin.auth import require_admin
from src.services import llm_config_store
from src.services.llm_config_store import LLMConfig, SlotConfig

router = APIRouter(prefix="/admin/api/v1/llm", tags=["admin-llm"])


@router.get("")
async def get_config(_admin: dict = Depends(require_admin)):
    cfg = llm_config_store.load_config()
    return llm_config_store.redact_for_response(cfg)


@router.put("")
async def save_config(cfg: LLMConfig, _admin: dict = Depends(require_admin)):
    llm_config_store.save_config(cfg)
    return llm_config_store.redact_for_response(cfg)


@router.get("/defaults")
async def get_defaults(_admin: dict = Depends(require_admin)):
    """Auto-detected endpoint per provider (for UI auto-fill on provider change).

    Probe order: `deployment_backend.json` override first (if set), then
    `host.docker.internal:<port>`, then `localhost:<port>`. First to answer wins.
    If the admin wants a specific endpoint (e.g. Tailscale), they can always
    override it in the slot's Endpoint field — that saves normally.
    """
    return await llm_config_store.endpoint_defaults()


@router.get("/providers")
async def get_providers(_admin: dict = Depends(require_admin)):
    """Live status + model list for the default lm_studio + ollama endpoints.

    Drives the top indicator panel in the admin LLM section (HRDD pattern). The
    admin UI polls this every ~15s so the dots stay fresh; the models list
    populates the dropdown when a slot picks lm_studio or ollama.
    Per-slot / API endpoints are covered by POST /health.
    """
    return await llm_config_store.fetch_provider_status()


@router.post("/health")
async def health(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    cfg = llm_config_store.load_config()
    inference = await llm_config_store.check_slot_health(cfg.inference)
    compressor = await llm_config_store.check_slot_health(cfg.compressor)
    summariser = await llm_config_store.check_slot_health(cfg.summariser)
    return {
        "inference": {"provider": cfg.inference.provider, **inference},
        "compressor": {"provider": cfg.compressor.provider, **compressor},
        "summariser": {"provider": cfg.summariser.provider, **summariser},
    }


@router.post("/providers/probe")
async def probe_slot(slot: SlotConfig,
                     _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Sprint 19 followup — probe an in-progress slot config (NOT yet saved)
    so the admin UI can show the model catalogue before persisting.

    The admin types endpoint + flavor + api_key into the form, clicks
    "Test connection". The frontend POSTs the current values here. We
    instantiate a transient SlotConfig and run the same `check_slot_health`
    that the regular /health endpoint uses — but without touching the
    persisted llm_config.json. Result is purely a UX hint: status + model
    list to populate the dropdown.

    Sprint 19 Fase 1 sentinel rule: if `api_key` arrives as the redact
    sentinel, the admin opened the form for an EXISTING saved slot and
    didn't retype the key. Resolve from the persisted config instead.
    """
    # Sentinel resolution — if the admin pasted the sentinel back, look up
    # the real key from the saved config (matching by api_endpoint).
    if slot.provider == "api" and (slot.api_key or "") == llm_config_store.API_KEY_SENTINEL:
        saved = llm_config_store.load_config()
        for saved_slot in (saved.inference, saved.compressor, saved.summariser):
            if (
                saved_slot.provider == "api"
                and saved_slot.api_endpoint == slot.api_endpoint
                and saved_slot.api_flavor == slot.api_flavor
                and (saved_slot.api_key or "")
            ):
                slot.api_key = saved_slot.api_key
                break
    return await llm_config_store.check_slot_health(slot)
