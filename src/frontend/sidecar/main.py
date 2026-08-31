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
_COMPANIES_CACHE = _DATA_DIR / "pushed_companies.json"

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
        "cba_sidepanel_enabled": pick("cba_sidepanel_enabled", True),
        "cba_citations_enabled": pick("cba_citations_enabled", False),
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


# --- Companies (pull-inverse: backend pushes per-frontend list during poll) ---
# The sidecar prefers the pushed list (admin-edited, per-frontend). Falls back
# to the image-shipped /app/config/companies.json only while the backend hasn't
# pushed yet (first boot, or if the frontend isn't registered in the backend).
#
# Compare All is a frontend-level concept — it is NOT a registered company.
# The sidecar prepends a synthetic button entry when listing so the UI can
# render it; the backend is responsible for routing is_compare_all=True to
# the compare_all.md prompt + combined RAG (see resolvers.py).

_COMPARE_ALL_ENTRY = {
    "slug": "compare-all",
    "display_name": "Compare All",
    "enabled": True,
    "is_compare_all": True,
}


@app.post("/internal/companies")
async def push_companies(body: dict[str, Any]):
    """Backend pushes this frontend's company list on every poll cycle (or
    after admin CRUD). Body: {"companies": [...]}. Cached to disk so the list
    survives sidecar restarts even if the backend is briefly offline.

    The backend ships only real (admin-registered) companies — Compare All is
    synthesised by the sidecar on read, not cached here."""
    companies = body.get("companies")
    if not isinstance(companies, list):
        raise HTTPException(400, "body.companies must be a list")
    _write_json(_COMPANIES_CACHE, {"companies": companies})
    logger.info(f"Companies pushed: {len(companies)} entries")
    return {"status": "ok"}


@app.get("/internal/companies")
async def get_companies():
    # Prefer the admin-edited list pushed by the backend.
    cached = _read_json(_COMPANIES_CACHE)
    if isinstance(cached.get("companies"), list):
        items = list(cached["companies"])
    elif _COMPANIES_FILE.exists():
        try:
            data = json.loads(_COMPANIES_FILE.read_text())
            items = data if isinstance(data, list) else data.get("companies", [])
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read companies.json: {e}")
            items = []
    else:
        items = []
    # Drop any stray is_compare_all entries the admin might have registered
    # accidentally — Compare All lives outside the company registry.
    items = [c for c in items if not c.get("is_compare_all")]
    items.sort(key=lambda c: (c.get("display_name") or c.get("slug") or "").lower())
    # Always prepend the synthetic Compare All button. The React
    # CompanySelectPage hides it when the `compare_all_enabled` deployment
    # flag is off.
    return {"companies": [dict(_COMPARE_ALL_ENTRY), *items]}


# --- Auth (pull-inverse, HRDD pattern, Sprint 10B) ---
# React POSTs request-code or verify-code → sidecar queues an auth_request
# in /internal/queue. Backend polling drains it, calls process_request_code /
# process_verify_code (auth.py), POSTs the result here at /result. React
# polls /status/{session_token} to see when the result lands.
#
# State machine for /status:
#   none      - no request pending
#   pending   - request queued, backend hasn't resolved yet
#   verifying - verify request queued, backend hasn't resolved yet
#   code_sent - backend issued the code (dev_code may be present)
#   verified  - code accepted, email persisted
#   invalid_code | not_authorized | smtp_error | smtp_not_configured | error
#             - terminal failure states; React shows the error and lets user retry

_auth_requests: dict[str, dict[str, Any]] = {}
_auth_queue: list[dict[str, Any]] = []
_auth_lock = asyncio.Lock()
_AUTH_TTL = 600.0  # how long pending state lives in memory before GC


class AuthRequestCode(BaseModel):
    session_token: str
    email: str
    language: str = "en"


class AuthVerifyCode(BaseModel):
    session_token: str
    code: str
    language: str = "en"


