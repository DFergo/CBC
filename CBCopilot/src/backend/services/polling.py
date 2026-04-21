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
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.config import config as backend_config
from src.services import (
    company_registry,
    context_compressor,
    guardrails,
    llm_provider,
    prompt_assembler,
    resolvers,
    session_rag,
    session_settings_store,
    smtp_service,
)
from src.services.frontend_registry import registry
from src.services.session_store import store as session_store

logger = logging.getLogger("polling")

POLL_INTERVAL_SECONDS = 2
HEALTH_TIMEOUT = 3.0
QUEUE_TIMEOUT = 5.0
STREAM_PUSH_TIMEOUT = 10.0
UPLOAD_FETCH_TIMEOUT = 30.0
PUSH_TIMEOUT = 5.0

# Track which frontends have had the current guardrails thresholds pushed to
# them. Cleared when the backend restarts or when thresholds change
# (see guardrails.invalidate_pushed_thresholds()).
_thresholds_pushed: set[str] = set()

# Track which frontends have had the current company list pushed. Invalidated
# per-frontend from the admin company CRUD endpoints so changes land on the
# next poll (≤ POLL_INTERVAL_SECONDS seconds).
_companies_pushed: set[str] = set()


def invalidate_thresholds_pushed() -> None:
    """Call from admin when thresholds change so next poll re-pushes."""
    _thresholds_pushed.clear()


def invalidate_companies_pushed(frontend_id: str | None = None) -> None:
    """Call from admin CRUD endpoints so next poll re-pushes the list.
    Pass frontend_id to target one frontend; omit to clear all."""
    if frontend_id is None:
        _companies_pushed.clear()
    else:
        _companies_pushed.discard(frontend_id)


