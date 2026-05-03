"""LLM configuration + health check (SPEC §4.7).

Three slots:
- `inference`  — main chat
- `compressor` — periodic context-window compression (progressive thresholds)
- `summariser` — document summaries on injection + final conversation summary

Plus a top-level `compression` block (enabled/first_threshold/step_size) and a
`routing` block with two summary-routing toggles. Fallback cascade on failure:
compressor → summariser → inference (preserved from HRDD Sprint 17; applied at
call-time in Sprint 6 llm_provider).

API key handling: only the env-var NAME is stored in the config file.
"""
import logging
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from src.core.config import config as backend_config
from src.services._paths import LLM_CONFIG_FILE, atomic_write_json, read_json

logger = logging.getLogger("llm_config")

ProviderType = Literal["lm_studio", "ollama", "api"]
ApiFlavor = Literal["anthropic", "openai", "openai_compatible"]
SlotName = Literal["inference", "compressor", "summariser"]


def _lm_studio_default() -> str:
    return backend_config.lm_studio_endpoint


def _ollama_default() -> str:
    return backend_config.ollama_endpoint


class SlotConfig(BaseModel):
    provider: ProviderType = "lm_studio"
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    num_ctx: int = 8192

    # Endpoint for local providers (lm_studio / ollama)
    endpoint: str = Field(default_factory=_lm_studio_default)

    # api provider — meaningful only when provider == "api"
    api_flavor: ApiFlavor | None = None
    api_endpoint: str | None = None
    api_key_env: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SlotConfig":
        if self.provider == "api":
            if not self.api_flavor:
                raise ValueError("api_flavor required when provider is 'api'")
            if not self.api_key_env:
                raise ValueError("api_key_env (env var NAME, not value) required when provider is 'api'")
            if not self.api_endpoint:
                self.api_endpoint = {
                    "anthropic": "https://api.anthropic.com/v1",
                    "openai": "https://api.openai.com/v1",
                    "openai_compatible": "",
                }[self.api_flavor]
        return self


class CompressionSettings(BaseModel):
    enabled: bool = False
    first_threshold: int = Field(20000, ge=1000)
    step_size: int = Field(15000, ge=500)


class RoutingToggles(BaseModel):
    document_summary_slot: SlotName = "summariser"
    user_summary_slot: SlotName = "summariser"
    # Sprint 15 phase 5: CR generates a 60-word context sentence per chunk at
    # ingest time. The task is "summarise this chunk with document context" —
    # doesn't need a 122B model. Default to `compressor` (small fast slot,
    # e.g. qwen3.5-9b on Ollama). For a 100-CBA corpus this cuts a CR reindex
    # from ~35 hours on the summariser slot to ~3-4 hours on the compressor.
    # Admin can bump to `summariser` if quality ever requires it.
    contextual_retrieval_slot: SlotName = "compressor"


def _default_compressor() -> SlotConfig:
    return SlotConfig(
        provider="ollama",
        endpoint=_ollama_default(),
        model=backend_config.ollama_summariser_model,
        temperature=0.3,
        max_tokens=1024,
        num_ctx=backend_config.ollama_num_ctx,
    )