class AuthResultPush(BaseModel):
    status: str
    email: str = ""
    dev_code: str = ""
    detail: str = ""


@app.post("/internal/auth/request-code")
async def request_auth_code(req: AuthRequestCode):
    """React queues a code-request. Backend resolves on its next poll
    (~2 s) and POSTs the result back to /internal/auth/{token}/result."""
    if not req.session_token.strip() or not req.email.strip():
        raise HTTPException(400, "session_token and email required")
    async with _auth_lock:
        _auth_requests[req.session_token] = {
            "status": "pending",
            "email": req.email.strip().lower(),
            "created_at": time.time(),
        }
        _auth_queue.append({
            "session_token": req.session_token,
            "email": req.email,
            "language": req.language,
            "frontend_id": _base_config.get("frontend_id", ""),
            "kind": "request_code",
        })
    logger.info(f"Auth code requested: email={req.email} session={req.session_token}")
    return {"status": "pending"}


@app.post("/internal/auth/verify-code")
async def verify_auth_code(req: AuthVerifyCode):
    """React queues a code-verify attempt. Same flow as request-code."""
    if not req.session_token.strip() or not req.code.strip():
        raise HTTPException(400, "session_token and code required")
    async with _auth_lock:
        existing = _auth_requests.get(req.session_token, {})
        _auth_requests[req.session_token] = {
            "status": "verifying",
            "email": existing.get("email", ""),
            "created_at": time.time(),
        }
        _auth_queue.append({
            "session_token": req.session_token,
            "code": req.code,
            "email": existing.get("email", ""),
            "language": req.language,
            "kind": "verify_code",
        })
    logger.info(f"Auth verify queued: session={req.session_token}")
    return {"status": "verifying"}


@app.get("/internal/auth/status/{session_token}")
async def get_auth_status(session_token: str):
    """React polls this every ~400 ms after sending a code request / verify
    attempt to find out what the backend decided. Returns the cached state
    or {"status": "none"} when there's no pending or recent request.

    Terminal states (verified, invalid_code, etc.) are NOT auto-cleared —
    the React app just stops polling. The 10-min GC in /result handles
    eventual cleanup."""
    async with _auth_lock:
        state = _auth_requests.get(session_token)
        if state and time.time() - state["created_at"] > _AUTH_TTL:
            _auth_requests.pop(session_token, None)
            state = None
    if not state:
        return {"status": "none"}
    return {
        "status": state["status"],
        "email": state.get("email", ""),
        "dev_code": state.get("dev_code", ""),
        "detail": state.get("detail", ""),
    }


@app.post("/internal/auth/{session_token}/result")
async def push_auth_result(session_token: str, body: AuthResultPush):
    """Backend pushes the resolved result here after processing a queued
    auth request. Schedules a GC of the entry after the TTL so the dict
    doesn't grow unbounded."""
    async with _auth_lock:
        existing = _auth_requests.get(session_token, {})
        _auth_requests[session_token] = {
            "status": body.status,
            "email": body.email or existing.get("email", ""),
            "dev_code": body.dev_code,
            "detail": body.detail,
            "created_at": time.time(),
        }
    logger.info(f"Auth result pushed for {session_token}: {body.status}")

    async def _gc() -> None:
        await asyncio.sleep(_AUTH_TTL)
        async with _auth_lock:
            _auth_requests.pop(session_token, None)
    asyncio.create_task(_gc())

    return {"status": "ok"}


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


# Sprint 13 — cancellation signals.
#
# React → POST /internal/chat/cancel/{session_token} when the user clicks Stop.
# The token lands in _cancellations with a timestamp. The backend's per-turn
# cancel-watcher (separate from the main polling loop, so it can fire while a
# stream is in flight) drains via GET /internal/cancellations every ~1 s and
# checks whether its own session is listed.
_cancellations: dict[str, float] = {}
_cancel_lock = asyncio.Lock()
_CANCEL_TTL = 30.0  # drop signals older than this if no poll picked them up


