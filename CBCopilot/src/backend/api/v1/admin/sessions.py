"""Admin endpoints for session inspection (SPEC §5.1).

List + detail drawer + flag + destroy (D6=A). No HRDD-style role/mode
columns — CBC has a single user profile. Report / internal-summary
generation endpoints are absent by design (ADR-004).
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.v1.admin.auth import require_admin
from src.services import session_rag
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