class LLMConfig(BaseModel):
    inference: SlotConfig = Field(default_factory=SlotConfig)
    compressor: SlotConfig = Field(default_factory=_default_compressor)
    summariser: SlotConfig = Field(default_factory=SlotConfig)
    compression: CompressionSettings = Field(default_factory=CompressionSettings)
    routing: RoutingToggles = Field(default_factory=RoutingToggles)
    # Sprint 13: when True, the provider request body and the system prompt are
    # nudged to suppress reasoning/<think> tokens. Effective for qwen3 family
    # (think:false on Ollama, /no_think on LM Studio); harmless no-op for
    # models without a thinking mode (gemma, llama, mistral). Defaults to True
    # because thinking models hurt first-token latency in CBC's chat use.
    disable_thinking: bool = True
    # Sprint 14: concurrency ceiling for parallel chat turns across the whole
    # backend. polling.py runs frontends + their messages in parallel and
    # acquires a semaphore sized from this field before each LLM call.
    # Must align with OLLAMA_NUM_PARALLEL and LM Studio's per-model Parallel
    # setting — if CBC lets more through than the runtime can serve, the
    # excess queues INSIDE the runtime with no user-visible indicator.
    # 1 = serial (pre-Sprint-14 behaviour), 4 = default, 6 = heavy deployment.
    max_concurrent_turns: Literal[1, 2, 4, 6] = 4


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old 2-slot config (Sprint 3 initial) to the 3-slot shape.

    Old shape: {inference: {...}, summariser: {...}}
    New shape: {inference, compressor, summariser, compression, routing}

    The old `summariser` becomes the new `compressor` (it was lightweight, used
    for context compression). The new `summariser` starts from inference's config
    so it's immediately usable.
    """
    if "compressor" in data or "compression" in data:
        return data  # already new shape
    if "summariser" in data and "inference" in data:
        logger.info("Migrating legacy 2-slot LLM config to 3-slot shape")
        migrated = {
            "inference": data["inference"],
            "compressor": data["summariser"],
            "summariser": dict(data["inference"]),
        }
        return migrated
    return data


def load_config() -> LLMConfig:
    data = read_json(LLM_CONFIG_FILE)
    if not isinstance(data, dict):
        return LLMConfig()
    try:
        data = _migrate_legacy(data)
        return LLMConfig(**data)
    except Exception as e:
        logger.warning(f"Invalid llm_config.json ({e}); returning defaults")
        return LLMConfig()


def save_config(cfg: LLMConfig) -> None:
    atomic_write_json(LLM_CONFIG_FILE, cfg.model_dump())
    logger.info("LLM config saved")


def redact_for_response(cfg: LLMConfig) -> dict[str, Any]:
    """`api_key_env` is a variable NAME, not a secret — safe to return as-is."""
    return cfg.model_dump()


def _candidate_endpoints(provider: ProviderType) -> list[str]:
    """Ordered list of candidate endpoints to probe for a local provider.

    1. Whatever the deployment override says (deployment_backend.json), if set
    2. `host.docker.internal:<port>` — default for Docker-based deployments
    3. `localhost:<port>` — default for bare-metal / same-host deployments

    Duplicates are removed while preserving order.
    """
    if provider == "lm_studio":
        override = (backend_config.lm_studio_endpoint or "").strip()
        defaults = ["http://host.docker.internal:1234/v1", "http://localhost:1234/v1"]
    elif provider == "ollama":
        override = (backend_config.ollama_endpoint or "").strip()
        defaults = ["http://host.docker.internal:11434", "http://localhost:11434"]
    else:
        return []

    ordered = ([override] if override else []) + defaults
    seen: set[str] = set()
    result: list[str] = []
    for url in ordered:
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


async def _autodetect(provider: ProviderType, timeout: float = 2.0) -> dict[str, Any]:
    """Probe candidates in order, return the first one that answers.

    Returns {endpoint, ok, status_code, error, models}. If all candidates fail,
    returns the last one attempted with its error — so the UI can show the
    default users will actually hit.
    """
    candidates = _candidate_endpoints(provider)
    if not candidates:
        return {"endpoint": "", "ok": False, "status_code": 0, "error": "unknown provider", "models": []}

    last: dict[str, Any] = {}
    for url in candidates:
        r = await check_slot_health(SlotConfig(provider=provider, endpoint=url), timeout=timeout)
        last = {"endpoint": url, **r}
        if r["ok"]:
            return last
    return last


async def endpoint_defaults() -> dict[str, str]:
    """Auto-detected endpoint per provider, used by the admin UI for auto-fill.

    Probes the candidates from `_candidate_endpoints` and returns whichever
    responds. If none do, returns the last candidate attempted (so the UI still
    shows something sensible and the admin can see what to override).
    """
    lm = await _autodetect("lm_studio")
    ol = await _autodetect("ollama")
    return {
        "lm_studio": lm["endpoint"],
        "ollama": ol["endpoint"],
    }


def _parse_models(provider: ProviderType, flavor: ApiFlavor | None, payload: Any) -> list[str]:
    """Extract model IDs from a provider's /models response.

    LM Studio + OpenAI + Anthropic + OpenAI-compatible → OpenAI-style payload:
        {"data": [{"id": "..."}, ...]}
    Ollama /api/tags → {"models": [{"name": "..."}, ...]}.
    """
    if not isinstance(payload, dict):
        return []
    if provider == "ollama":
        return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    return [m.get("id", "") for m in payload.get("data", []) if m.get("id")]


async def check_slot_health(slot: SlotConfig, timeout: float = 5.0) -> dict[str, Any]:
    """Light HTTP probe + model listing.

    - lm_studio: GET {endpoint}/models  (OpenAI-compatible)
    - ollama:    GET {endpoint}/api/tags
    - api:       verify env var is set, GET {api_endpoint}/models with auth header

    Returns {ok, status_code, error, models}.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if slot.provider == "lm_studio":
                r = await client.get(f"{slot.endpoint.rstrip('/')}/models")
                models = _parse_models("lm_studio", None, r.json()) if r.status_code == 200 else []
                return _result(r.status_code == 200, r.status_code, None, models)

            if slot.provider == "ollama":
                r = await client.get(f"{slot.endpoint.rstrip('/')}/api/tags")
                models = _parse_models("ollama", None, r.json()) if r.status_code == 200 else []
                return _result(r.status_code == 200, r.status_code, None, models)

            # provider == "api"
            if not slot.api_key_env:
                return _result(False, 0, "api_key_env not set", [])
            key = os.environ.get(slot.api_key_env)
            if not key:
                return _result(False, 0, f"env var {slot.api_key_env} is not set in the container", [])

            headers: dict[str, str] = {}
            if slot.api_flavor == "anthropic":
                headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
                url = f"{slot.api_endpoint.rstrip('/')}/models"
            elif slot.api_flavor in ("openai", "openai_compatible"):
                headers["Authorization"] = f"Bearer {key}"
                url = f"{slot.api_endpoint.rstrip('/')}/models"
            else:
                return _result(False, 0, f"unknown api_flavor {slot.api_flavor!r}", [])

            r = await client.get(url, headers=headers)
            models = _parse_models("api", slot.api_flavor, r.json()) if r.status_code == 200 else []
            err = None if r.status_code == 200 else r.text[:200]
            return _result(r.status_code == 200, r.status_code, err, models)
        except httpx.HTTPError as e:
            return _result(False, 0, str(e), [])


