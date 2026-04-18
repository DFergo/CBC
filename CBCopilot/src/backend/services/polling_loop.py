"""Minimal health-check polling.

Sprint 4A: just hit `/internal/health` on each enabled frontend and update its
status (online / offline). Full message-queue polling — dequeueing user
messages, dispatching to LLM, streaming responses — lands in Sprint 6.

Runs as an asyncio task kicked off from main.py's lifespan.
"""
import asyncio
import logging

import httpx

from src.services.frontend_registry import registry

logger = logging.getLogger("polling")

POLL_INTERVAL_SECONDS = 5
HEALTH_TIMEOUT = 3.0


async def _check_one(url: str) -> str:
    """Return "online" if the sidecar /internal/health responds 200, else "offline"."""
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
            r = await client.get(f"{url.rstrip('/')}/internal/health")
            return "online" if r.status_code == 200 else "offline"
    except httpx.HTTPError:
        return "offline"


async def polling_loop() -> None:
    """Background task: health-check every enabled frontend every N seconds."""
    logger.info(f"Polling loop started (interval {POLL_INTERVAL_SECONDS}s, health-only)")
    try:
        while True:
            for fe in registry.list_enabled():
                status = await _check_one(fe["url"])
                registry.set_status(fe["id"], status)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Polling loop cancelled")
        raise
    except Exception as e:
        # Don't let a transient error kill the loop forever
        logger.error(f"Polling loop error: {e}; restarting in {POLL_INTERVAL_SECONDS}s")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
