"""Session-scoped endpoints — uploads (Sprint 5), status (Sprint 6B), and
recovery (Sprint 7).

Sidecars on `cbc-net` relay user uploads here; ChatShell polls status to
refresh the guardrails-violation counter; the SessionPage "Resume existing
session" button calls the recovery endpoint through the sidecar. No auth in
v1 — the frontend network perimeter is the trust boundary.
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.core.config import config
from src.services import session_rag, session_settings_store, smtp_service
from src.services.session_store import store as session_store

logger = logging.getLogger("api.sessions.uploads")

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

MAX_UPLOAD_BYTES = config.file_max_size_mb * 1024 * 1024


@router.post("/{token}/upload", status_code=201)
async def upload_to_session(token: str, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {config.file_max_size_mb} MB.",
        )
    try:
        result = session_rag.ingest_upload(token, file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fire-and-forget admin alert (Sprint 7). Only runs when SMTP is configured
    # AND the `send_new_document_to_admin` toggle is on AND there's at least
    # one admin recipient resolved for this session's frontend.
    sess = session_store.get_session(token)
    if sess:
        asyncio.create_task(_maybe_alert_admins(token, sess, file.filename, result.size))

    return {"upload": {"name": result.name, "size": result.size}}


async def _maybe_alert_admins(token: str, session: dict, filename: str, size: int) -> None:
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


@router.get("/{token}/uploads")
async def list_session_uploads(token: str):
    try:
        items = session_rag.list_uploads(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"uploads": [{"name": u.name, "size": u.size} for u in items]}


@router.delete("/{token}")
async def destroy_session(token: str):
    try:
        removed = session_rag.destroy_session(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "removed": removed}


@router.get("/{token}/status")
async def get_session_status(token: str):
    """Lightweight poll target for the chat UI — no conversation payload.
    Returns the bits that drive UI state: status, violation count, last activity."""
    sess = session_store.get_session(token)
    if not sess:
        raise HTTPException(status_code=404, detail=f"Session {token!r} not found")
    return {
        "token": token,
        "status": sess.get("status", "active"),
        "guardrail_violations": int(sess.get("guardrail_violations", 0)),
        "message_count": len(sess.get("messages", [])),
        "last_activity": sess.get("last_activity"),
    }


@router.get("/{token}/recover")
async def recover_session(token: str):
    """Recovery endpoint for the SessionPage "Resume existing session" flow.

    Returns the full conversation + survey + status if the session exists AND
    the user is still within `session_resume_hours` of its creation. The
    frontend uses this to render the chat view pre-populated with the past
    conversation, then opens a fresh SSE for future turns.

    Sprint 7 D1=B: we replay the persisted state; we don't try to re-attach
    to any in-flight LLM stream.
    """
    sess = session_store.get_session(token)
    if not sess:
        raise HTTPException(status_code=404, detail=f"Session {token!r} not found")

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
        raise HTTPException(
            status_code=410,
            detail=f"Session is outside the {resume_hours}h resume window.",
        )

    # Strip timestamps and system prompt from the payload — the frontend
    # renders bubbles from role + content only.
    messages = [
        {
            "role": m.get("role"),
            "content": m.get("content", ""),
            "attachments": m.get("attachments") or [],
        }
        for m in sess.get("messages", [])
    ]
    return {
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