def _slot_endpoint_for_provider(cfg: "LLMConfig", provider: ProviderType) -> str | None:
    """Return the endpoint of the first slot that uses this provider (inference
    → compressor → summariser order), or None if no slot does.
    """
    for slot in (cfg.inference, cfg.compressor, cfg.summariser):
        if slot.provider == provider and slot.endpoint:
            return slot.endpoint
    return None


async def fetch_provider_status(timeout: float = 5.0) -> dict[str, Any]:
    """Probe every configured provider and return status + model list.

    Feeds the top-level indicator in the admin LLM section (HRDD pattern) +
    populates the per-slot model dropdown.

    Shape (Sprint 18 Fase 5 — extended for `api` providers):
    {
      "lm_studio": { endpoint, status, models, error },
      "ollama":    { endpoint, status, models, error },
      "api":       [
        { slot, api_flavor, api_endpoint, api_key_env, status, models, error },
        ...one entry per slot configured with provider=api...
      ]
    }

    Logic per provider:
    - lm_studio / ollama (single endpoint each): if a saved slot uses this
      provider, probe that slot's endpoint; otherwise run auto-detect
      (host.docker.internal → localhost, with deployment_backend.json
      override taking priority if set).
    - api (potentially multiple): iterate every slot whose provider is
      "api" and probe each one — different slots may point at different
      API providers (e.g. summariser=Anthropic, inference=MiniMax). Each
      slot becomes its own entry in the result list.
    """
    cfg = load_config()
    result: dict[str, Any] = {}

    for provider_type in ("lm_studio", "ollama"):
        slot_endpoint = _slot_endpoint_for_provider(cfg, provider_type)
        if slot_endpoint:
            r = await check_slot_health(
                SlotConfig(provider=provider_type, endpoint=slot_endpoint),
                timeout=timeout,
            )
            endpoint = slot_endpoint
            ok = r["ok"]
            models = r["models"]
            error = r["error"]
        else:
            detected = await _autodetect(provider_type, timeout=timeout)
            endpoint = detected["endpoint"]
            ok = detected["ok"]
            models = detected["models"]
            error = detected["error"]

        result[provider_type] = {
            "endpoint": endpoint,
            "status": "online" if ok else "offline",
            "models": models,
            "error": error,
        }

    # Sprint 18 Fase 5 — also probe every slot configured as `api`. Each slot
    # is its own entry (different endpoint / flavor / key per slot is allowed:
    # you can have summariser=Anthropic + inference=MiniMax in the same setup).
    api_entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for slot_name, slot in (
        ("inference", cfg.inference),
        ("compressor", cfg.compressor),
        ("summariser", cfg.summariser),
    ):
        if slot.provider != "api":
            continue
        # Dedup: if two slots happen to point at the exact same api_endpoint
        # + flavor + key_env, probe once and report both slot names.
        key = (slot.api_endpoint or "", slot.api_flavor, slot.api_key_env)
        if key in seen:
            for entry in api_entries:
                if (
                    entry["api_endpoint"] == (slot.api_endpoint or "")
                    and entry["api_flavor"] == slot.api_flavor
                    and entry["api_key_env"] == slot.api_key_env
                ):
                    entry["slots"].append(slot_name)
            continue
        seen.add(key)
        r = await check_slot_health(slot, timeout=timeout)
        api_entries.append({
            "slots": [slot_name],
            "api_flavor": slot.api_flavor,
            "api_endpoint": slot.api_endpoint or "",
            "api_key_env": slot.api_key_env,
            "status": "online" if r["ok"] else "offline",
            "models": r["models"],
            "error": r["error"],
        })
    result["api"] = api_entries

    return result


def _result(ok: bool, status: int, error: str | None, models: list[str] | None = None) -> dict[str, Any]:
    return {"ok": ok, "status_code": status, "error": error, "models": models or []}
