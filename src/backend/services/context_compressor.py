"""Progressive-threshold context compression (SPEC §4.7).

When the conversation grows past `compression.first_threshold` tokens (and
again every `step_size` tokens after), the compressor LLM summarises the
older turns into one short system message that replaces them in-place.
Keeps the last `KEEP_RECENT` raw turns so the LLM always sees the actual
user/assistant volley for the current topic.

The transformation only happens on the outgoing LLM payload — the on-disk
conversation.jsonl stays complete for audit / future session recovery.

Sprint 6B: simple in-memory cache keyed by session_token. A restart of the
backend drops the cache, re-deriving it on the next turn. Persisting the
cache is Sprint 7+ work.

Token estimation: rough chars/4 heuristic. Good enough for "am I near the
threshold"; the underlying LLM has its own tokenizer for actual billing.
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from src.services.llm_config_store import load_config

logger = logging.getLogger("context_compressor")

KEEP_RECENT = 4          # always send the last N messages verbatim
CHARS_PER_TOKEN = 4      # crude estimator (OpenAI's actual ratio is ~4)
MIN_COMPRESSIBLE = 6     # don't bother compressing < 6 older messages


@dataclass
class _SessionCompressionState:
    """What we remember about a session's compression history."""
    summary_text: str = ""                    # running summary prefix (system msg)
    summarised_up_to: int = 0                 # index in session.messages covered by summary
    compressions_fired: int = 0               # how many times we've compressed (0, 1, 2, …)
    _last_error: str | None = field(default=None, repr=False)


_state: dict[str, _SessionCompressionState] = {}
_lock = threading.Lock()


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(len(m.get("content", "")) for m in messages) // CHARS_PER_TOKEN


def _get_state(token: str) -> _SessionCompressionState:
    with _lock:
        if token not in _state:
            _state[token] = _SessionCompressionState()
        return _state[token]


def should_compress(messages: list[dict[str, Any]], frontend_id: str | None = None) -> bool:
    """True when the conversation has crossed the next compression threshold.

    Threshold schedule: first fires at `first_threshold`, then every
    `step_size` tokens after — matching SPEC §4.7's progressive thresholds.
    """
    try:
        cfg = load_config()
    except Exception:
        return False
    comp = cfg.compression
    if not comp.enabled:
        return False
    tokens = _estimate_tokens(messages)
    return tokens >= comp.first_threshold


async def compress_if_needed(
    session_token: str,
    messages: list[dict[str, Any]],
    frontend_id: str | None = None,
) -> list[dict[str, Any]]:
    """The function polling.py calls before the LLM call. Returns either the
    original `messages` unchanged, or a shorter list where the older prefix
    has been replaced by a single summary system message.

    Runs the compressor slot (`llm_provider.stream_chat(..., slot='compressor')`)
    — configurable per-frontend via Sprint 4B's LLM override.
    """
    try:
        cfg = load_config()
    except Exception as e:
        logger.warning(f"Compressor disabled — failed to load LLM config: {e}")
        return messages
    if not cfg.compression.enabled:
        return messages

    total_tokens = _estimate_tokens(messages)
    state = _get_state(session_token)

    # Work out the target firing point: first_threshold + step_size * N
    # where N is how many times we've already compressed.
    threshold = cfg.compression.first_threshold + cfg.compression.step_size * state.compressions_fired
    if total_tokens < threshold:
        return messages

    # Separate system prompt (always first) from the conversation tail.
    system_msg: dict[str, Any] | None = None
    convo = list(messages)
    if convo and convo[0].get("role") == "system":
        system_msg = convo.pop(0)

    if len(convo) <= KEEP_RECENT + MIN_COMPRESSIBLE:
        # Not enough to chew on — bump threshold so we don't thrash.
        return messages

    to_summarise = convo[:-KEEP_RECENT]
    keep_tail = convo[-KEEP_RECENT:]

    # Fold in any existing running summary so we don't lose history
    preamble = f"Earlier summary so far:\n{state.summary_text}\n\n" if state.summary_text else ""
    transcript = "\n\n".join(
        f"### {'User' if m.get('role') == 'user' else 'Assistant'}\n{m.get('content', '')}"
        for m in to_summarise
    )

    summary_prompt = [
        {
            "role": "system",
            "content": (
                "You compress a chat conversation. Produce a tight, factual summary "
                "of the exchanges below that preserves: (1) what the user is researching, "
                "(2) specific CBA clauses or figures that came up, (3) decisions or "
                "direction the user indicated. No preamble. No editorial comment."
            ),
        },
        {
            "role": "user",
            "content": preamble + transcript,
        },
    ]

    # Lazy-import to avoid circular (llm_provider -> ... -> context_compressor)
    from src.services import llm_provider
    try:
        summary = await llm_provider.chat(summary_prompt, slot="compressor", frontend_id=frontend_id)
    except Exception as e:
        logger.warning(f"[{session_token}] compressor LLM failed — skipping this round: {e}")
        state._last_error = str(e)
        return messages

    summary = summary.strip()
    if not summary:
        logger.warning(f"[{session_token}] compressor returned empty; skipping")
        return messages

    with _lock:
        state.summary_text = summary
        state.summarised_up_to += len(to_summarise)
        state.compressions_fired += 1

    compressed: list[dict[str, Any]] = []
    if system_msg:
        compressed.append(system_msg)
    compressed.append({
        "role": "system",
        "content": f"Summary of earlier conversation (turns 1-{state.summarised_up_to}):\n\n{summary}",
    })
    compressed.extend(keep_tail)

    logger.info(
        f"[{session_token}] context compressed: {total_tokens} → ~"
        f"{_estimate_tokens(compressed)} tokens (kept last {KEEP_RECENT} turns, "
        f"compressions_fired={state.compressions_fired})"
    )
    return compressed


def forget_session(session_token: str) -> None:
    """Drop the compression state — called when a session is destroyed."""
    with _lock:
        _state.pop(session_token, None)
