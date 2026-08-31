"""Admin endpoints for session inspection (SPEC §5.1).

List + detail drawer + flag + destroy (D6=A). No HRDD-style role/mode
columns — CBC has a single user profile. Report / internal-summary
generation endpoints are absent by design (ADR-004).
"""
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.api.v1.admin.auth import require_admin
from src.services import session_rag
from src.services._paths import SESSIONS_DIR, safe_filename
from src.services.session_store import store as session_store

logger = logging.getLogger("admin.sessions")

router = APIRouter(prefix="/admin/api/v1/sessions", tags=["admin-sessions"])


def _sorted_sessions() -> list[dict[str, Any]]:
    items = session_store.list_sessions()
    items.sort(
        key=lambda s: (s.get("last_activity") or s.get("created_at") or ""),
        reverse=True,
    )
    return items


@router.get("")
async def list_sessions(_admin: dict = Depends(require_admin)):
    return {"sessions": _sorted_sessions()}


@router.get("/{token}")
async def get_session(token: str, _admin: dict = Depends(require_admin)):
    sess = session_store.get_session(token)
    if not sess:
        raise HTTPException(status_code=404, detail=f"Session {token!r} not found")

    # Uploads directly from disk so we reflect what the session RAG actually sees
    try:
        uploads = session_rag.list_uploads(token)
        upload_payload = [{"name": u.name, "size": u.size} for u in uploads]
    except Exception as e:
        logger.warning(f"Could not list uploads for {token}: {e}")
        upload_payload = []

    # Strip timestamps on messages to match the React bubble contract
    messages = [
        {
            "role": m.get("role"),
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp"),
            "attachments": m.get("attachments") or [],
        }
        for m in sess.get("messages", [])
    ]

    # Surface the latest summary at the top of the payload so the drawer can
    # pin it without scrolling through the conversation to find it.
    summary: str | None = None
    for m in reversed(messages):
        if m["role"] == "assistant_summary":
            summary = m["content"]
            break

    return {
        "token": token,
        "status": sess.get("status", "active"),
        "flagged": bool(sess.get("flagged", False)),
        "guardrail_violations": int(sess.get("guardrail_violations", 0)),
        "survey": sess.get("survey") or {},
        "language": sess.get("language", "en"),
        "frontend_id": sess.get("frontend_id", ""),
        "frontend_name": sess.get("frontend_name", ""),
        "created_at": sess.get("created_at"),
        "last_activity": sess.get("last_activity"),
        "completed_at": sess.get("completed_at"),
        "message_count": len(messages),
        "messages": messages,
        "uploads": upload_payload,
        "summary": summary,
    }


@router.post("/{token}/flag")
async def toggle_flag(token: str, _admin: dict = Depends(require_admin)):
    if not session_store.exists(token):
        raise HTTPException(status_code=404, detail=f"Session {token!r} not found")
    flagged = session_store.toggle_flag(token)
    return {"token": token, "flagged": flagged}


@router.delete("/{token}")
async def destroy(token: str, _admin: dict = Depends(require_admin)):
    """ADR-005 privacy wipe: rm -rf the session tree + clear all in-memory caches."""
    removed = session_store.destroy_session(token)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session {token!r} not found")
    return {"token": token, "removed": True}


@router.get("/{token}/uploads/{filename}")
async def download_session_upload(
    token: str,
    filename: str,
    _admin: dict = Depends(require_admin),
):
    """Stream a user-uploaded file from the session's tree to the admin.

    Used by the Sessions tab's detail drawer Download / Copy-text buttons.
    Path is constructed + validated — traversal attempts (`../etc/passwd`)
    are rejected by `safe_filename` and the `relative_to` sanity check.
    """
    try:
        fname = safe_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    uploads_dir = (SESSIONS_DIR / token / "uploads").resolve()
    requested = (uploads_dir / fname).resolve()
    try:
        requested.relative_to(uploads_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not requested.is_file():
        raise HTTPException(status_code=404, detail=f"Upload {fname!r} not found in session {token!r}")

    # Keep the original name in Content-Disposition so downloads don't lose it.
    return FileResponse(
        path=str(requested),
        filename=fname,
        media_type="application/octet-stream",
    )
