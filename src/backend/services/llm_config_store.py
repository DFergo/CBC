"""LLM configuration + health check (SPEC §4.7).

Four slots:
- `inference`   — main chat
- `compressor`  — periodic context-window compression (progressive thresholds)
- `summariser`  — document summaries on injection + final conversation summary
- `translation` — branding auto-translate (disclaimer/instructions → i18n
                   languages); previously hardwired to reuse `summariser`.

Plus a top-level `compression` block (enabled/first_threshold/step_size) and a
`routing` block with two summary-routing toggles (routes only among the
original 3 slots — translation is invoked directly, not part of routing).
Fallback cascade on failure: own slot → summariser → inference → compressor
(preserved from HRDD Sprint 17 / Daniel's Sprint 6A rule; applied at call-time
in llm_provider). `translation` additionally falls back into that same chain.

Each slot references a connection from the registry (connection_registry.py)
instead of embedding its own provider/endpoint/api_key — that's the Sprint-N
"LLM provider registry" port from HRDDHelper. API key handling now lives on
the connection record: only the env-var NAME or the pasted secret is stored
there, never duplicated per slot.
"""
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from src.services import connection_registry
from src.services._paths import LLM_CONFIG_FILE, atomic_write_json, read_json

logger = logging.getLogger("llm_config")

ProviderType = Literal["lm_studio", "ollama", "api"]
ApiFlavor = Literal["anthropic", "openai", "openai_compatible"]
SlotName = Literal["inference", "compressor", "summariser", "translation"]

SLOT_NAMES: tuple[SlotName, ...] = ("inference", "compressor", "summariser", "translation")


class SlotConfig(BaseModel):
    connection_id: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    num_ctx: int = 8192


# Sentinel string used to (a) tell the admin UI "this connection has an
# api_key set, just don't tell me what it is" and (b) tell the PUT handler
# "the user didn't retype the key, preserve the stored one". 8 bullet chars;
# unlikely to collide with a real provider key.
API_KEY_SENTINEL = "••••••••"


def resolve_api_key(conn: dict[str, Any]) -> str | None:
    """Return the actual api key for a connection dict, or None if neither
    source has a value. Inline `api_key` wins over env var (admin had to
    explicitly paste it, more recent + explicit). The env var path stays so
    deploys that wire keys via Portainer / vault keep working."""
    if conn.get("type") != "api":
        return None
    import os

    inline = (conn.get("api_key") or "").strip()
    if inline and inline != API_KEY_SENTINEL:
        return inline
    env_name = (conn.get("api_key_env") or "").strip()
    if env_name:
        env_val = os.environ.get(env_name)
        if env_val:
            return env_val
    return None


class CompressionSettings(BaseModel):
    enabled: bool = False
    first_threshold: int = Field(20000, ge=1000)
    step_size: int = Field(15000, ge=500)


class RoutingToggles(BaseModel):
    document_summary_slot: Literal["inference", "compressor", "summariser"] = "summariser"
    user_summary_slot: Literal["inference", "compressor", "summariser"] = "summariser"
    # Sprint 15 phase 5: CR generates a 60-word context sentence per chunk at
    # ingest time. The task is "summarise this chunk with document context" —
    # doesn't need a 122B model. Default to `compressor` (small fast slot,
    # e.g. qwen3.5-9b on Ollama). For a 100-CBA corpus this cuts a CR reindex
    # from ~35 hours on the summariser slot to ~3-4 hours on the compressor.
    # Admin can bump to `summariser` if quality ever requires it.
    contextual_retrieval_slot: Literal["inference", "compressor", "summariser"] = "compressor"


class LLMConfig(BaseModel):
    inference: SlotConfig = Field(default_factory=SlotConfig)
    compressor: SlotConfig = Field(default_factory=SlotConfig)
    summariser: SlotConfig = Field(default_factory=SlotConfig)
    translation: SlotConfig = Field(default_factory=SlotConfig)
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


