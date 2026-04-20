"""Session-scoped uploads — used by the chat UI in Sprint 6.

Sprint 5 ships the pipeline + a curl-testable endpoint. The sidecar relays
multipart uploads here; we save the file under the session's tree and add
it to the session's RAG index. No auth on this route in v1 — it's
internal-network only (only sidecars on `cbc-net` can reach the backend).
"""
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.core.config import config
from src.services import session_rag

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
