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
"""
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from src.services import connection_registry
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

# Sprint 13 / Sprint 14: instruction appended to the system prompt when
# disable_thinking is on. Idempotent across turns (same constant every time,
# added only if not already present) → prefix-cache safe. Redundant with the
# top-level `think: false` body field for Ollama but still useful because:
# - API providers that don't accept `think:false` rely on this to know.
# - Acts as a safety net if any runtime doesn't fully honour the body field.
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
    disable_thinking: bool,
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

    if disable_thinking:
        messages = _apply_no_think(messages)

    body: dict[str, Any] = {
        "model": slot.model,
        "messages": messages,
        "temperature": slot.temperature,
        "max_tokens": slot.max_tokens,
        "stream": True,
    }
    if conn_type == "ollama" and slot.num_ctx:
        body["options"] = {"num_ctx": slot.num_ctx}
    if disable_thinking and conn_type == "ollama":
        # Ollama (≥0.7) honours a top-level `think: false` for ANY thinking
        # model it serves — qwen3, deepseek-r1, gemma3-think, whatever ships
        # next. No per-model detection needed, no per-model code paths.
        body["think"] = False

    has_system_hint = any(
        m.get("role") == "system" and _NO_THINK_SYSTEM_HINT in (m.get("content") or "")
        for m in messages
    )
    logger.info(
        f"LLM request → connection={conn.get('id')} ({conn_type}) model={slot.model} "
        f"num_ctx={slot.num_ctx} disable_thinking={disable_thinking} "
        f"body_think_false={body.get('think') is False} "
        f"sys_hint_injected={has_system_hint} n_messages={len(messages)}"
    )
    return f"{base}/chat/completions", headers, body


def _build_anthropic_request(
    conn: dict[str, Any],
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    disable_thinking: bool,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Native Anthropic Messages API. Hoists system messages to the top-level
    `system` param (required shape); force-fills `max_tokens` since Anthropic
    requires it. Fixes the pre-registry bug where the "api"/"anthropic" path
    sent an OpenAI-shaped body with Anthropic headers and never actually
    worked."""
    key = _resolve_openai_key(conn)  # same resolution logic regardless of flavor
    if disable_thinking:
        messages = _apply_no_think(messages)

    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            if m.get("content"):
                system_parts.append(m["content"])
            continue
        converted.append({"role": m["role"], "content": m.get("content") or ""})

    body: dict[str, Any] = {
        "model": slot.model,
        "messages": converted,
        "stream": True,
        "max_tokens": slot.max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS,
    }
    system = "\n\n".join(p for p in system_parts if p)
    if system:
        body["system"] = system
    if slot.temperature is not None:
        body["temperature"] = slot.temperature

    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    base = (conn.get("api_endpoint") or "").rstrip("/")
    logger.info(
        f"LLM request → connection={conn.get('id')} (anthropic) model={slot.model} "
        f"max_tokens={body['max_tokens']} disable_thinking={disable_thinking} "
        f"n_messages={len(converted)}"
    )
    return f"{base}/messages", headers, body


def _build_request(
    conn: dict[str, Any],
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    disable_thinking: bool,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    """Return (url, headers, body, dialect) where dialect selects the SSE
    parser — "openai" (choices[0].delta.content) or "anthropic"
    (content_block_delta / message_stop events)."""
    if conn.get("type") == "api" and conn.get("api_flavor") == "anthropic":
        url, headers, body = _build_anthropic_request(conn, slot, messages, disable_thinking)
        return url, headers, body, "anthropic"
    url, headers, body = _build_openai_request(conn, slot, messages, disable_thinking)
    return url, headers, body, "openai"


def _extract_token(dialect: str, chunk: dict[str, Any]) -> tuple[str | None, bool]:
    """Return (token_or_none, is_stream_end)."""
    if dialect == "anthropic":
        if chunk.get("type") == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text") or None, False
            return None, False
        if chunk.get("type") == "message_stop":
            return None, True
        return None, False
    # openai dialect
    delta = chunk.get("choices", [{}])[0].get("delta", {})
    return delta.get("content") or None, False


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
    disable_thinking: bool = False,
    cancel_check: CancelCheck = None,
) -> AsyncIterator[str]:
    """Stream tokens from one specific slot. Raises on HTTP / config errors.

    Empty response (0 tokens) is treated as a silent failure in the upper
    fallback layer — see lessons-learned #4 + HRDD's zero-token check.

    Sprint 13:
    - Wraps the chunk reader with INACTIVITY_TIMEOUT per chunk so a stalled
      stream aborts instead of hanging until the connection-level timeout.
    - Filters `<think>...</think>` from the streamed content when the caller
      asked for `disable_thinking` (state machine handles tags split across
      chunks).
    - Polls `cancel_check` between chunks so the polling loop can abort
      cooperatively when the user clicks Stop in the UI.
    """
    conn = connection_registry.connections.get(slot.connection_id)
    if not conn:
        raise ValueError(f"No connection configured (connection_id={slot.connection_id!r})")
    if not conn.get("enable", True):
        raise ValueError(f"Connection disabled: {conn['id']}")

    url, headers, body, dialect = _build_request(conn, slot, messages, disable_thinking)
    tokens_yielded = 0
    stripper = _ThinkStripper() if disable_thinking else None
    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
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
                token, is_end = _extract_token(dialect, chunk)
                if is_end:
                    break
                if not token:
                    continue
                if stripper is not None:
                    token = stripper.feed(token)
                    if not token:
                        continue
                tokens_yielded += 1
                yield token
    if stripper is not None:
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
) -> AsyncIterator[str]:
    """Top-level streamer the polling loop calls. Resolves the per-frontend
    LLM config, walks the fallback chain, and yields tokens from the first
    slot that produces any output.

    Failures bump the circuit breaker; subsequent calls skip open breakers
    until the cooldown elapses. A slot with no connection configured (e.g. a
    fresh `translation` slot before the admin points it anywhere) is skipped
    immediately, same as an open breaker.
    """
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
        try:
            produced = False
            async for token in stream_chat_one_slot(
                slot_cfg,
                messages,
                disable_thinking=cfg.disable_thinking,
                cancel_check=cancel_check,
            ):
                produced = True
                yield token
            if produced:
                _record_success(key)
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
) -> str:
    """Collect tokens into a single string. Used for summaries, translations, etc."""
    chunks: list[str] = []
    async for token in stream_chat(messages, slot=slot, frontend_id=frontend_id):
        chunks.append(token)
    return "".join(chunks)
