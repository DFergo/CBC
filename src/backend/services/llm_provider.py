"""Streaming LLM client with 4-slot config + connection registry + fallback cascade.

Adapted from HRDDHelper/src/backend/services/llm_provider.py. CBC changes:
- Slots reference a named connection from connection_registry.py instead of
  embedding their own provider/endpoint/api_key (Sprint-N LLM provider
  registry port). Two protocol dialects: "openai" (OpenAI-compatible chat
  completions — lm_studio, ollama via its /v1 shim, and api/openai(_compatible))
  and "anthropic" (native Messages API — api/anthropic). The anthropic dialect
  fixes a bug where CBC previously sent an OpenAI-shaped body with Anthropic
  headers, which never actually worked against the real Anthropic API.
- Daniel's fallback rule (D3, Sprint 6A): every slot's fallback chain is
  `[own, summariser, inference, compressor]` deduplicated. Rationale:
  summariser is the most capable slot in typical deployments, so it handles
  the main chat reasonably well if `inference` goes down. `translation` falls
  back into that same chain but is never itself a fallback target.
- No multimodal — Sprint 5 already routes uploads through the RAG pipeline.
- Sprint 13: per-chunk inactivity timeout, think-mode suppression, <think>
  tag stripping in the streamed output. Cooperative cancel via `cancel_check`.
- Sprint 22 (port of HRDD Sprint 37): request fields per provider/model from
  llm_capabilities.py (per-slot reasoning control replaces the global
  disable_thinking hint), drop-and-retry-once for rejected optional fields,
  block-format response content (Mistral reasoning models), token + prompt
  cache usage per session/slot (llm_usage.py), Anthropic cache breakpoints.
"""
import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from src.services import connection_registry, llm_capabilities as caps
from src.services.llm_config_store import LLMConfig, SlotConfig, SlotName, resolve_api_key
from src.services.llm_override_store import resolve_llm_config

logger = logging.getLogger("llm_provider")

# Circuit-breaker tuning (lessons-learned #4: 3 failures / 60 s → 300 s cooldown)
FAIL_WINDOW_SECONDS = 60
FAIL_THRESHOLD = 3
COOLDOWN_SECONDS = 300

STREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
# Sprint 13: per-chunk inactivity timeout. The connection-level STREAM_TIMEOUT
# above doesn't catch a model that "drips" tokens or stalls mid-stream — every
# new chunk resets it. This is the gap-between-chunks budget; if a runtime
# stops emitting for this long we abort the slot and let the fallback chain
# try the next one (or surface an error).
INACTIVITY_TIMEOUT = 60.0

# Anthropic requires max_tokens; used when a slot leaves it blank/zero.
_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
_ANTHROPIC_VERSION = "2023-06-01"

# Sprint 13 / Sprint 22: instruction appended to the system prompt when a slot's
# reasoning is "off" on a generic OpenAI-compatible server (LM Studio, vLLM…),
# as a safety net next to `chat_template_kwargs.enable_thinking=false`, which
# not every server honours. Idempotent across turns (same constant, added once)
# → prefix-cache safe. API providers get their real reasoning field instead.
_NO_THINK_SYSTEM_HINT = (
    "Respond directly without any reasoning prelude. "
    "Do not output <think>, </think>, or any chain-of-thought tokens."
)

SLOT_ORDER: tuple[SlotName, ...] = ("summariser", "inference", "compressor")


# --- Circuit breaker state ---

_fail_state: dict[str, dict[str, Any]] = {}


def _slot_key(connection_id: str, model: str) -> str:
    """A unique string per (connection, model) pair for circuit-breaker
    bookkeeping."""
    return f"{connection_id or ''}|{model or ''}"


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
    `translation` is never itself a fallback target for another primary slot —
    it only appears when it IS the primary (branding auto-translate).
    """
    chain: list[tuple[SlotName, SlotConfig]] = [(primary, getattr(cfg, primary))]
    for name in SLOT_ORDER:
        if name == primary:
            continue
        chain.append((name, getattr(cfg, name)))
    return chain


# --- Request construction per connection dialect ---


def _apply_no_think(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject the "respond directly" system-prompt hint into the messages.
    Returns a NEW list (no mutation of the caller's data).

    Idempotent: the hint is added ONLY if not already present in the first
    system message, so calling this on every turn produces identical output
    for identical input → prefix cache friendly.
    """
    out: list[dict[str, Any]] = []
    system_amended = False
    for m in messages:
        new = dict(m)
        if not system_amended and m.get("role") == "system":
            existing = (new.get("content") or "").rstrip()
            if _NO_THINK_SYSTEM_HINT not in existing:
                new["content"] = (
                    f"{existing}\n\n{_NO_THINK_SYSTEM_HINT}" if existing else _NO_THINK_SYSTEM_HINT
                )
            system_amended = True
        out.append(new)
    if not system_amended:
        out.insert(0, {"role": "system", "content": _NO_THINK_SYSTEM_HINT})
    return out


