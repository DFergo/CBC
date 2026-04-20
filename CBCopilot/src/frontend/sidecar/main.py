# Adapted from HRDDHelper/src/frontend/sidecar/main.py
# Sprint 2: health, config, companies, auth stubs, survey queue.
# Sprint 4A: backend-push endpoints for branding + session-settings overrides;
#            /internal/config merges baseline JSON + pushed overrides.
# SSE streaming, recovery, file upload, evidence delete — later sprints.
import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sidecar")

app = FastAPI(title="CBC Frontend Sidecar", version="0.4.0")

_config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "/app/config/deployment_frontend.json")
_base_config: dict[str, Any] = {}
if os.path.exists(_config_path):
    with open(_config_path) as f:
        _base_config = json.load(f)

# Env-var overrides take precedence over the JSON baseline. This is what lets
# one image be deployed N times with different identities (Portainer pattern):
# the same Docker image carries the JSON defaults, but each running container
# reads CBC_FRONTEND_ID from its env to claim its own identity. Without this,
# `frontend_id` would be baked into the image at build time and you'd need
# one image per frontend.
_env_frontend_id = os.environ.get("CBC_FRONTEND_ID")
if _env_frontend_id:
    _base_config["frontend_id"] = _env_frontend_id
    logger.info(f"frontend_id overridden from env: {_env_frontend_id}")

_COMPANIES_FILE = Path("/app/config/companies.json")

# Pushed overrides from the backend cached on disk so they survive restarts.
_DATA_DIR = Path("/app/data")
_BRANDING_CACHE = _DATA_DIR / "pushed_branding.json"
_SESSION_SETTINGS_CACHE = _DATA_DIR / "pushed_session_settings.json"