@app.post("/internal/chat/cancel/{session_token}")
async def cancel_chat(session_token: str):
    """User clicked Stop. Mark the token cancelled; the backend's in-flight
    stream watcher will see it within ~1 s and abort."""
    token = (session_token or "").strip()
    if not token:
        raise HTTPException(400, "session_token required")
    async with _cancel_lock:
        _cancellations[token] = time.time()
    logger.info(f"Cancel requested for session {token}")
    return {"status": "queued"}


@app.get("/internal/cancellations")
async def drain_cancellations():
    """Backend per-turn cancel-watcher polls this. Returns and clears all
    pending cancellation signals (older than _CANCEL_TTL are dropped silently
    so a long-stale signal doesn't kill an unrelated future turn).

    Deliberately NOT bundled into /internal/queue: that endpoint runs on a 2 s
    main-poll cycle and only fires between turns. A user clicking Stop while
    a stream is in flight needs a faster, dedicated channel."""
    now = time.time()
    async with _cancel_lock:
        fresh = [tok for tok, ts in _cancellations.items() if now - ts < _CANCEL_TTL]
        _cancellations.clear()
    return {"cancellations": fresh}


@app.get("/internal/queue")
async def dequeue_messages():
    """Backend poll target — drains pending chat/survey/close messages and
    surfaces pending recovery_requests (tokens), auth_requests, and
    document_requests (CBA sidepanel downloads) so the backend can resolve
    them in the same tick."""
    now = time.time()
    async with _queue_lock:
        valid = [m for m in _queue if now - m["created_at"] < MESSAGE_TTL]
        _queue.clear()
    async with _recovery_lock:
        pending_tokens = [tok for tok, s in _recovery.items() if s["status"] == "pending"]
    async with _auth_lock:
        auth_drain = list(_auth_queue)
        _auth_queue.clear()
    async with _document_lock:
        doc_drain = list(_document_queue)
        _document_queue.clear()
    result: dict[str, Any] = {"messages": valid}
    if pending_tokens:
        result["recovery_requests"] = pending_tokens
    if auth_drain:
        result["auth_requests"] = auth_drain
    if doc_drain:
        result["document_requests"] = doc_drain
    return result


# Sprint 13 — queue position lookup for the "esperando turno" indicator.
#
# Cheap O(N) walk over the chat queue (which is ~empty most of the time and
# only fills when N concurrent users on the same frontend press Send). Returns
# the position of the user's OLDEST pending chat message, where 0 = next up.
# When there's nothing for this token, returns position=-1.

@app.get("/internal/queue/position/{session_token}")
async def queue_position(session_token: str):
    """Where am I in the queue? React polls this every couple of seconds
    while waiting for the first token. Position = number of OTHER chat
    messages ahead of this user's oldest pending one. -1 = not in queue
    (already processed, or never enqueued)."""
    token = (session_token or "").strip()
    if not token:
        raise HTTPException(400, "session_token required")
    async with _queue_lock:
        chat_queue = [m for m in _queue if m.get("type") == "chat"]
    own_idx = -1
    for i, m in enumerate(chat_queue):
        if m.get("session_token") == token:
            own_idx = i
            break
    if own_idx == -1:
        return {"position": -1, "total": len(chat_queue)}
    return {"position": own_idx, "total": len(chat_queue)}


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
    """Backend pushes one SSE event. Terminal events (`done`, `error`,
    `cancelled`) close the SSE connection and schedule queue cleanup so the
    next user turn starts on a fresh stream."""
    q = await _get_or_create_stream(session_token)
    await q.put({"event": chunk.event, "data": chunk.data})
    if chunk.event in ("done", "error", "cancelled"):
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
                if event["event"] in ("done", "error", "cancelled"):
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


