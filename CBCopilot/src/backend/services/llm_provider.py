"""OpenAI-compatible streaming LLM client with 3-slot config + fallback cascade.

Adapted from HRDDHelper/src/backend/services/llm_provider.py. CBC changes:
- 3 provider types (lm_studio / ollama / api) via Sprint 3 `llm_config_store`.
- Per-frontend override via Sprint 4B `llm_override_store.resolve_llm_config`.
- Daniel's fallback rule (D3, Sprint 6A): every slot's fallback chain is
  `[own, summariser, inference, compressor]` deduplicated. Rationale:
  summariser is the most capable slot in typical deployments, so it handles
  the main chat reasonably well if `inference` goes down.
- No multimodal — Sprint 5 already routes uploads through the RAG pipeline.
- Sprint 13: per-chunk inactivity timeout, think-mode suppression, <think>
  tag stripping in the streamed output. Cooperative cancel via `cancel_check`.
"""
import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
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
# Sprint 13: per-chunk inactivity timeout. The connection-level STREAM_TIMEOUT
# above doesn't catch a model that "drips" tokens or stalls mid-stream — every
# new chunk resets it. This is the gap-between-chunks budget; if a runtime
# stops emitting for this long we abort the slot and let the fallback chain
# try the next one (or surface an error).
INACTIVITY_TIMEOUT = 60.0

# Sprint 13 / Sprint 14: instruction appended to the system prompt when
# disable_thinking is on. Idempotent across turns (same constant every time,
# added only if not already present) → prefix-cache safe. Redundant with the
# top-level `think: false` body field for Ollama but still useful because:
# - API providers that don't accept `think:false` rely on this to know.
# - Acts as a safety net if any runtime doesn't fully honour the body field.
#
# The `/no_think` suffix on user messages (qwen3-specific convention) was
# removed in Sprint 14 follow-up. Its placement-on-last-user-only broke Ollama
# prefix caching (turn N saw "¿foo? /no_think"; turn N+1 saw "¿foo?" because
# the suffix had moved to the new last user) and triggered full re-prefill on
# every re-question, turning ~10 s follow-ups into 40-60 s. For Ollama the
# body field is the source of truth; for LM Studio the admin configures no-
# thinking in the runtime GUI instead.
_NO_THINK_SYSTEM_HINT = (
    "Respond directly without any reasoning prelude. "
    "Do not output <think>, </think>, or any chain-of-thought tokens."
)

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
        # Sprint 19 Fase 1 — resolve via inline api_key (admin paste) first,
        # then env var. Either path produces the same usable key string.
        from src.services.llm_config_store import resolve_api_key
        key = resolve_api_key(slot)
        if not key:
            inline_set = bool((slot.api_key or "").strip())
            env_name = (slot.api_key_env or "").strip()
            if inline_set:
                raise ValueError("api_key is empty — paste it in the admin slot")
            if env_name:
                raise ValueError(f"env var {env_name} not set in container")
            raise ValueError("api slot has neither api_key nor api_key_env")
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