def _content_text(content: Any) -> str:
    """Visible text of a response ``content`` field, string or block list.

    Reasoning models on the Mistral API send ``content`` as a list of blocks
    (``[{"type": "thinking", ...}, {"type": "text", "text": "..."}]``), in both
    ``message.content`` and streaming ``delta.content``. Only ``text`` blocks
    are user-visible; ``thinking`` blocks are dropped.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _openai_usage(u: dict[str, Any]) -> dict[str, int]:
    """Normalise an OpenAI-style ``usage`` object (Mistral, OpenRouter, OpenAI, vLLM, Ollama shim)."""
    details = u.get("prompt_tokens_details") or {}
    comp = u.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "cached_tokens": int(details.get("cached_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "reasoning_tokens": int(comp.get("reasoning_tokens") or 0),
    }


def _cache_key(session: str | None) -> str | None:
    """Provider prompt-cache key for a session: a hash, never the session token
    (the token is a recovery credential and must not leave the backend)."""
    if not session:
        return None
    return hashlib.sha256(f"cbc-cache:{session}".encode()).hexdigest()[:32]


def _resolve_openai_key(conn: dict[str, Any]) -> str:
    key = resolve_api_key(conn)
    if key:
        return key
    inline_set = bool((conn.get("api_key") or "").strip())
    env_name = (conn.get("api_key_env") or "").strip()
    if inline_set:
        raise ValueError("api_key is empty — paste it in the admin connection")
    if env_name:
        raise ValueError(f"env var {env_name} not set in container")
    raise ValueError("api connection has neither api_key nor api_key_env")


def _build_openai_request(
    conn: dict[str, Any],
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    cache_key: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """OpenAI-compatible chat completions. Covers lm_studio, ollama (via its
    /v1 shim), and api connections with flavor openai/openai_compatible."""
    conn_type = conn.get("type")
    if conn_type == "lm_studio":
        base = (conn.get("endpoint") or "").rstrip("/")
        headers = {"Content-Type": "application/json"}
    elif conn_type == "ollama":
        base = (conn.get("endpoint") or "").rstrip("/")
        base = base if base.endswith("/v1") else f"{base}/v1"
        headers = {"Content-Type": "application/json"}
    elif conn_type == "api":
        key = _resolve_openai_key(conn)
        base = (conn.get("api_endpoint") or "").rstrip("/")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    else:
        raise ValueError(f"Unknown connection type {conn_type!r}")

    kind = caps.provider_kind(conn)
    if slot.reasoning == "off" and kind == "openai_compatible":
        messages = _apply_no_think(messages)

    body: dict[str, Any] = {"model": slot.model, "messages": messages, "stream": True}
    # temperature / max_tokens / reasoning / num_ctx (Ollama) / stream_options /
    # cache key / OpenRouter routing — per provider rules. Ollama (≥0.7) honours
    # a top-level `think` on its /v1 shim for any thinking model it serves.
    body.update(caps.openai_body_extras(
        conn, slot.model, slot.temperature, slot.max_tokens, slot.reasoning, cache_key, slot.num_ctx,
    ))
    logger.info(
        f"LLM request → connection={conn.get('id')} ({conn_type}/{kind}) model={slot.model} "
        f"reasoning={slot.reasoning} fields={sorted(k for k in body if k not in ('model', 'messages'))} "
        f"n_messages={len(messages)}"
    )
    return f"{base}/chat/completions", headers, body


def _build_anthropic_request(
    conn: dict[str, Any],
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    cache_key: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Native Anthropic Messages API. Hoists system messages to the top-level
    `system` param (required shape); force-fills `max_tokens` since Anthropic
    requires it. Fixes the pre-registry bug where the "api"/"anthropic" path
    sent an OpenAI-shaped body with Anthropic headers and never actually
    worked."""
    key = _resolve_openai_key(conn)  # same resolution logic regardless of flavor

    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            if m.get("content"):
                system_parts.append(m["content"])
            continue
        # Block list so cache_control can be attached.
        converted.append({"role": m["role"], "content": [{"type": "text", "text": m.get("content") or ""}]})

    body: dict[str, Any] = {
        "model": slot.model,
        "messages": converted,
        "stream": True,
        "max_tokens": slot.max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS,
    }
    # Prompt caching: breakpoints on the system prompt and the last-but-one
    # message, so the stable prefix is cached turn after turn.
    system = "\n\n".join(p for p in system_parts if p)
    if system:
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if len(converted) >= 2:
        converted[-2]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    extras, _ = caps.reasoning_mapping("anthropic", slot.model, slot.reasoning)
    if extras:
        body.update(extras)
        body["max_tokens"] = max(body["max_tokens"], extras["thinking"]["budget_tokens"] + 1024)
    elif slot.temperature is not None:
        body["temperature"] = slot.temperature  # not allowed together with thinking

    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    base = (conn.get("api_endpoint") or "").rstrip("/")
    logger.info(
        f"LLM request → connection={conn.get('id')} (anthropic) model={slot.model} "
        f"max_tokens={body['max_tokens']} reasoning={slot.reasoning} "
        f"n_messages={len(converted)}"
    )
    return f"{base}/messages", headers, body


