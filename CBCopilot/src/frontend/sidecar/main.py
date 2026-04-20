# Adapted from HRDDHelper/src/frontend/sidecar/main.py
# Sprint 2: health, config, companies, auth stubs, survey queue.
# Sprint 4A: backend-push endpoints for branding + session-settings overrides;
#            /internal/config merges baseline JSON + pushed overrides.
# SSE streaming added in Sprint 6A.
# Sprint 8 (pull-inverse fix): uploads, session recovery, and guardrails
# thresholds all flow through the backend's polling loop — NO direct
# sidecar→backend HTTP. Matches HRDD architecture.
import asyncio
import json
import logging
import os
import random
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx  # used only by the auth relay below — follow-up to also pull-invert
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
_HARDCODED_BRANDING: dict[str, Any] = {
    "app_title": "Collective Bargaining Copilot",
    "org_name": "UNI Global Union",
    "logo_url": "/assets/uni-global-logo.png",
    "primary_color": "#003087",
    "secondary_color": "#E31837",
    # Empty in the baseline = use the i18n disclaimer/instructions text. Admins
    # can override globally or per-frontend with a custom block.
    "disclaimer_text": "",
    "instructions_text": "",
    # Sprint 8: source language + per-language translations for the text blocks
    # above. Pushed-through from whichever tier owns the text (resolvers.py).
    "source_language": "en",
    "disclaimer_text_translations": {},
    "instructions_text_translations": {},
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
    """Backend poll target — drains pending chat/survey/close messages and
    surfaces pending recovery_requests (tokens) so the backend can resolve
    them in the same tick."""
    now = time.time()
    async with _queue_lock:
        valid = [m for m in _queue if now - m["created_at"] < MESSAGE_TTL]
        _queue.clear()
    async with _recovery_lock:
        pending_tokens = [tok for tok, s in _recovery.items() if s["status"] == "pending"]
    result: dict[str, Any] = {"messages": valid}
    if pending_tokens:
        result["recovery_requests"] = pending_tokens
    return result


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


# --- Guardrails thresholds (push from backend) ---
# Backend pushes the admin-configured warn/end thresholds during its polling
# cycle. Sidecar caches them to disk; ChatShell reads via the GET route on
# mount. Fallback defaults are HRDD-era 2/5 so UI never breaks.

_GUARDRAIL_THRESHOLDS_CACHE = _DATA_DIR / "pushed_guardrails_thresholds.json"
_DEFAULT_THRESHOLDS = {"warn_at": 2, "end_at": 5}


class GuardrailThresholdsBody(BaseModel):
    warn_at: int
    end_at: int


@app.post("/internal/guardrails/thresholds")
async def push_guardrails_thresholds(body: GuardrailThresholdsBody):
    """Backend pushes the configured guardrails thresholds here on every poll."""
    _write_json(_GUARDRAIL_THRESHOLDS_CACHE, body.model_dump())
    return {"status": "ok"}


@app.get("/internal/guardrails/thresholds")
async def get_guardrails_thresholds():
    """ChatShell reads this on mount to show the amber-banner threshold +
    lock the input at the end threshold."""
    cached = _read_json(_GUARDRAIL_THRESHOLDS_CACHE)
    warn = cached.get("warn_at")
    end = cached.get("end_at")
    if isinstance(warn, int) and isinstance(end, int):
        return {"warn_at": warn, "end_at": end}
    return dict(_DEFAULT_THRESHOLDS)


# --- Session recovery (pull-inverse, HRDD pattern) ---
# React POSTs to /internal/session/recover with a token; the sidecar queues a
# recovery_request that the backend picks up on its next poll. Backend pushes
# the resolved session data to /internal/session/{token}/recovery-data. React
# polls /internal/session/{token}/recover for the status until it's resolved.

_recovery: dict[str, dict[str, Any]] = {}
_recovery_lock = asyncio.Lock()
_RECOVERY_TTL = 60.0  # seconds — abandon pending requests after this


class RecoverRequest(BaseModel):
    token: str


class RecoveryData(BaseModel):
    status: str  # "found" | "not_found" | "expired"
    data: dict[str, Any] | None = None


@app.post("/internal/session/recover")
async def request_recovery(req: RecoverRequest):
    """React starts a recovery by session token. Queues the request for the
    backend's next poll; the React app then polls /internal/session/{token}/recover
    for the result."""
    token = req.token.strip().upper()
    if not token:
        raise HTTPException(400, "Empty token")
    async with _recovery_lock:
        _recovery[token] = {"status": "pending", "data": None, "created_at": time.time()}
    return {"status": "pending"}


@app.get("/internal/session/{token}/recover")
async def poll_recovery(token: str):
    """React polls this. Returns status='pending' until backend pushes a
    result (found / not_found / expired). Once delivered, the slot is freed
    so a subsequent attempt on the same token starts fresh."""
    token = token.strip().upper()
    async with _recovery_lock:
        state = _recovery.get(token)
        if not state:
            raise HTTPException(404, "No recovery request for this token")
        # Abandon stale pendings so the React app sees an error instead of
        # spinning forever if the backend never polled.
        if state["status"] == "pending" and time.time() - state["created_at"] > _RECOVERY_TTL:
            _recovery.pop(token, None)
            raise HTTPException(504, "Backend did not respond in time")
        if state["status"] in ("found", "not_found", "expired"):
            _recovery.pop(token, None)
        return {"status": state["status"], "data": state.get("data")}


@app.post("/internal/session/{token}/recovery-data")
async def push_recovery_data(token: str, body: RecoveryData):
    """Backend pushes the resolved recovery payload here. Status is one of
    'found' (payload in `data`), 'not_found', or 'expired'."""
    token = token.strip().upper()
    async with _recovery_lock:
        if token in _recovery:
            _recovery[token] = {
                "status": body.status,
                "data": body.data,
                "created_at": _recovery[token].get("created_at", time.time()),
            }
    return {"status": "ok"}


# --- Session uploads (pull-inverse, HRDD pattern) ---
# React POSTs a file to /internal/upload/{token}. Sidecar stores it locally
# and queues a notification. Backend polls /internal/uploads, GETs each file,
# ingests it, then DELETEs the sidecar's temp copy.

_UPLOAD_MAX_SIZE = 25 * 1024 * 1024  # 25 MB
_upload_dir = Path(tempfile.mkdtemp(prefix="cbc_uploads_"))
_upload_queue: list[dict[str, Any]] = []
_upload_queue_lock = asyncio.Lock()


@app.post("/internal/upload/{session_token}", status_code=201)
async def upload_file(session_token: str, file: UploadFile = File(...)):
    """React app uploads a file for this session. Sidecar stores locally and
    queues it for the backend's next poll. Returns immediately — user sees
    a 'ready' chip, backend ingests in the background within ~2s."""
    if not file.filename:
        raise HTTPException(400, "No filename")
    content = await file.read()
    if len(content) > _UPLOAD_MAX_SIZE:
        raise HTTPException(
            413,
            f"File too large. Max {_UPLOAD_MAX_SIZE // (1024 * 1024)} MB.",
        )
    session_dir = _upload_dir / session_token
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / file.filename).write_bytes(content)
    async with _upload_queue_lock:
        _upload_queue.append({
            "session_token": session_token,
            "filename": file.filename,
            "size": len(content),
            "content_type": file.content_type or "application/octet-stream",
            "created_at": time.time(),
        })
    logger.info(f"Upload received: {file.filename} ({len(content)} bytes) for {session_token}")
    return {"status": "uploaded", "filename": file.filename, "size": len(content)}


@app.get("/internal/uploads")
async def list_pending_uploads():
    """Backend polls this alongside /internal/queue. Returns all pending
    upload notifications and clears the list."""
    async with _upload_queue_lock:
        uploads = list(_upload_queue)
        _upload_queue.clear()
    return {"uploads": uploads}


@app.get("/internal/upload/{session_token}/{filename}")
async def fetch_upload(session_token: str, filename: str):
    """Backend fetches the raw file bytes for ingest."""
    safe_name = Path(filename).name  # strip any directory components
    file_path = _upload_dir / session_token / safe_name
    if not file_path.exists():
        raise HTTPException(404, "Upload not found")
    return FileResponse(file_path)


@app.delete("/internal/upload/{session_token}/{filename}")
async def cleanup_upload(session_token: str, filename: str):
    """Backend signals ingest is done; sidecar removes the temp copy."""
    safe_name = Path(filename).name
    file_path = _upload_dir / session_token / safe_name
    if file_path.exists():
        file_path.unlink()
    session_dir = _upload_dir / session_token
    if session_dir.exists() and not any(session_dir.iterdir()):
        session_dir.rmdir()
    return {"status": "deleted"}