def _migrate_legacy_slot(slot_data: dict[str, Any]) -> dict[str, Any]:
    """Convert one old-shape slot dict (inline provider/endpoint/api_key/...)
    into the new shape (connection_id + model + params), reusing or creating
    a connection in the registry. No-op if already migrated (has connection_id
    or lacks the old `provider` marker)."""
    if "connection_id" in slot_data or "provider" not in slot_data:
        return slot_data
    conn_id = connection_registry.connections.add_or_reuse({
        "id": f"migrated-{slot_data.get('provider', 'unknown')}",
        "type": slot_data.get("provider", "lm_studio"),
        "api_flavor": slot_data.get("api_flavor"),
        "endpoint": slot_data.get("endpoint"),
        "api_endpoint": slot_data.get("api_endpoint"),
        "api_key": slot_data.get("api_key"),
        "api_key_env": slot_data.get("api_key_env"),
    })
    return {
        "connection_id": conn_id,
        "model": slot_data.get("model", ""),
        "temperature": slot_data.get("temperature", 0.7),
        "max_tokens": slot_data.get("max_tokens", 4096),
        "num_ctx": slot_data.get("num_ctx", 8192),
    }


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old shapes to the current one:

    1. Sprint 3 initial 2-slot config {inference, summariser} → 3-slot shape
       (compressor takes over the old summariser role, summariser starts
       from inference).
    2. Pre-connection-registry 3-slot config (each slot has inline
       provider/endpoint/api_key fields) → connection_id-based slots, plus a
       new `translation` slot. Translation defaults to a copy of the
       (migrated) summariser slot's connection_id/model, so the existing
       auto-translate behaviour (which used to hardcode the summariser slot)
       doesn't change until the admin deliberately reconfigures it.
    """
    if "compressor" not in data and "compression" not in data:
        if "summariser" in data and "inference" in data:
            logger.info("Migrating legacy 2-slot LLM config to 3-slot shape")
            data = {
                "inference": data["inference"],
                "compressor": data["summariser"],
                "summariser": dict(data["inference"]),
            }

    inference = data.get("inference") or {}
    compressor = data.get("compressor") or {}
    summariser = data.get("summariser") or {}
    needs_connection_migration = any(
        "provider" in s and "connection_id" not in s
        for s in (inference, compressor, summariser)
        if isinstance(s, dict)
    )
    if needs_connection_migration:
        logger.info("Migrating legacy inline-provider LLM slots to connection_id shape")
        data = dict(data)
        data["inference"] = _migrate_legacy_slot(inference) if inference else inference
        data["compressor"] = _migrate_legacy_slot(compressor) if compressor else compressor
        data["summariser"] = _migrate_legacy_slot(summariser) if summariser else summariser
        if "translation" not in data:
            data["translation"] = dict(data["summariser"])

    if "translation" not in data:
        data = dict(data)
        data["translation"] = dict(data.get("summariser") or {})

    return data


def load_config() -> LLMConfig:
    data = read_json(LLM_CONFIG_FILE)
    if not isinstance(data, dict):
        return LLMConfig()
    try:
        migrated = _migrate_legacy(data)
        cfg = LLMConfig(**migrated)
        if migrated is not data:
            save_config(cfg)
        return cfg
    except Exception as e:
        logger.warning(f"Invalid llm_config.json ({e}); returning defaults")
        return LLMConfig()


def save_config(cfg: LLMConfig) -> None:
    atomic_write_json(LLM_CONFIG_FILE, cfg.model_dump())
    logger.info("LLM config saved")


def redact_for_response(cfg: LLMConfig) -> dict[str, Any]:
    """Slot dump has no secrets any more (those live on the connection record,
    redacted separately by the connections API) — kept for API-shape
    stability with callers that expect this helper's name."""
    return cfg.model_dump()


def _candidate_endpoints(provider: ProviderType) -> list[str]:
    """Ordered list of candidate endpoints to probe for a local provider.

    1. Whatever the deployment override says (deployment_backend.json), if set
    2. `host.docker.internal:<port>` — default for Docker-based deployments
    3. `localhost:<port>` — default for bare-metal / same-host deployments

    Duplicates are removed while preserving order.
    """
    from src.core.config import config as backend_config

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
        r = await check_connection_health({"type": provider, "endpoint": url}, timeout=timeout)
        last = {"endpoint": url, **r}
        if r["ok"]:
            return last
    return last


