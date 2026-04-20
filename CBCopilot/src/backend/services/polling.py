"""Backend polling loop — replaces Sprint 4A's health-only `polling_loop`.

For every registered + enabled frontend, every POLL_INTERVAL_SECONDS:

1. `GET {url}/internal/health`   → update online/offline status
2. `GET {url}/internal/queue`    → drain queued items
    - type == "survey" → init_session on disk; inject the survey's
        `initial_query` as the first user message; process like a chat turn.
    - type == "chat" → dispatch the user turn through the pipeline.

Per turn (survey first turn or subsequent chat):
    a. Append user message to the session's conversation log.
    b. Run guardrails (count triggers, continue).
    c. Assemble system prompt via `prompt_assembler.assemble(...)`.
    d. Refresh the session's system prompt in the store.
    e. Stream LLM tokens via `llm_provider.stream_chat`, relaying each token
        to the frontend's SSE queue at
        `POST {url}/internal/stream/{session_token}/chunk`.
    f. On success, append the assistant message to the log and push `done`.
    g. On failure, push `error` so the UI can show something actionable.

Lesson #2 (message TTL): we relay tokens immediately — no buffering. If a
user closes the tab mid-stream, tokens land in the sidecar queue and get
drained the next time the UI reconnects (within 30s keepalive window).
"""
import asyncio
import logging
from typing import Any

import httpx

from src.core.config import config as backend_config
from src.services import context_compressor, guardrails, llm_provider, prompt_assembler, resolvers, smtp_service
from src.services.frontend_registry import registry
from src.services.session_store import store as session_store

logger = logging.getLogger("polling")

POLL_INTERVAL_SECONDS = 2
HEALTH_TIMEOUT = 3.0
QUEUE_TIMEOUT = 5.0
STREAM_PUSH_TIMEOUT = 10.0


