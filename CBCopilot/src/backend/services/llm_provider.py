"""OpenAI-compatible streaming LLM client with 3-slot config + fallback cascade.

Adapted from HRDDHelper/src/backend/services/llm_provider.py. CBC changes:
- 3 provider types (lm_studio / ollama / api) via Sprint 3 `llm_config_store`.
- Per-frontend override via Sprint 4B `llm_override_store.resolve_llm_config`.
- Daniel's fallback rule (D3, Sprint 6A): every slot's fallback chain is
  `[own, summariser, inference, compressor]` deduplicated. Rationale:
  summariser is the most capable slot in typical deployments, so it handles
  the main chat reasonably well if `inference` goes down.
- No multimodal — Sprint 5 already routes uploads through the RAG pipeline.
"""
import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.services.llm_config_store import LLMConfig, SlotConfig, SlotName
from src.services.llm_override_store import resolve_llm_config

logger = logging.getLogger("llm_provider")

# Circuit-breaker tuning (lessons-learned #4: 3 failures / 60 s → 300 s cooldown)
FAIL_WINDOW_SECONDS = 60
FAIL_THRESHOLD = 3
COOLDOWN_SECONDS = 300

STREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
SLOT_ORDER: tuple[SlotName, ...] = ("summariser", "inference", "compressor")


# --- Circuit breaker state ---

_fail_state: dict[str, dict[str, Any]] = {}


def _slot_key(provider: str, model: str, api_flavor: str | None = None, api_endpoint: str | None = None) -> str:
    """A unique string per (provider, model, flavor, endpoint) tuple for the
    circuit-breaker bookkeeping. Using endpoint too avoids confusing two
    different LM Studio instances."""
    return "|".join([provider or "", model or "", api_flavor or "", api_endpoint or ""])


def _record_success(key: str) -> None:
    entry = _fail_state.get(key)
    if entry:
        entry["failures"].clear()
        entry["open_until"] = 0.0


def _record_failure(key: str) -> None:
    entry = _fail_state.setdefault(key, {"failures": [], "open_until": 0.0})
    now = time.monotonic()
    entry["failures"] = [t for t in entry["failures"] if now - t < FAIL_WINDOW_SECONDS]
    entry["failures"].append(now)
    if len(entry["failures"]) >= FAIL_THRESHOLD:
        entry["open_until"] = now + COOLDOWN_SECONDS
        logger.warning(f"Circuit breaker OPEN for {key} (cooldown {COOLDOWN_SECONDS}s)")


def _is_open(key: str) -> bool:
    entry = _fail_state.get(key)
    if not entry:
        return False
    if entry["open_until"] > time.monotonic():
        return True
    if entry["open_until"]:
        entry["open_until"] = 0.0
        logger.info(f"Circuit breaker CLOSED for {key}")
    return False


# --- Fallback chain ---

def build_fallback_chain(cfg: LLMConfig, primary: SlotName) -> list[tuple[SlotName, SlotConfig]]:
    """Return the ordered list of (slot_name, SlotConfig) to try.

    Dedup rule: start with the primary, then walk SLOT_ORDER skipping
    duplicates. Example with `primary='inference'`:
        [inference, summariser, compressor] — inference first, summariser next
        (Daniel's preference: "summariser is more capable for chat").
    """
    chain: list[tuple[SlotName, SlotConfig]] = [(primary, getattr(cfg, primary))]
    for name in SLOT_ORDER:
        if name == primary:
            continue
        chain.append((name, getattr(cfg, name)))
    return chain


# --- HTTP body construction per provider ---