# Hardcoded branding baseline. Like HRDD, the app ships with a default look in
# code; admins can override globally (Branding defaults in General tab) or
# per-frontend (FrontendsTab → Branding). When all overrides are absent, this
# wins. NOT read from deployment_frontend.json — that file shouldn't carry
# branding at all in CBC's model.
_HARDCODED_BRANDING: dict[str, str] = {
    "app_title": "Collective Bargaining Copilot",
    "org_name": "UNI Global Union",
    "logo_url": "/assets/uni-global-logo.png",
    "primary_color": "#003087",
    "secondary_color": "#E31837",
    # Empty in the baseline = use the i18n disclaimer/instructions text. Admins
    # can override globally or per-frontend with a custom block.
    "disclaimer_text": "",
    "instructions_text": "",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read {path}: {e}")
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


@app.get("/internal/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/config")
async def get_config():
    """Effective config = baseline deployment_frontend.json + pushed overrides.

    Backend pushes branding + session-settings via POST /internal/branding and
    POST /internal/session-settings; those cache to disk and override here.
    """
    pushed_branding = _read_json(_BRANDING_CACHE)
    pushed_settings = _read_json(_SESSION_SETTINGS_CACHE)

    # Branding: per-field merge of the hardcoded baseline with whatever the
    # backend pushed. Backend already merged global defaults + per-frontend
    # override (deepest non-empty wins) and stripped empty fields. We layer
    # those non-empty fields on top of the baseline. Empty pushed fields are
    # never sent, so they can never blank out the baseline. `custom=False`
    # means no override at any tier — pure baseline.
    branding = dict(_HARDCODED_BRANDING)
    if pushed_branding.get("custom"):
        for k, v in pushed_branding.items():
            if k == "custom" or v in ("", None):
                continue
            branding[k] = v

    def pick(key: str, default: Any) -> Any:
        if key in pushed_settings and pushed_settings[key] is not None:
            return pushed_settings[key]
        return _base_config.get(key, default)

    return {
        "role": "frontend",
        "frontend_id": _base_config.get("frontend_id", "default"),
        "auth_required": pick("auth_required", True),
        "disclaimer_enabled": pick("disclaimer_enabled", True),
        "instructions_enabled": pick("instructions_enabled", True),
        "compare_all_enabled": pick("compare_all_enabled", True),
        "session_resume_hours": pick("session_resume_hours", 48),
        "auto_close_hours": pick("auto_close_hours", 72),
        "auto_destroy_hours": pick("auto_destroy_hours", 0),
        "branding": branding,
    }


# --- Backend push targets ---

@app.post("/internal/branding")
async def push_branding(body: dict[str, Any]):
    """Backend pushes branding here when admin saves changes.

    Body: `{"custom": True, ...non_empty_fields}` — only non-empty fields are
    sent, and they merge per-field on top of `_HARDCODED_BRANDING`. Empty
    fields stay at the baseline.
    Or: `{"custom": False}` to clear the cache and use pure baseline.
    """
    _write_json(_BRANDING_CACHE, body)
    logger.info(f"Branding pushed: custom={body.get('custom', False)}")
    return {"status": "ok"}


@app.post("/internal/session-settings")
async def push_session_settings(body: dict[str, Any]):
    """Backend pushes session-settings override here when admin saves changes.

    Body is a flat dict with only the fields to override (auth_required,
    disclaimer_enabled, etc.). Empty dict = clear the override.
    """
    _write_json(_SESSION_SETTINGS_CACHE, body)
    logger.info(f"Session settings pushed: keys={list(body.keys())}")
    return {"status": "ok"}


# --- Companies (Sprint 2: sidecar-local stub; Sprint 3 backend replaces this) ---

@app.get("/internal/companies")
async def get_companies():
    if not _COMPANIES_FILE.exists():
        return {"companies": []}
    try:
        data = json.loads(_COMPANIES_FILE.read_text())
        items = data if isinstance(data, list) else data.get("companies", [])
        # Compare All entries first, then alphabetical by display_name.
        items.sort(key=lambda c: (
            0 if c.get("is_compare_all") else 1,
            (c.get("display_name") or c.get("slug") or "").lower(),
        ))
        return {"companies": items}
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read companies.json: {e}")
        return {"companies": []}


# --- Auth (Sprint 7: relay to backend for SMTP + Contacts allowlist) ---


class AuthRequestCode(BaseModel):
    session_token: str
    email: str


class AuthVerifyCode(BaseModel):
    session_token: str
    code: str


async def _backend_call(method: str, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
    url = f"{os.environ.get('CBC_BACKEND_URL', 'http://cbc-backend:8000').rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.request(method, url, json=json_body)
    except httpx.HTTPError as e:
        logger.warning(f"Backend call to {url} failed: {e}")
        raise HTTPException(502, f"Backend unreachable: {e}")
    if r.status_code == 403:
        raise HTTPException(403, r.json().get("detail", "Not authorized"))
    if r.status_code // 100 != 2:
        raise HTTPException(r.status_code, r.text[:300])
    return r.json()


@app.post("/internal/auth/request-code")
async def request_auth_code(req: AuthRequestCode):
    """Relay to backend. Backend handles SMTP + Contacts allowlist. Sprint 7."""
    body = {
        "session_token": req.session_token,
        "email": req.email,
        "language": "en",  # sidecar doesn't know the user's language yet
        "frontend_id": _base_config.get("frontend_id", ""),
    }
    data = await _backend_call("POST", "/api/v1/auth/request-code", body)
    logger.info(
        f"Auth code requested via backend: email={req.email} session={req.session_token} "
        + ("(SMTP)" if "dev_code" not in data else "(dev fallback)")
    )
    return data


@app.post("/internal/auth/verify-code")
async def verify_auth_code(req: AuthVerifyCode):
    """Relay to backend. Sprint 7."""
    body = {"session_token": req.session_token, "code": req.code}
    return await _backend_call("POST", "/api/v1/auth/verify-code", body)


# --- Survey queue (Sprint 2) ---

MESSAGE_TTL = 300
_queue: list[dict[str, Any]] = []
_queue_lock = asyncio.Lock()


class SurveySubmit(BaseModel):
    session_token: str
    survey: dict[str, Any]
    language: str = "en"


@app.post("/internal/queue")
async def enqueue_survey(msg: SurveySubmit):
    """Survey submission — enqueued for the backend to process on its next poll."""
    async with _queue_lock:
        _queue.append({"type": "survey", **msg.model_dump(), "created_at": time.time()})
    logger.info(
        f"Survey submitted: session={msg.session_token} "
        f"company={msg.survey.get('company_slug')} "
        f"country={msg.survey.get('country')} "
        f"query={(msg.survey.get('initial_query') or '')[:60]}..."
    )
    return {"status": "queued"}


class ChatMessage(BaseModel):
    session_token: str
    content: str
    language: str = "en"
    attachments: list[str] = []  # filenames already ingested via /internal/upload


class CloseSession(BaseModel):
    session_token: str
    language: str = "en"


@app.post("/internal/close-session")
async def enqueue_close(msg: CloseSession):
    """End-session signal. Backend dequeues, runs the summariser slot on the
    conversation, streams the summary back via /internal/stream, then marks
    the session status='completed'."""
    async with _queue_lock:
        _queue.append({
            "type": "close",
            "session_token": msg.session_token,
            "language": msg.language,
            "created_at": time.time(),
        })
    logger.info(f"Close session queued: session={msg.session_token}")
    return {"status": "queued"}


@app.post("/internal/chat")
async def enqueue_chat(msg: ChatMessage):
    """Chat turn from the user. Backend dequeues, assembles prompt, streams
    response back via /internal/stream/{session_token}/chunk."""
    if not msg.content.strip():
        return {"status": "empty"}
    async with _queue_lock:
        _queue.append({
            "type": "chat",
            "session_token": msg.session_token,
            "content": msg.content,
            "language": msg.language,
            "attachments": msg.attachments,
            "created_at": time.time(),
        })
    logger.info(
        f"Chat message queued: session={msg.session_token} len={len(msg.content)}"
        + (f" attachments={msg.attachments}" if msg.attachments else "")
    )
    return {"status": "queued"}


@app.get("/internal/queue")
async def dequeue_messages():
    now = time.time()
    async with _queue_lock:
        valid = [m for m in _queue if now - m["created_at"] < MESSAGE_TTL]
        _queue.clear()
    return {"messages": valid}


# --- SSE stream channels (Sprint 6A) ---
# Backend pushes tokens to POST /internal/stream/{token}/chunk; React reads
# from GET /internal/stream/{token} with an EventSource. One queue per
# session token (D1=A serial — second message queues behind first).

_streams: dict[str, asyncio.Queue] = {}
_streams_lock = asyncio.Lock()


class StreamChunk(BaseModel):
    event: str  # "token" | "done" | "error"
    data: str


async def _get_or_create_stream(token: str) -> asyncio.Queue:
    async with _streams_lock:
        if token not in _streams:
            _streams[token] = asyncio.Queue()
        return _streams[token]


@app.post("/internal/stream/{session_token}/chunk")
async def push_stream_chunk(session_token: str, chunk: StreamChunk):
    """Backend pushes one SSE event (a token, done marker, or error)."""
    q = await _get_or_create_stream(session_token)
    await q.put({"event": chunk.event, "data": chunk.data})
    if chunk.event in ("done", "error"):
        # Let the consumer drain, then clean up the queue so a new turn starts fresh.
        async def _cleanup():
            await asyncio.sleep(5)
            async with _streams_lock:
                _streams.pop(session_token, None)
        asyncio.create_task(_cleanup())
    return {"status": "ok"}


@app.get("/internal/stream/{session_token}")
async def stream_sse(session_token: str):
    """React EventSource endpoint. Emits `token` events during generation,
    then a `done` (or `error`) event, then closes.
    """
    from fastapi.responses import StreamingResponse

    q = await _get_or_create_stream(session_token)

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                # SSE multi-line data: each line needs its own "data:" prefix
                lines = event["data"].split("\n")
                data_block = "\n".join(f"data: {line}" for line in lines)
                yield f"event: {event['event']}\n{data_block}\n\n"
                if event["event"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                # Keepalive comment so proxies / browsers don't drop the connection
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disables Nginx buffering if any
        },
    )


# --- Session uploads (Sprint 5) ---
# Browser → sidecar /internal/upload → backend /api/v1/sessions/{token}/upload.
# We forward over the shared `cbc-net` network using the conventional
# `cbc-backend` service name. End users never see the backend URL — they
# only ever talk to the sidecar.

import httpx  # noqa: E402  — kept here so the sidecar's boot path doesn't pay the import cost
from fastapi import File, HTTPException, UploadFile  # noqa: E402

_BACKEND_URL = os.environ.get("CBC_BACKEND_URL", "http://cbc-backend:8000")
_UPLOAD_TIMEOUT = 30.0


@app.get("/internal/session/{session_token}/recover")
async def recover_session(session_token: str):
    """Proxy for the backend's recovery endpoint. The React SessionPage calls
    this when the user pastes a session token and clicks Resume."""
    url = f"{_BACKEND_URL}/api/v1/sessions/{session_token}/recover"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
    except httpx.HTTPError as e:
        logger.warning(f"Recovery relay to {url} failed: {e}")
        raise HTTPException(502, f"Backend unreachable: {e}")
    if r.status_code // 100 != 2:
        raise HTTPException(r.status_code, r.text[:300])
    return r.json()


@app.post("/internal/upload")
async def upload_session_file(session_token: str, file: UploadFile = File(...)):
    """Forward a session upload to the backend's session ingest endpoint."""
    if not file.filename:
        raise HTTPException(400, "No filename")
    content = await file.read()
    url = f"{_BACKEND_URL}/api/v1/sessions/{session_token}/upload"
    files = {"file": (file.filename, content, file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
            r = await client.post(url, files=files)
    except httpx.HTTPError as e:
        logger.error(f"Upload relay to {url} failed: {e}")
        raise HTTPException(502, f"Backend unreachable: {e}")
    if r.status_code // 100 != 2:
        raise HTTPException(r.status_code, r.text[:300])
    return r.json()