def _apply_no_think(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject the "respond directly" system-prompt hint into the messages.
    Returns a NEW list (no mutation of the caller's data).

    Idempotent: the hint is added ONLY if not already present in the first
    system message, so calling this on every turn produces identical output
    for identical input → prefix cache friendly.

    Ollama gets the authoritative switch via `"think": false` in the body
    (see `_build_body`). This hint is the cross-provider fallback plus a
    belt-and-braces safety net. LM Studio users configure no-thinking in
    the LM Studio GUI directly — they don't rely on this hint.
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
    # If the conversation started without any system message, prepend one
    # carrying the hint so the model still sees it.
    if not system_amended:
        out.insert(0, {"role": "system", "content": _NO_THINK_SYSTEM_HINT})
    return out


def _build_body(
    slot: SlotConfig,
    messages: list[dict[str, Any]],
    disable_thinking: bool = False,
) -> dict[str, Any]:
    if disable_thinking:
        messages = _apply_no_think(messages)

    body: dict[str, Any] = {
        "model": slot.model,
        "messages": messages,
        "temperature": slot.temperature,
        "max_tokens": slot.max_tokens,
        "stream": True,
    }
    if slot.provider == "ollama" and slot.num_ctx:
        body["options"] = {"num_ctx": slot.num_ctx}
    if disable_thinking and slot.provider == "ollama":
        # Ollama (≥0.7) honours a top-level `think: false` for ANY thinking
        # model it serves — qwen3, deepseek-r1, gemma3-think, whatever ships
        # next. No per-model detection needed, no per-model code paths.
        # This is the authoritative switch for the Ollama path; the system
        # prompt hint in messages is a belt-and-braces redundancy.
        #
        # LM Studio users configure no-thinking in the LM Studio GUI; CBC
        # does not send a suffix/trick for that path (was Sprint 13 but got
        # removed in Sprint 14 follow-up because the last-user placement of
        # `/no_think` shifted between turns and broke Ollama prefix cache,
        # turning re-question TTFT from ~10 s to ~45 s).
        body["think"] = False

    # Diagnostic log: one INFO per outgoing request so admin can verify in
    # OrbStack container logs what the pipeline is actually sending. Captures
    # the disable_thinking-relevant fields + context size. Privacy: no
    # message content in the log.
    has_system_hint = any(
        m.get("role") == "system" and _NO_THINK_SYSTEM_HINT in (m.get("content") or "")
        for m in messages
    )
    logger.info(
        f"LLM request → provider={slot.provider} model={slot.model} "
        f"num_ctx={slot.num_ctx} "
        f"disable_thinking={disable_thinking} "
        f"body_think_false={body.get('think') is False} "
        f"sys_hint_injected={has_system_hint} "
        f"n_messages={len(messages)}"
    )
    return body


# --- <think> tag stripping (Sprint 13) ---

# Streaming-safe state machine: tokens may split tags across boundaries
# (e.g. "<th" arrives in one chunk, "ink>" in the next). We keep an internal
# buffer of an "ambiguous prefix" until we know whether we're inside a think
# block or whether the buffered text is real content.
#
# Approach: a small carryover buffer holds at most len("</think>") - 1
# characters from the tail of each chunk. The longest tag literal we need to
# match is "</think>" (8 chars), so 7 chars of carryover guarantee we never
# miss a tag straddling two chunks.

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
                # Looking for closing tag.
                close_idx = text.find(_THINK_CLOSE, i)
                if close_idx == -1:
                    # Hold on to the tail (might be a partial close tag).
                    if last:
                        # Stream ended mid-think: drop everything we held.
                        return "".join(out)
                    keep = min(_THINK_MAX_TAG_LEN - 1, n - i)
                    self.buffer = text[n - keep:]
                    return "".join(out)
                # Skip past the closing tag.
                i = close_idx + len(_THINK_CLOSE)
                self.in_think = False
                continue
            # Looking for opening tag — emit literal text up to the next tag.
            open_idx = text.find(_THINK_OPEN, i)
            if open_idx == -1:
                # No open tag — but the tail might be the start of one.
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
            # Emit text up to the open tag, then enter think mode.
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
    base, headers = _resolve_endpoint_and_headers(slot)
    body = _build_body(slot, messages, disable_thinking=disable_thinking)
    url = f"{base}/chat/completions"
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
                        f"{slot.provider}/{slot.model}"
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
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content")
                if not token:
                    continue
                if stripper is not None:
                    token = stripper.feed(token)
                    if not token:
                        continue
                tokens_yielded += 1
                yield token
    # Flush any tail content the stripper held onto. If the model never closed
    # a `<think>` block, the held content is dropped (best-effort suppression).
    if stripper is not None:
        tail = stripper.feed("", last=True)
        if tail:
            tokens_yielded += 1
            yield tail
    if tokens_yielded == 0:
        raise RuntimeError(
            f"Zero tokens from {slot.provider}/{slot.model} "
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
    until the cooldown elapses.

    Sprint 13: forwards `cancel_check` to the slot streamer; honours the
    config-level `disable_thinking` flag.
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