def _resolve_endpoint_and_headers(slot: SlotConfig) -> tuple[str, dict[str, str]]:
    """Return (base_url, headers) for the chat/completions call."""
    if slot.provider == "api":
        if not slot.api_endpoint:
            raise ValueError("api slot has no api_endpoint")
        if not slot.api_key_env:
            raise ValueError("api slot has no api_key_env")
        key = os.environ.get(slot.api_key_env)
        if not key:
            raise ValueError(f"env var {slot.api_key_env} not set in container")
        headers = {"Content-Type": "application/json"}
        if slot.api_flavor == "anthropic":
            # Anthropic's Messages API is NOT OpenAI-compatible — we'd need a
            # different body shape. For v1 we pretend it is and let the admin
            # pick openai_compatible if they're using a proxy. Real Anthropic
            # support can land with a dedicated client later.
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {key}"
        return slot.api_endpoint.rstrip("/"), headers
    # Local providers: OpenAI-compatible /v1
    if slot.provider == "lm_studio":
        return slot.endpoint.rstrip("/"), {"Content-Type": "application/json"}
    if slot.provider == "ollama":
        # Ollama's OpenAI shim lives at /v1
        base = slot.endpoint.rstrip("/")
        return (base if base.endswith("/v1") else f"{base}/v1"), {"Content-Type": "application/json"}
    raise ValueError(f"Unknown provider {slot.provider!r}")


def _build_body(slot: SlotConfig, messages: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": slot.model,
        "messages": messages,
        "temperature": slot.temperature,
        "max_tokens": slot.max_tokens,
        "stream": True,
    }
    if slot.provider == "ollama" and slot.num_ctx:
        body["options"] = {"num_ctx": slot.num_ctx}
    return body


# --- Streaming core ---

async def stream_chat_one_slot(
    slot: SlotConfig,
    messages: list[dict[str, Any]],
) -> AsyncIterator[str]:
    """Stream tokens from one specific slot. Raises on HTTP / config errors.

    Empty response (0 tokens) is treated as a silent failure in the upper
    fallback layer — see lessons-learned #4 + HRDD's zero-token check.
    """
    base, headers = _resolve_endpoint_and_headers(slot)
    body = _build_body(slot, messages)
    url = f"{base}/chat/completions"
    tokens_yielded = 0
    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        break
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content")
                if token:
                    tokens_yielded += 1
                    yield token
    if tokens_yielded == 0:
        raise RuntimeError(
            f"Zero tokens from {slot.provider}/{slot.model} "
            f"(likely model eviction, context overflow, or empty response)"
        )


async def stream_chat(
    messages: list[dict[str, Any]],
    slot: SlotName = "inference",
    frontend_id: str | None = None,
) -> AsyncIterator[str]:
    """Top-level streamer the polling loop calls. Resolves the per-frontend
    LLM config, walks the fallback chain, and yields tokens from the first
    slot that produces any output.

    Failures bump the circuit breaker; subsequent calls skip open breakers
    until the cooldown elapses.
    """
    cfg = resolve_llm_config(frontend_id)
    chain = build_fallback_chain(cfg, slot)
    last_error: Exception | None = None

    for slot_name, slot_cfg in chain:
        key = _slot_key(
            slot_cfg.provider,
            slot_cfg.model,
            slot_cfg.api_flavor,
            slot_cfg.api_endpoint,
        )
        if _is_open(key):
            logger.info(f"Skipping slot {slot_name} — breaker open for {key}")
            continue
        try:
            produced = False
            async for token in stream_chat_one_slot(slot_cfg, messages):
                produced = True
                yield token
            if produced:
                _record_success(key)
                return
            # No tokens — treat as failure and try next slot
            _record_failure(key)
            last_error = RuntimeError(f"{slot_name} produced no tokens")
            continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _record_failure(key)
            logger.warning(f"Slot {slot_name} ({slot_cfg.provider}/{slot_cfg.model}) failed: {e}")
            last_error = e
            continue

    # Exhausted the chain
    if last_error:
        raise last_error
    raise RuntimeError("No slot produced a response and no slot raised — check LLM config")


# --- Non-streaming convenience ---

async def chat(
    messages: list[dict[str, Any]],
    slot: SlotName = "inference",
    frontend_id: str | None = None,
) -> str:
    """Collect tokens into a single string. Used for summaries, etc."""
    chunks: list[str] = []
    async for token in stream_chat(messages, slot=slot, frontend_id=frontend_id):
        chunks.append(token)
    return "".join(chunks)
