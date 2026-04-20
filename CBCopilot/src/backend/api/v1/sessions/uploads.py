"""Session-scoped endpoints — uploads (Sprint 5) + read-only status (Sprint 6B).

Sidecars on `cbc-net` relay user uploads here; ChatShell polls status to
refresh the guardrails-violation counter. No auth in v1 — the frontend
network perimeter is the trust boundary.
"""
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.core.config import config
from src.services import session_rag
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
    return {"upload": {"name": result.name, "size": result.size}}


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
