"""Embedding + reranker provider configuration (Sprint 20).

Mirrors the `llm_config_store.py` pattern (same SlotConfig-style shape,
same API-key sentinel/redact/resolve dance) but for the RAG embedding +
reranker models instead of the chat LLM.

Two independent slots, same provider type:
- `embedding`: what turns chunk/query text into vectors.
- `reranker`:  what re-scores retrieved candidates (optional — `enabled`).

Three providers:
- "local"            — HuggingFace weights baked into the Docker image
                        (unchanged Sprint <20 behaviour). `model` is
                        restricted to the same pre-downloaded whitelist
                        as before (see rag_service.SUPPORTED_EMBEDDING_MODELS
                        / SUPPORTED_RERANKER_MODELS_LOCAL below).
                        IMPORTANT — for this provider `rag_service` ignores
                        this slot's `model` field entirely and instead uses
                        `backend_config.rag_embedding_model` /
                        `.rag_reranker_model` (the existing, already
                        runtime-overridable settings from Sprint 9/15).
                        This is a deliberate decision (see ARCHITECTURE.md
                        Sprint 20 section) to keep the "local" zero-config
                        default 100% unchanged and avoid two sources of
                        truth for the same setting. This slot's `model`
                        field is kept for schema symmetry / UI display only
                        when provider="local".
- "omlx"             — Daniel's self-hosted MLX inference server
                        (OpenAI-compatible /v1/embeddings + a de-facto
                        /v1/rerank endpoint shared by oMLX, HF TEI, vLLM,
                        Infinity). Suggested placeholder endpoint shown by
                        the admin UI, not hardcoded here.
- "openai_compatible" — any other OpenAI-compatible endpoint (real OpenAI,
                        another self-hosted server, etc). Same field shape
                        as "omlx", no suggested defaults. Reranking via
                        `/rerank` is NOT part of the OpenAI standard, so it
                        may not work against arbitrary "OpenAI-compatible"
                        providers — that caveat is surfaced in the admin UI.

API key handling reuses the exact sentinel/resolve pattern from
`llm_config_store` (imported, not duplicated) so the security properties
are identical: the raw key is never echoed back to the frontend, and a
`api_key_env` (env var name) is always an alternative to pasting the key.
"""
import logging
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from src.services._paths import EMBEDDING_CONFIG_FILE, atomic_write_json, read_json
from src.services.llm_config_store import API_KEY_SENTINEL

logger = logging.getLogger("embedding_config")

EmbeddingProviderType = Literal["local", "omlx", "openai_compatible"]