# --- CBA document downloads (pull-inverse, Sprint 11) ---
# React requests a doc download by (scope_key, filename). Sidecar queues a
# document_request in /internal/queue. Backend polls, reads the file from
# disk, POSTs the bytes back to /internal/document/{request_id}/result.
# React polls /internal/document/{request_id} which returns 202 "pending"
# until the bytes arrive, then 200 with the file body.

_DOCUMENT_DIR = Path(tempfile.mkdtemp(prefix="cbc_documents_"))
_document_requests: dict[str, dict[str, Any]] = {}
_document_queue: list[dict[str, Any]] = []
_document_lock = asyncio.Lock()
_DOCUMENT_TTL = 120.0


class DocumentRequest(BaseModel):
    scope_key: str
    filename: str


@app.post("/internal/document-request")
async def queue_document_request(req: DocumentRequest):
    """React queues a download. Returns a request_id the UI will poll."""
    if not req.scope_key.strip() or not req.filename.strip():
        raise HTTPException(400, "scope_key and filename required")
    request_id = f"{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    async with _document_lock:
        _document_requests[request_id] = {
            "status": "pending",
            "scope_key": req.scope_key,
            "filename": req.filename,
            "created_at": time.time(),
        }
        _document_queue.append({
            "request_id": request_id,
            "scope_key": req.scope_key,
            "filename": req.filename,
        })
    logger.info(f"Document request queued: {request_id} {req.scope_key}/{req.filename}")
    return {"request_id": request_id, "status": "pending"}


@app.get("/internal/document/{request_id}")
async def poll_document(request_id: str):
    """React polls this every ~500 ms after queueing a document-request. While
    the backend hasn't pushed the bytes back we return 202 pending. Once the
    file is here we stream it as a FileResponse."""
    async with _document_lock:
        state = _document_requests.get(request_id)
        if state and time.time() - state["created_at"] > _DOCUMENT_TTL:
            _document_requests.pop(request_id, None)
            state = None
    if not state:
        raise HTTPException(404, "Unknown or expired document request")
    if state["status"] != "ready":
        # FastAPI returns 202 JSON; React loops until it sees a non-JSON body.
        return {"status": state["status"], "detail": state.get("detail", "")}
    path = _DOCUMENT_DIR / request_id / state["filename"]
    if not path.exists():
        raise HTTPException(500, "Document file missing on sidecar")
    return FileResponse(
        path,
        filename=state["filename"],
        media_type=state.get("content_type") or "application/octet-stream",
    )


@app.post("/internal/document/{request_id}/result")
async def push_document_bytes(request_id: str, file: UploadFile = File(...)):
    """Backend pushes the fetched file here. Stored under a per-request dir
    so the cleanup task knows exactly what to remove on TTL expiry."""
    async with _document_lock:
        state = _document_requests.get(request_id)
    if not state:
        raise HTTPException(404, "Unknown document request")
    target_dir = _DOCUMENT_DIR / request_id
    target_dir.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    (target_dir / state["filename"]).write_bytes(content)
    async with _document_lock:
        st = _document_requests.get(request_id)
        if st:
            st["status"] = "ready"
            st["size"] = len(content)
            st["content_type"] = file.content_type or "application/octet-stream"

    async def _gc() -> None:
        await asyncio.sleep(_DOCUMENT_TTL)
        async with _document_lock:
            _document_requests.pop(request_id, None)
        try:
            if target_dir.exists():
                for p in target_dir.iterdir():
                    p.unlink(missing_ok=True)
                target_dir.rmdir()
        except OSError:
            pass
    asyncio.create_task(_gc())
    logger.info(f"Document bytes received for {request_id}: {len(content)} bytes")
    return {"status": "ok"}


@app.post("/internal/document/{request_id}/error")
async def push_document_error(request_id: str, body: dict[str, Any]):
    """Backend couldn't fetch the file — surface to React via status poll."""
    async with _document_lock:
        st = _document_requests.get(request_id)
        if st:
            st["status"] = "error"
            st["detail"] = str(body.get("detail") or "backend could not fetch the file")
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