async def _check_health(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(f"{url.rstrip('/')}/internal/health", timeout=HEALTH_TIMEOUT)
        return "online" if r.status_code == 200 else "offline"
    except httpx.HTTPError:
        return "offline"


async def _drain_queue(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """Drain the sidecar queue. Returns a dict with:
      - messages: list of queued chat/survey/close items
      - recovery_requests: list of session tokens the user pasted in SessionPage
    """
    try:
        r = await client.get(f"{url.rstrip('/')}/internal/queue", timeout=QUEUE_TIMEOUT)
        r.raise_for_status()
        return dict(r.json())
    except httpx.HTTPError as e:
        logger.warning(f"Drain queue at {url} failed: {e}")
        return {}


async def _push_companies_if_needed(client: httpx.AsyncClient, url: str, fid: str) -> None:
    """Push the admin-edited per-frontend company list to the sidecar once
    (HRDD branding-push pattern). Sidecar caches to disk; CompanySelectPage
    reads via /internal/companies. Invalidated on admin CRUD.

    Compare All is NOT a registered company — it's a frontend-level concept
    (own prompt `compare_all.md`, own routing, combined RAG). The sidecar
    prepends the Compare All button when listing; we just ship the real
    admin-registered companies here.
    """
    if fid in _companies_pushed:
        return
    companies = [c.model_dump() for c in company_registry.list_companies(fid)]
    try:
        r = await client.post(
            f"{url.rstrip('/')}/internal/companies",
            json={"companies": companies},
            timeout=PUSH_TIMEOUT,
        )
        if r.status_code // 100 != 2:
            logger.warning(f"Push companies to {fid}: HTTP {r.status_code}")
            return
    except httpx.HTTPError as e:
        logger.warning(f"Push companies to {fid} failed: {e}")
        return
    _companies_pushed.add(fid)


async def _push_thresholds_if_needed(client: httpx.AsyncClient, url: str, fid: str) -> None:
    """Push admin-configured guardrails thresholds to the sidecar once per
    frontend (HRDD branding-push pattern). Sidecar caches to disk; ChatShell
    reads on mount.
    """
    if fid in _thresholds_pushed:
        return
    body = {
        "warn_at": int(backend_config.guardrail_warn_at),
        "end_at": int(backend_config.guardrail_max_triggers),
    }
    try:
        r = await client.post(
            f"{url.rstrip('/')}/internal/guardrails/thresholds",
            json=body,
            timeout=PUSH_TIMEOUT,
        )
        if r.status_code // 100 != 2:
            logger.warning(f"Push thresholds to {fid}: HTTP {r.status_code}")
            return
    except httpx.HTTPError as e:
        logger.warning(f"Push thresholds to {fid} failed: {e}")
        return
    _thresholds_pushed.add(fid)


async def _handle_recovery_request(client: httpx.AsyncClient, url: str, token: str) -> None:
    """Resolve one pending recovery request and POST the result back to the
    sidecar. Status payload is 'found' (+data), 'not_found', or 'expired'.
    """
    token = (token or "").strip().upper()
    if not token:
        return

    def _post(status: str, data: dict[str, Any] | None = None) -> asyncio.Task[Any]:
        return asyncio.create_task(_push_recovery_result(client, url, token, status, data))

    sess = session_store.get_session(token)
    if not sess:
        await _post("not_found")
        return

    frontend_id = sess.get("frontend_id") or ""
    settings = session_settings_store.load(frontend_id)
    if settings is None:
        from src.services.session_settings_store import SessionSettings
        settings = SessionSettings()
    resume_hours = int(settings.session_resume_hours)

    created_at_raw = sess.get("created_at")
    try:
        created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
    except ValueError:
        created_at = None
    within_window = False
    if created_at and resume_hours > 0:
        age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
        within_window = age_hours <= resume_hours
    if not within_window:
        await _post("expired")
        return

    messages = [
        {
            "role": m.get("role"),
            "content": m.get("content", ""),
            "attachments": m.get("attachments") or [],
        }
        for m in sess.get("messages", [])
    ]
    data = {
        "token": token,
        "status": sess.get("status", "active"),
        "survey": sess.get("survey") or {},
        "language": sess.get("language", "en"),
        "frontend_id": frontend_id,
        "frontend_name": sess.get("frontend_name", ""),
        "created_at": created_at_raw,
        "last_activity": sess.get("last_activity"),
        "completed_at": sess.get("completed_at"),
        "guardrail_violations": int(sess.get("guardrail_violations", 0)),
        "messages": messages,
        "session_resume_hours": resume_hours,
    }
    await _post("found", data)


async def _push_recovery_result(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    status: str,
    data: dict[str, Any] | None,
) -> None:
    try:
        await client.post(
            f"{url.rstrip('/')}/internal/session/{token}/recovery-data",
            json={"status": status, "data": data},
            timeout=PUSH_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.warning(f"Push recovery result for {token} failed: {e}")


async def _handle_document_request(
    client: httpx.AsyncClient,
    url: str,
    doc_req: dict[str, Any],
) -> None:
    """Resolve a CBA sidepanel document download. Reads the requested file
    from the matching `documents/` dir and POSTs it back to the sidecar,
    or POSTs an error if the file is missing / path is unsafe.

    Security note: `filename` is treated as a bare basename — we strip any
    path components and resolve against the docs_dir so sessions can't ask
    for arbitrary disk paths. Only admin-uploaded docs in the resolved
    scope_key are reachable.
    """
    request_id = (doc_req.get("request_id") or "").strip()
    scope_key = (doc_req.get("scope_key") or "").strip()
    filename = (doc_req.get("filename") or "").strip()

    async def _push_error(detail: str) -> None:
        try:
            await client.post(
                f"{url.rstrip('/')}/internal/document/{request_id}/error",
                json={"detail": detail},
                timeout=PUSH_TIMEOUT,
            )
        except httpx.HTTPError as e:
            logger.warning(f"Push document error for {request_id} failed: {e}")

    if not request_id or not scope_key or not filename:
        await _push_error("Malformed document request")
        return

    from pathlib import Path as _Path
    safe_name = _Path(filename).name
    try:
        from src.services import rag_service
        docs_dir = rag_service._docs_dir_for(scope_key)
    except Exception as e:
        logger.warning(f"Bad scope_key {scope_key!r}: {e}")
        await _push_error(f"Unknown scope {scope_key}")
        return

    file_path = docs_dir / safe_name
    try:
        resolved = file_path.resolve()
        if not resolved.is_file() or not str(resolved).startswith(str(docs_dir.resolve())):
            await _push_error("Document not found")
            return
        content = resolved.read_bytes()
    except Exception as e:
        logger.warning(f"Reading {file_path}: {e}")
        await _push_error("Could not read document")
        return

    try:
        files = {"file": (safe_name, content, "application/octet-stream")}
        await client.post(
            f"{url.rstrip('/')}/internal/document/{request_id}/result",
            files=files,
            timeout=60.0,
        )
        logger.info(f"Pushed document {scope_key}/{safe_name} → {request_id} ({len(content)} bytes)")
    except httpx.HTTPError as e:
        logger.warning(f"Push document bytes for {request_id} failed: {e}")


async def _handle_auth_request(
    client: httpx.AsyncClient,
    url: str,
    auth_req: dict[str, Any],
    fid: str,
) -> None:
    """Resolve a queued auth action (request_code or verify_code) against the
    real auth logic, then POST the result back to the sidecar so it can be
    served from /internal/auth/status. Pull-inverse — sidecar never calls
    the backend directly.
    """
    from src.api.v1.auth import process_request_code, process_verify_code

    session_token = (auth_req.get("session_token") or "").strip()
    kind = auth_req.get("kind") or ("verify_code" if auth_req.get("code") else "request_code")
    if not session_token:
        return

    try:
        if kind == "verify_code":
            result = process_verify_code(session_token, auth_req.get("code") or "")
        else:
            result = await process_request_code(
                session_token=session_token,
                email=auth_req.get("email") or "",
                language=auth_req.get("language") or "en",
                frontend_id=auth_req.get("frontend_id") or fid,
            )
    except Exception as e:
        logger.exception(f"Auth handler failed for {session_token}: {e}")
        result = {"status": "error", "detail": str(e)[:200]}

    payload = {
        "status": str(result.get("status", "error")),
        "email": str(result.get("email", "")),
        "dev_code": str(result.get("dev_code", "")),
        "detail": str(result.get("detail", "")),
    }
    try:
        await client.post(
            f"{url.rstrip('/')}/internal/auth/{session_token}/result",
            json=payload,
            timeout=PUSH_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.warning(f"Push auth result for {session_token} failed: {e}")


async def _handle_uploads(client: httpx.AsyncClient, url: str, fid: str) -> None:
    """Poll the sidecar for pending uploads, ingest each one, then tell the
    sidecar to clean up its temp copy. Matches HRDD upload pull-inverse.
    """
    try:
        r = await client.get(f"{url.rstrip('/')}/internal/uploads", timeout=QUEUE_TIMEOUT)
        r.raise_for_status()
        uploads = list(r.json().get("uploads") or [])
    except httpx.HTTPError as e:
        logger.warning(f"List uploads from {fid} failed: {e}")
        return

    for upload in uploads:
        token = (upload.get("session_token") or "").strip()
        filename = (upload.get("filename") or "").strip()
        if not token or not filename:
            continue
        await _ingest_one_upload(client, url, fid, token, filename)


async def _ingest_one_upload(
    client: httpx.AsyncClient,
    url: str,
    fid: str,
    token: str,
    filename: str,
) -> None:
    """GET the file from the sidecar, ingest into session RAG, then DELETE
    the sidecar copy. Fire the admin alert (fire-and-forget) if configured.
    """
    try:
        r = await client.get(
            f"{url.rstrip('/')}/internal/upload/{token}/{filename}",
            timeout=UPLOAD_FETCH_TIMEOUT,
        )
        r.raise_for_status()
        content = r.content
    except httpx.HTTPError as e:
        logger.warning(f"Fetch upload {token}/{filename} from {fid} failed: {e}")
        return

    try:
        result = session_rag.ingest_upload(token, filename, content)
        logger.info(f"[{token}] ingested upload {filename} ({result.size} bytes)")
    except ValueError as e:
        logger.warning(f"[{token}] ingest of {filename} rejected: {e}")
        # Still delete the sidecar copy so it doesn't clog the temp dir.
    except Exception as e:
        logger.exception(f"[{token}] ingest of {filename} failed: {e}")
        return  # Do NOT delete — allow retry on next poll

    # Fire-and-forget admin alert (same logic as the old direct endpoint).
    sess = session_store.get_session(token)
    if sess:
        asyncio.create_task(_maybe_alert_admins(token, sess, filename, len(content)))

    try:
        await client.delete(
            f"{url.rstrip('/')}/internal/upload/{token}/{filename}",
            timeout=PUSH_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.info(f"Cleanup of {token}/{filename} on {fid} dropped: {e}")


async def _maybe_alert_admins(token: str, session: dict[str, Any], filename: str, size: int) -> None:
    cfg = smtp_service.load_config()
    if not cfg.send_new_document_to_admin:
        return
    if not smtp_service.is_configured(cfg):
        return
    frontend_id = session.get("frontend_id") or ""
    recipients = smtp_service.resolve_admin_emails(frontend_id)
    if not recipients:
        return
    survey = session.get("survey") or {}
    subject = f"[CBC] User uploaded {filename} in session {token}"
    body = (
        f"A user just attached a document to their chat session.\n\n"
        f"Session: {token}\n"
        f"Frontend: {session.get('frontend_name') or frontend_id}\n"
        f"Company: {survey.get('company_display_name') or survey.get('company_slug') or '(none)'}\n"
        f"Country: {survey.get('country') or '(not provided)'}\n"
        f"User email: {survey.get('email') or '(anonymous)'}\n"
        f"File: {filename} ({size} bytes)\n\n"
        f"You can view the session in the admin panel under Sessions."
    )
    try:
        await smtp_service.send_email(to_address=recipients, subject=subject, body=body)
        logger.info(f"[{token}] admin alert emailed to {len(recipients)} recipient(s) for upload {filename}")
    except Exception as e:
        logger.warning(f"[{token}] admin alert for upload {filename} failed: {e}")


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
    # Phase B: look up the per-frontend CBA-citations flag. The sidepanel
    # flag gates whether we emit the `sources` event at all; the separate
    # citations flag gates whether the prompt asks the LLM for inline
    # `[filename, locator]` references.
    fe_settings = session_settings_store.load(frontend_id)
    cite_inline = bool(
        fe_settings and getattr(fe_settings, "cba_citations_enabled", False)
        and getattr(fe_settings, "cba_sidepanel_enabled", True)
    )
    assembled = prompt_assembler.assemble(
        survey=survey,
        frontend_id=frontend_id,
        language=language,
        query_text=user_content,
        session_token=session_token,
        fresh_attachments=attachments,
        cite_inline=cite_inline,
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
    # Emit the citation list for this turn so the CBA sidepanel can render.
    # Fired before `done` so the UI can attach sources to the streaming bubble
    # before it's finalised. A no-op when retrieval returned nothing.
    sources = assembled.sources or []
    if sources:
        await _push_chunk(client, url, session_token, "sources", json.dumps(sources))
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

        # 2. Push guardrails thresholds once per frontend (pull-inverse —
        #    sidecar caches; ChatShell reads on mount).
        await _push_thresholds_if_needed(client, url, fid)

        # 2b. Push per-frontend company list (admin-edited; invalidated on CRUD).
        await _push_companies_if_needed(client, url, fid)

        # 3. Queue drain (messages + recovery_requests)
        drained = await _drain_queue(client, url)
        for msg in drained.get("messages") or []:
            try:
                await _process_message(client, fe, msg)
            except Exception as e:
                logger.exception(f"Processing message from {fid} failed: {e}")

        # 4. Handle recovery requests (pull-inverse: backend resolves, POSTs back)
        for token in drained.get("recovery_requests") or []:
            try:
                await _handle_recovery_request(client, url, token)
            except Exception as e:
                logger.exception(f"Recovery for {token} from {fid} failed: {e}")

        # 4b. Handle auth requests (pull-inverse: drain queued request_code /
        #     verify_code actions, resolve via auth.py, push result back).
        for auth_req in drained.get("auth_requests") or []:
            try:
                await _handle_auth_request(client, url, auth_req, fid)
            except Exception as e:
                logger.exception(f"Auth handler from {fid} failed: {e}")

        # 4c. Handle CBA sidepanel document-download requests (pull-inverse:
        #     read file from disk, POST bytes back to the sidecar).
        for doc_req in drained.get("document_requests") or []:
            try:
                await _handle_document_request(client, url, doc_req)
            except Exception as e:
                logger.exception(f"Document handler from {fid} failed: {e}")

        # 5. Handle uploads (pull-inverse: fetch, ingest, cleanup)
        try:
            await _handle_uploads(client, url, fid)
        except Exception as e:
            logger.exception(f"Handling uploads from {fid} failed: {e}")


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