def _build_request(
    conn: dict[str, Any],
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    cache_key: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    """Return (url, headers, body, dialect) where dialect selects the SSE
    parser — "openai" (choices[0].delta.content) or "anthropic"
    (content_block_delta / message_stop events)."""
    if conn.get("type") == "api" and conn.get("api_flavor") == "anthropic":
        url, headers, body = _build_anthropic_request(conn, slot, messages, cache_key)
        return url, headers, body, "anthropic"
    url, headers, body = _build_openai_request(conn, slot, messages, cache_key)
    return url, headers, body, "openai"


def _extract_token(
    dialect: str, chunk: dict[str, Any], usage: dict[str, int] | None = None,
) -> tuple[str | None, bool]:
    """Return (token_or_none, is_stream_end). Fills ``usage`` when the chunk
    carries token counts (OpenAI-style final chunk, Anthropic message events)."""
    if dialect == "anthropic":
        ctype = chunk.get("type")
        if ctype == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text") or None, False
            return None, False
        if ctype == "message_start" and usage is not None:
            u = (chunk.get("message") or {}).get("usage") or {}
            cached = int(u.get("cache_read_input_tokens") or 0)
            usage.update({
                "prompt_tokens": int(u.get("input_tokens") or 0) + cached
                                 + int(u.get("cache_creation_input_tokens") or 0),
                "cached_tokens": cached,
            })
        elif ctype == "message_delta" and usage is not None:
            out = (chunk.get("usage") or {}).get("output_tokens")
            if out is not None:
                usage["completion_tokens"] = int(out)
        if ctype == "message_stop":
            return None, True
        return None, False
    # openai dialect (content may be a string or, on Mistral reasoning
    # models, a list of thinking/text blocks — B.1)
    if usage is not None and chunk.get("usage"):
        usage.update(_openai_usage(chunk["usage"]))
    choices = chunk.get("choices") or [{}]
    delta = choices[0].get("delta") or {}
    return _content_text(delta.get("content")) or None, False


# --- <think> tag stripping (Sprint 13) ---

# Streaming-safe state machine: tokens may split tags across boundaries
# (e.g. "<th" arrives in one chunk, "ink>" in the next). We keep an internal
# buffer of an "ambiguous prefix" until we know whether we're inside a think
# block or whether the buffered text is real content.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_THINK_MAX_TAG_LEN = max(len(_THINK_OPEN), len(_THINK_CLOSE))


class _ThinkStripper:
    """Stateful filter applied to streamed text. Yields content with all
    `<think>...</think>` blocks removed. Tolerant of tags split across chunks
    and of unmatched opens/closes (treated as best-effort suppression)."""

    def __init__(self) -> None:
        self.in_think = False
        self.buffer = ""

    def feed(self, chunk: str, *, last: bool = False) -> str:
        """Process one streamed chunk, return whatever should be emitted now.
        Pass last=True after the stream ends to flush the carryover buffer."""
        text = self.buffer + chunk
        self.buffer = ""
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if self.in_think:
                close_idx = text.find(_THINK_CLOSE, i)
                if close_idx == -1:
                    if last:
                        return "".join(out)
                    keep = min(_THINK_MAX_TAG_LEN - 1, n - i)
                    self.buffer = text[n - keep:]
                    return "".join(out)
                i = close_idx + len(_THINK_CLOSE)
                self.in_think = False
                continue
            open_idx = text.find(_THINK_OPEN, i)
            if open_idx == -1:
                if last:
                    out.append(text[i:])
                    return "".join(out)
                keep = min(_THINK_MAX_TAG_LEN - 1, n - i)
                if keep > 0:
                    self.buffer = text[n - keep:]
                    out.append(text[i:n - keep])
                else:
                    out.append(text[i:])
                return "".join(out)
            if open_idx > i:
                out.append(text[i:open_idx])
            i = open_idx + len(_THINK_OPEN)
            self.in_think = True
        return "".join(out)


# --- Streaming core ---

CancelCheck = Callable[[], Awaitable[bool]] | Callable[[], bool] | None


async def _cancel_requested(check: CancelCheck) -> bool:
    """Run the cancel-check callback; tolerate sync or async."""
    if check is None:
        return False
    res = check()
    if asyncio.iscoroutine(res):
        res = await res
    return bool(res)


async def stream_chat_one_slot(
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    *,
    cancel_check: CancelCheck = None,
    cache_key: str | None = None,
    usage: dict[str, int] | None = None,
) -> AsyncIterator[str]:
    """Stream tokens from one specific slot. Raises on HTTP / config errors.

    Empty response (0 tokens) is treated as a silent failure in the upper
    fallback layer — see lessons-learned #4 + HRDD's zero-token check.

    Sprint 13:
    - Wraps the chunk reader with INACTIVITY_TIMEOUT per chunk so a stalled
      stream aborts instead of hanging until the connection-level timeout.
    - Filters `<think>...</think>` from the streamed content (state machine
      handles tags split across chunks). Always on since Sprint 22: reasoning
      is now per slot and may be enabled.
    - Polls `cancel_check` between chunks so the polling loop can abort
      cooperatively when the user clicks Stop in the UI.
    """
    conn = connection_registry.connections.get(slot.connection_id)
    if not conn:
        raise ValueError(f"No connection configured (connection_id={slot.connection_id!r})")
    if not conn.get("enable", True):
        raise ValueError(f"Connection disabled: {conn['id']}")

    url, headers, body, dialect = _build_request(conn, slot, messages, cache_key)
    tokens_yielded = 0
    stripper = _ThinkStripper()
    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
        for attempt in (1, 2):
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code in (400, 422) and attempt == 1:
                    text = (await resp.aread()).decode(errors="replace")
                    dropped = caps.rejected_optional_fields(text, body)
                    if dropped:
                        logger.warning(f"{conn.get('id')}/{slot.model} rejected {dropped}; retrying without them")
                        for f in dropped:
                            body.pop(f, None)
                        continue
                    raise httpx.HTTPStatusError(f"{resp.status_code} from {url}: {text[:300]}",
                                                request=resp.request, response=resp)
                resp.raise_for_status()
                line_iter = resp.aiter_lines().__aiter__()
                while True:
                    if await _cancel_requested(cancel_check):
                        raise asyncio.CancelledError()
                    try:
                        line = await asyncio.wait_for(
                            line_iter.__anext__(),
                            timeout=INACTIVITY_TIMEOUT,
                        )
                    except asyncio.TimeoutError as e:
                        raise RuntimeError(
                            f"LLM inactivity timeout ({INACTIVITY_TIMEOUT:.0f}s) on "
                            f"{conn.get('id')}/{slot.model}"
                        ) from e
                    except StopAsyncIteration:
                        break
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
                    token, is_end = _extract_token(dialect, chunk, usage)
                    if is_end:
                        break
                    if not token:
                        continue
                    token = stripper.feed(token)
                    if not token:
                        continue
                    tokens_yielded += 1
                    yield token
            break
    tail = stripper.feed("", last=True)
    if tail:
        tokens_yielded += 1
        yield tail
    if tokens_yielded == 0:
        raise RuntimeError(
            f"Zero tokens from {conn.get('id')}/{slot.model} "
            f"(likely model eviction, context overflow, or empty response)"
        )


async def stream_chat(
    messages: list[dict[str, Any]],
    slot: SlotName = "inference",
    frontend_id: str | None = None,
    *,
    cancel_check: CancelCheck = None,
    session: str | None = None,
) -> AsyncIterator[str]:
    """Top-level streamer the polling loop calls. Resolves the per-frontend
    LLM config, walks the fallback chain, and yields tokens from the first
    slot that produces any output.

    Failures bump the circuit breaker; subsequent calls skip open breakers
    until the cooldown elapses. A slot with no connection configured (e.g. a
    fresh `translation` slot before the admin points it anywhere) is skipped
    immediately, same as an open breaker.

    ``session`` attributes token/cache usage (llm_usage) and derives the
    provider cache key (a hash, never the session token itself).
    """
    from src.services import llm_usage

    cfg = resolve_llm_config(frontend_id)
    chain = build_fallback_chain(cfg, slot)
    last_error: Exception | None = None

    for slot_name, slot_cfg in chain:
        if not slot_cfg.connection_id:
            logger.info(f"Skipping slot {slot_name} — no connection configured")
            continue
        key = _slot_key(slot_cfg.connection_id, slot_cfg.model)
        if _is_open(key):
            logger.info(f"Skipping slot {slot_name} — breaker open for {key}")
            continue
        usage: dict[str, int] = {}
        try:
            produced = False
            async for token in stream_chat_one_slot(
                slot_cfg,
                messages,
                cancel_check=cancel_check,
                cache_key=_cache_key(session),
                usage=usage,
            ):
                produced = True
                yield token
            if produced:
                _record_success(key)
                llm_usage.record(session, slot_name, slot_cfg.connection_id, slot_cfg.model, usage)
                return
            _record_failure(key)
            last_error = RuntimeError(f"{slot_name} produced no tokens")
            continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _record_failure(key)
            logger.warning(f"Slot {slot_name} ({slot_cfg.connection_id}/{slot_cfg.model}) failed: {e}")
            last_error = e
            continue

    if last_error:
        raise last_error
    raise RuntimeError("No slot produced a response and no slot raised — check LLM config")


# --- Non-streaming convenience ---

async def chat(
    messages: list[dict[str, Any]],
    slot: SlotName = "inference",
    frontend_id: str | None = None,
    session: str | None = None,
) -> str:
    """Collect tokens into a single string. Used for summaries, translations, etc."""
    chunks: list[str] = []
    async for token in stream_chat(messages, slot=slot, frontend_id=frontend_id, session=session):
        chunks.append(token)
    return "".join(chunks)


# --- Model metadata (admin capability view) ---

_model_info_cache: dict[str, dict[str, Any]] = {}


async def model_info(connection_id: str, model: str) -> dict[str, Any]:
    """Provider-declared metadata for a model: ``context_length`` (OpenRouter
    ``context_length``, Mistral/LM Studio ``max_context_length``, Ollama
    ``<arch>.context_length``) and OpenRouter's ``supported_parameters``.
    Never raises; cached per (connection, model) for the process lifetime."""
    conn = connection_registry.connections.get(connection_id)
    if not conn or not model:
        return {}
    key = f"{connection_id}|{model}"
    if key in _model_info_cache:
        return _model_info_cache[key]
    info: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            ctype = conn.get("type")
            if ctype == "ollama":
                base = (conn.get("endpoint") or "").rstrip("/").removesuffix("/v1")
                r = await client.post(f"{base}/api/show", json={"model": model})
                r.raise_for_status()
                for k, v in (r.json().get("model_info") or {}).items():
                    if k.endswith(".context_length") and v:
                        info = {"context_length": int(v)}
            elif not (ctype == "api" and conn.get("api_flavor") == "anthropic"):
                if ctype == "api":
                    base = (conn.get("api_endpoint") or "").rstrip("/")
                    headers = {"Authorization": f"Bearer {_resolve_openai_key(conn)}"}
                else:
                    base, headers = (conn.get("endpoint") or "").rstrip("/"), {}
                r = await client.get(f"{base}/models", headers=headers)
                r.raise_for_status()
                for m in r.json().get("data", []):
                    if m.get("id") == model:
                        val = m.get("context_length") or m.get("max_context_length")
                        info = {"context_length": int(val) if val else None,
                                "supported_parameters": m.get("supported_parameters")}
    except Exception as e:
        logger.debug(f"model_info({connection_id}, {model}) unavailable: {e}")
    _model_info_cache[key] = info
    return info
