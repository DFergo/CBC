"""Context compressor — Sprint 6A stub.

SPEC §4.7's `compression` block (enabled / first_threshold / step_size) will
drive this: when the assembled conversation exceeds a token threshold, the
compressor slot summarises older turns into a short block that replaces
them. This keeps long conversations within the LLM's context window without
silently dropping turns (lessons-learned §10).

This module is intentionally empty in 6A — polling.py doesn't call it yet.
6B will implement:
- `should_compress(messages, cfg) -> bool` using progressive thresholds
- `compress(messages, slot, frontend_id) -> messages` via llm_provider.chat
- Wiring into session_store: replace the compressed prefix with a single
  "summary" system message at the top of the history.

Leaving the module in place so the Sprint 6A import graph is stable — 6B
just fills in the body.
"""
from typing import Any


def should_compress(messages: list[dict[str, Any]]) -> bool:  # noqa: ARG001 — stub
    """Sprint 6B will read `compression.{enabled,first_threshold,step_size}`
    from the resolved LLM config and decide. Stub: always False."""
    return False


async def compress(messages: list[dict[str, Any]], frontend_id: str | None = None) -> list[dict[str, Any]]:  # noqa: ARG001
    """Sprint 6B: call the compressor slot with a summarise-older-turns
    prompt, replace the compressed prefix with a single system message.
    Stub: return input unchanged."""
    return messages