async def _check_health(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(f"{url.rstrip('/')}/internal/health", timeout=HEALTH_TIMEOUT)
        return "online" if r.status_code == 200 else "offline"
    except httpx.HTTPError:
        return "offline"


async def _drain_queue(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    try:
        r = await client.get(f"{url.rstrip('/')}/internal/queue", timeout=QUEUE_TIMEOUT)
        r.raise_for_status()
        return list(r.json().get("messages") or [])
    except httpx.HTTPError as e:
        logger.warning(f"Drain queue at {url} failed: {e}")
        return []


async def _push_chunk(client: httpx.AsyncClient, url: str, token: str, event: str, data: str) -> None:
    try:
        await client.post(
            f"{url.rstrip('/')}/internal/stream/{token}/chunk",
            json={"event": event, "data": data},
            timeout=STREAM_PUSH_TIMEOUT,
        )
    except httpx.HTTPError as e:
        # Non-fatal — the React side may have disconnected. Log and continue.
        logger.info(f"Push chunk to {url}/{token} [{event}] dropped: {e}")


async def _process_turn(
    client: httpx.AsyncClient,
    url: str,
    frontend_id: str,
    frontend_name: str,
    session_token: str,
    user_content: str,
    language: str,
    attachments: list[str] | None = None,
) -> None:
    """Run one user turn end-to-end: guardrails → prompt assembly → stream."""
    session = session_store.get_session(session_token)
    if not session:
        logger.warning(f"Chat for unknown session {session_token}; ignoring")
        await _push_chunk(client, url, session_token, "error", "Session not found")
        return

    survey = session.get("survey") or {}

    # Persist the user's raw turn first so the conversation log reflects what
    # they said regardless of what we do with it downstream. Attachments go
    # in as a structured field (ChatShell re-renders chips on reload; the
    # LLM-facing view decorates with "the user attached this turn: …").
    session_store.add_message(session_token, "user", user_content, attachments=attachments)

    # Guardrails (Sprint 7.5 D3=A, HRDD Sprint 16 pattern): on ANY triggered
    # turn, skip the LLM entirely — we don't want the model to even see the
    # jailbreak attempt. Push a fixed response as the assistant turn. If this
    # push takes the violation counter past the configured threshold, end
    # the session right here.
    guard = guardrails.check(user_content, language=language)
    if guard.triggered:
        violations = session_store.increment_guardrail_violations(session_token)
        end_at = int(backend_config.guardrail_max_triggers)
        logger.warning(
            f"[{session_token}] Guardrail triggered ({guard.category}): "
            f"violation {violations}/{end_at}"
        )
        if violations >= end_at:
            ended_text = guardrails.session_ended_response(language)
            session_store.add_message(session_token, "assistant", ended_text)
            # Flag + close the session so the admin can spot it easily.
            if not session.get("flagged"):
                session_store.toggle_flag(session_token)
            session_store.set_status(session_token, "completed")
            await _push_chunk(client, url, session_token, "token", ended_text)
            await _push_chunk(client, url, session_token, "done", "guardrail_ended")
            logger.warning(f"[{session_token}] Session ended — guardrail threshold reached")
            return
        # Under threshold: just deliver the fixed response, keep the session alive.
        session_store.add_message(session_token, "assistant", guard.response)
        await _push_chunk(client, url, session_token, "token", guard.response)
        await _push_chunk(client, url, session_token, "done", "")
        return

    # Assemble + store system prompt for this turn. Fresh attachments are
    # force-injected into the RAG context so the model can't ignore them.
    assembled = prompt_assembler.assemble(
        survey=survey,
        frontend_id=frontend_id,
        language=language,
        query_text=user_content,
        session_token=session_token,
        fresh_attachments=attachments,
    )
    session_store.init_session(
        token=session_token,
        system_prompt=assembled.text,
        survey=survey,
        language=language,
        frontend_id=frontend_id,
        frontend_name=frontend_name,
    )
    logger.info(
        f"[{session_token}] prompt assembled: "
        f"{len(assembled.text)} chars, {assembled.rag_chunks_used} RAG chunks, "
        f"tiers={[p['tier'] for p in assembled.rag_paths]}"
    )

    # Stream LLM response → relay each token to the sidecar
    messages = session_store.get_llm_messages(session_token)
    # Context compression: swap in a shortened message list when we've passed
    # the progressive thresholds. Returns `messages` unchanged when disabled
    # or below threshold.
    messages = await context_compressor.compress_if_needed(session_token, messages, frontend_id)
    accumulated: list[str] = []
    try:
        async for token_text in llm_provider.stream_chat(messages, slot="inference", frontend_id=frontend_id):
            accumulated.append(token_text)
            await _push_chunk(client, url, session_token, "token", token_text)
    except Exception as e:
        logger.exception(f"[{session_token}] LLM stream failed: {e}")
        await _push_chunk(client, url, session_token, "error", f"LLM error: {e}")
        return

    full = "".join(accumulated).strip()
    if full:
        session_store.add_message(session_token, "assistant", full)
    await _push_chunk(client, url, session_token, "done", "")


async def _process_message(client: httpx.AsyncClient, fe: dict[str, Any], msg: dict[str, Any]) -> None:
    url = fe["url"]
    frontend_id = fe.get("frontend_id") or fe.get("id") or ""
    frontend_name = fe.get("name") or frontend_id
    kind = msg.get("type", "survey")  # default = survey (old sidecars)
    session_token = msg.get("session_token", "")
    if not session_token:
        logger.warning(f"Message missing session_token: {msg}")
        return

    if kind == "survey":
        survey = msg.get("survey") or {}
        language = msg.get("language", "en")
        # Seed session metadata; system prompt will be built during the first turn.
        session_store.init_session(
            token=session_token,
            system_prompt="",
            survey=survey,
            language=language,
            frontend_id=frontend_id,
            frontend_name=frontend_name,
        )
        # D5=A: auto-inject the survey's initial_query as the first user turn
        initial_query = (survey.get("initial_query") or "").strip()
        if initial_query and not session_store.get_session(session_token).get("initial_query_injected"):
            session_store.mark_initial_query_injected(session_token)
            await _process_turn(
                client, url, frontend_id, frontend_name,
                session_token, initial_query, language,
            )
        return

    if kind == "chat":
        content = (msg.get("content") or "").strip()
        language = msg.get("language", "en")
        attachments = list(msg.get("attachments") or [])
        # File-only turn (user attached files with empty text): seed a minimal
        # prompt so the history has a readable pivot and the LLM knows the
        # user's intent is to have the assistant examine the files.
        if not content and attachments:
            content = f"Please examine the files I just attached: {', '.join(attachments)}."
        if not content:
            return
        await _process_turn(
            client, url, frontend_id, frontend_name,
            session_token, content, language,
            attachments=attachments or None,
        )
        return

    if kind == "close":
        language = msg.get("language", "en")
        await _process_close(client, url, frontend_id, session_token, language)
        return

    logger.warning(f"Unknown queue message type {kind!r}: {msg}")


async def _process_close(
    client: httpx.AsyncClient,
    url: str,
    frontend_id: str,
    session_token: str,
    language: str,
) -> None:
    """Generate the end-session user summary via the summariser slot, stream
    it back, then mark the session `completed`. SMTP send is Sprint 7 — for
    now the summary is only surfaced to the user inline in the chat.
    """
    session = session_store.get_session(session_token)
    if not session:
        await _push_chunk(client, url, session_token, "error", "Session not found")
        return
    history = session.get("messages") or []
    if not history:
        await _push_chunk(client, url, session_token, "error", "Nothing to summarise")
        return

    # Build a lightweight message list: summariser system prompt + the
    # conversation transcript formatted as context. Reads `summary.md` via the
    # Sprint 4B resolver so per-frontend / per-company overrides work.
    summary_prompt = resolvers.resolve_prompt(
        "summary.md", frontend_id, session.get("survey", {}).get("company_slug"),
    )
    system = (summary_prompt.content or "Produce a structured summary of the conversation.").strip()
    transcript_lines: list[str] = []
    for m in history:
        role = m.get("role", "user")
        who = "User" if role == "user" else "Assistant"
        transcript_lines.append(f"### {who}\n{m.get('content', '')}")
    transcript = "\n\n".join(transcript_lines)

    prompt_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Conversation transcript (language: {language}):\n\n{transcript}"},
    ]

    accumulated: list[str] = []
    try:
        async for token_text in llm_provider.stream_chat(
            prompt_messages, slot="summariser", frontend_id=frontend_id,
        ):
            accumulated.append(token_text)
            await _push_chunk(client, url, session_token, "token", token_text)
    except Exception as e:
        logger.exception(f"[{session_token}] Summary generation failed: {e}")
        await _push_chunk(client, url, session_token, "error", f"Summary error: {e}")
        return

    summary_text = "".join(accumulated).strip()
    if summary_text:
        session_store.add_message(session_token, "assistant_summary", summary_text)
    session_store.set_status(session_token, "completed")

    # Email the summary to the user if they provided an email AND SMTP is
    # configured. Fire-and-forget so the SSE close event lands regardless.
    user_email = (session.get("survey", {}).get("email") or "").strip()
    if summary_text and user_email and smtp_service.is_configured():
        asyncio.create_task(_email_summary(session_token, user_email, summary_text, language))
    else:
        logger.info(
            f"[{session_token}] session closed; summary {len(summary_text)} chars; "
            f"email_send=skipped (user_email={'set' if user_email else 'none'}, "
            f"smtp={'configured' if smtp_service.is_configured() else 'offline'})"
        )

    # Tell the client the session has ended so the UI can lock the input.
    # `data` carries the completion reason ("summary" or "error") for future use.
    await _push_chunk(client, url, session_token, "done", "summary")


async def _email_summary(session_token: str, to_email: str, summary: str, language: str) -> None:
    """Non-blocking delivery of the user summary. Runs after _process_close
    pushes the `done` event so UI responsiveness doesn't depend on SMTP."""
    subjects = {
        "en": "Your Collective Bargaining Copilot session summary",
        "es": "Resumen de tu sesión con Collective Bargaining Copilot",
        "fr": "Résumé de votre session avec Collective Bargaining Copilot",
        "de": "Zusammenfassung Ihrer Sitzung mit Collective Bargaining Copilot",
        "pt": "Resumo da sua sessão com Collective Bargaining Copilot",
    }
    subject = subjects.get(language, subjects["en"])
    body = f"{summary}\n\n—\nSession: {session_token}"
    try:
        await smtp_service.send_email(to_address=to_email, subject=subject, body=body)
        logger.info(f"[{session_token}] summary emailed to {to_email}")
    except Exception as e:
        logger.warning(f"[{session_token}] summary email to {to_email} failed: {e}")


async def _tick(client: httpx.AsyncClient) -> None:
    """One polling pass over every registered + enabled frontend."""
    for fe in registry.list_enabled():
        url = fe["url"]
        fid = fe.get("frontend_id") or fe.get("id") or ""

        # 1. Health
        status = await _check_health(client, url)
        registry.set_status(fid, status)
        if status != "online":
            continue

        # 2. Queue drain
        messages = await _drain_queue(client, url)
        for msg in messages:
            try:
                await _process_message(client, fe, msg)
            except Exception as e:
                logger.exception(f"Processing message from {fid} failed: {e}")


async def polling_loop() -> None:
    """Background task kicked off from `main.py` lifespan. Never exits
    voluntarily; restarts itself if anything inside explodes."""
    logger.info(f"Polling loop started (interval {POLL_INTERVAL_SECONDS}s, health + queue drain)")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await _tick(client)
            except asyncio.CancelledError:
                logger.info("Polling loop cancelled")
                raise
            except Exception as e:
                logger.exception(f"Polling tick crashed: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