# Mirrors rag_service.SUPPORTED_EMBEDDING_MODELS. Duplicated (not imported)
# to avoid a module-level import of rag_service, which would create a
# circular import once rag_service imports this module for provider
# dispatch. Keep the two lists in sync manually — they're tiny and change
# only when the Dockerfile pre-downloads a new model.
SUPPORTED_EMBEDDING_MODELS_LOCAL: tuple[str, ...] = (
    "BAAI/bge-m3",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# The Dockerfile only pre-downloads bge-reranker-v2-m3 today (see
# Dockerfile.backend). Single-entry whitelist, same pattern as embeddings.
SUPPORTED_RERANKER_MODELS_LOCAL: tuple[str, ...] = (
    "BAAI/bge-reranker-v2-m3",
)


class EmbeddingSlotConfig(BaseModel):
    provider: EmbeddingProviderType = "local"
    model: str = "BAAI/bge-m3"

    # Meaningful only when provider != "local".
    api_endpoint: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "EmbeddingSlotConfig":
        if self.provider == "local":
            if self.model not in SUPPORTED_EMBEDDING_MODELS_LOCAL:
                raise ValueError(
                    f"local embedding model {self.model!r} not supported; "
                    f"pick one of {SUPPORTED_EMBEDDING_MODELS_LOCAL}"
                )
        else:
            if not (self.api_endpoint or "").strip():
                raise ValueError(f"api_endpoint required when provider={self.provider!r}")
            if not (self.model or "").strip():
                raise ValueError(f"model required when provider={self.provider!r}")
            # Note: unlike llm_config_store.SlotConfig, we do NOT hard-require
            # an api_key/api_key_env here — some self-hosted servers (oMLX
            # included, in Daniel's Tailscale-only deployment) accept requests
            # without auth. A missing key just means the health check /
            # actual embed call may fail with a 401, which surfaces clearly
            # via "Test connection" rather than blocking Save.
        return self


class RerankerSlotConfig(BaseModel):
    provider: EmbeddingProviderType = "local"
    model: str = "BAAI/bge-reranker-v2-m3"
    enabled: bool = True
    top_n: int = 8

    api_endpoint: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "RerankerSlotConfig":
        if self.provider == "local":
            if self.model not in SUPPORTED_RERANKER_MODELS_LOCAL:
                raise ValueError(
                    f"local reranker model {self.model!r} not supported; "
                    f"pick one of {SUPPORTED_RERANKER_MODELS_LOCAL}"
                )
        else:
            if not (self.api_endpoint or "").strip():
                raise ValueError(f"api_endpoint required when provider={self.provider!r}")
            if not (self.model or "").strip():
                raise ValueError(f"model required when provider={self.provider!r}")
        return self


class EmbeddingConfig(BaseModel):
    embedding: EmbeddingSlotConfig = Field(default_factory=EmbeddingSlotConfig)
    reranker: RerankerSlotConfig = Field(default_factory=RerankerSlotConfig)


def load_config() -> EmbeddingConfig:
    data = read_json(EMBEDDING_CONFIG_FILE)
    if not isinstance(data, dict):
        return EmbeddingConfig()
    try:
        return EmbeddingConfig(**data)
    except Exception as e:
        logger.warning(f"Invalid embedding_config.json ({e}); returning defaults")
        return EmbeddingConfig()


def save_config(cfg: EmbeddingConfig) -> None:
    """Persist the config. Preserves the stored api_key when the incoming
    value is the redact sentinel (admin opened the form, didn't retype the
    key) — identical rule to llm_config_store.save_config."""
    incoming = cfg.model_dump()
    prior = read_json(EMBEDDING_CONFIG_FILE)
    if isinstance(prior, dict):
        for slot_name in ("embedding", "reranker"):
            slot_in = incoming.get(slot_name) or {}
            slot_prev = (prior.get(slot_name) or {}) if isinstance(prior, dict) else {}
            if (slot_in.get("api_key") or "") == API_KEY_SENTINEL:
                slot_in["api_key"] = slot_prev.get("api_key") or None
                incoming[slot_name] = slot_in
    atomic_write_json(EMBEDDING_CONFIG_FILE, incoming)
    logger.info("Embedding config saved")


def redact_for_response(cfg: EmbeddingConfig) -> dict[str, Any]:
    out = cfg.model_dump()
    for slot_name in ("embedding", "reranker"):
        slot = out.get(slot_name) or {}
        if (slot.get("api_key") or "").strip():
            slot["api_key"] = API_KEY_SENTINEL
            out[slot_name] = slot
    return out


def resolve_api_key(slot: EmbeddingSlotConfig | RerankerSlotConfig) -> str | None:
    """Same precedence as llm_config_store.resolve_api_key: inline api_key
    wins (if not the sentinel), then api_key_env, else None."""
    if slot.provider == "local":
        return None
    inline = (slot.api_key or "").strip()
    if inline and inline != API_KEY_SENTINEL:
        return inline
    env_name = (slot.api_key_env or "").strip()
    if env_name:
        return os.environ.get(env_name)
    return None


def _result(ok: bool, status: int, error: str | None, models: list[str] | None = None) -> dict[str, Any]:
    return {"ok": ok, "status_code": status, "error": error, "models": models or []}


async def check_embedding_slot_health(
    slot: EmbeddingSlotConfig, timeout: float = 5.0, deep: bool = True
) -> dict[str, Any]:
    """Health check for the embedding slot.

    - local: no network call — the model name is already validated against
      the pre-downloaded whitelist by the Pydantic validator, and actually
      loading BGE-M3 here just to prove it works would be a multi-second
      blocking call on every "Test connection" click. Report ok=True with
      the whitelist as the "models" list so the admin UI's dropdown has
      something to show.
    - omlx / openai_compatible: GET {endpoint}/models (OpenAI-style) to
      populate the model dropdown, then (deep=True, the default) actually
      POST one short string to {endpoint}/embeddings to prove the round
      trip works end-to-end — a 200 on /models doesn't guarantee /embeddings
      accepts the configured model name. deep=False skips the second call
      for a faster / cheaper probe (used by the auto-refresh on every
      keystroke, if the admin UI ever adds that).
    """
    if slot.provider == "local":
        return _result(True, 200, None, list(SUPPORTED_EMBEDDING_MODELS_LOCAL))

    endpoint = (slot.api_endpoint or "").rstrip("/")
    if not endpoint:
        return _result(False, 0, "api_endpoint is empty", [])
    key = resolve_api_key(slot)
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.get(f"{endpoint}/models", headers=headers)
            models = (
                [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
                if r.status_code == 200
                else []
            )
            if r.status_code != 200:
                return _result(False, r.status_code, r.text[:200], [])
            if not deep:
                return _result(True, r.status_code, None, models)
            # Real round trip — embed a short string with the configured model.
            body = {"model": slot.model, "input": ["health check"]}
            er = await client.post(f"{endpoint}/embeddings", json=body, headers=headers)
            if er.status_code != 200:
                return _result(False, er.status_code, f"/embeddings failed: {er.text[:200]}", models)
            data = er.json().get("data") or []
            if not data or not data[0].get("embedding"):
                return _result(False, er.status_code, "/embeddings returned no vector", models)
            return _result(True, er.status_code, None, models)
        except httpx.HTTPError as e:
            return _result(False, 0, str(e), [])


async def check_reranker_slot_health(
    slot: RerankerSlotConfig, timeout: float = 5.0, deep: bool = True
) -> dict[str, Any]:
    """Health check for the reranker slot. Same shape as the embedding one;
    the deep probe POSTs a 1-query/1-document /rerank request (the de-facto
    format shared by oMLX/TEI/vLLM/Infinity — NOT an official OpenAI
    endpoint, so this may legitimately fail against a generic
    "openai_compatible" provider that doesn't implement it)."""
    if slot.provider == "local":
        return _result(True, 200, None, list(SUPPORTED_RERANKER_MODELS_LOCAL))

    endpoint = (slot.api_endpoint or "").rstrip("/")
    if not endpoint:
        return _result(False, 0, "api_endpoint is empty", [])
    key = resolve_api_key(slot)
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.get(f"{endpoint}/models", headers=headers)
            models = (
                [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
                if r.status_code == 200
                else []
            )
            if r.status_code != 200:
                return _result(False, r.status_code, r.text[:200], [])
            if not deep:
                return _result(True, r.status_code, None, models)
            body = {
                "model": slot.model,
                "query": "health check",
                "documents": ["ping"],
            }
            rr = await client.post(f"{endpoint}/rerank", json=body, headers=headers)
            if rr.status_code != 200:
                return _result(
                    False, rr.status_code,
                    f"/rerank failed (not all OpenAI-compatible providers implement this de-facto "
                    f"endpoint): {rr.text[:200]}",
                    models,
                )
            results = rr.json().get("results") or []
            if not results:
                return _result(False, rr.status_code, "/rerank returned no results", models)
            return _result(True, rr.status_code, None, models)
        except httpx.HTTPError as e:
            return _result(False, 0, str(e), [])