async def endpoint_defaults() -> dict[str, str]:
    """Auto-detected endpoint per provider, used by the admin UI for auto-fill
    when creating a NEW lm_studio/ollama connection."""
    lm = await _autodetect("lm_studio")
    ol = await _autodetect("ollama")
    return {
        "lm_studio": lm["endpoint"],
        "ollama": ol["endpoint"],
    }


def _parse_models(provider: ProviderType, payload: Any) -> list[str]:
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


def _result(ok: bool, status: int, error: str | None, models: list[str] | None = None) -> dict[str, Any]:
    return {"ok": ok, "status_code": status, "error": error, "models": models or []}


async def check_connection_health(conn: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Light HTTP probe + model listing for one connection record (or a
    transient in-progress dict shaped the same way, for the "Test connection"
    UX before Save).

    - lm_studio: GET {endpoint}/models  (OpenAI-compatible)
    - ollama:    GET {endpoint}/api/tags
    - api:       verify a key is resolvable, GET {api_endpoint}/models with
                 auth header appropriate to api_flavor

    Returns {ok, status_code, error, models}.
    """
    provider = conn.get("type")
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if provider == "lm_studio":
                endpoint = (conn.get("endpoint") or "").rstrip("/")
                r = await client.get(f"{endpoint}/models")
                models = _parse_models("lm_studio", r.json()) if r.status_code == 200 else []
                return _result(r.status_code == 200, r.status_code, None, models)

            if provider == "ollama":
                endpoint = (conn.get("endpoint") or "").rstrip("/")
                r = await client.get(f"{endpoint}/api/tags")
                models = _parse_models("ollama", r.json()) if r.status_code == 200 else []
                return _result(r.status_code == 200, r.status_code, None, models)

            # provider == "api"
            key = resolve_api_key(conn)
            if not key:
                if (conn.get("api_key") or "").strip():
                    return _result(False, 0, "api_key is empty (paste it in admin or set api_key_env)", [])
                env_name = (conn.get("api_key_env") or "").strip()
                if env_name:
                    return _result(False, 0, f"env var {env_name} is not set in the container", [])
                return _result(False, 0, "no api_key (paste in admin) and no api_key_env set", [])

            api_flavor = conn.get("api_flavor")
            api_endpoint = (conn.get("api_endpoint") or "").rstrip("/")
            headers: dict[str, str] = {}
            if api_flavor == "anthropic":
                headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
                url = f"{api_endpoint}/models"
            elif api_flavor in ("openai", "openai_compatible"):
                headers["Authorization"] = f"Bearer {key}"
                url = f"{api_endpoint}/models"
            else:
                return _result(False, 0, f"unknown api_flavor {api_flavor!r}", [])

            r = await client.get(url, headers=headers)
            models = _parse_models("api", r.json()) if r.status_code == 200 else []
            err = None if r.status_code == 200 else r.text[:200]
            return _result(r.status_code == 200, r.status_code, err, models)
        except httpx.HTTPError as e:
            return _result(False, 0, str(e), [])


async def check_slot_health(slot: SlotConfig, timeout: float = 5.0) -> dict[str, Any]:
    """Resolve the slot's connection and probe it. Used by /health."""
    conn = connection_registry.connections.get(slot.connection_id)
    if not conn:
        return _result(False, 0, f"no connection configured (connection_id={slot.connection_id!r})", [])
    return await check_connection_health(conn, timeout=timeout)


async def fetch_connections_status(timeout: float = 5.0) -> dict[str, Any]:
    """Probe every enabled connection in parallel. Returns
    {connection_id: {status, models, error}}. Feeds the admin's Connections
    list + every slot's model dropdown."""
    import asyncio

    enabled = connection_registry.connections.enabled()
    results = await asyncio.gather(
        *(check_connection_health(c, timeout=timeout) for c in enabled),
        return_exceptions=True,
    )
    status: dict[str, Any] = {}
    for conn, res in zip(enabled, results):
        if isinstance(res, Exception):
            status[conn["id"]] = {"status": "offline", "error": str(res), "models": []}
        else:
            status[conn["id"]] = {
                "status": "online" if res["ok"] else "offline",
                "models": res["models"],
                "error": res["error"],
            }
    return status
