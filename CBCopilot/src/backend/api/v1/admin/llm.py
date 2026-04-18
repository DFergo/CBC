"""Admin LLM configuration (SPEC §4.7).

3 slots (inference, compressor, summariser) × 3 provider types (lm_studio, ollama, api).
The `api` provider stores only the ENV VAR NAME for the key — never the key itself.
Plus top-level compression settings + summary-routing toggles.
"""
from typing import Any

from fastapi import APIRouter, Depends

from src.api.v1.admin.auth import require_admin
from src.services import llm_config_store
from src.services.llm_config_store import LLMConfig

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
