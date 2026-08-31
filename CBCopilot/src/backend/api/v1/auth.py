"""Email-code auth for end users (session-scoped).

The flow is pull-inverse end to end (Sprint 10B). Sidecars queue auth
requests in `/internal/queue`; the backend polling loop drains them and
calls `process_request_code` / `process_verify_code` from this module
directly, then POSTs the result back to `/internal/auth/{token}/result`
on the sidecar. The HTTP endpoints below stay as a small admin-side
debug surface but the sidecar no longer hits them.

We:
1. Check the Contacts allowlist (SPEC §4.11) when `auth_allowlist_enabled`.
2. Generate a 6-digit code with a TTL (default 15 min).
3. Send it via SMTP if `smtp_service.is_configured()`.
4. If SMTP is offline (bootstrap / demo), return the code inline as
   `dev_code` so the AuthPage's amber banner can keep working (D7=A).

No JWT, no session persistence — the code verification just writes the
verified email into the session's survey record. Admin-panel auth is a
separate story (bcrypt + JWT, already in place from Sprint 1).
"""
import logging
import random
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from src.core.config import config
from src.services import contacts_store, smtp_service

logger = logging.getLogger("api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RequestCodeBody(BaseModel):
    session_token: str
    email: EmailStr
    language: str = "en"
    frontend_id: str = ""


class VerifyCodeBody(BaseModel):
    session_token: str
    code: str


# In-memory code store: session_token -> {email, code, expires_at}
# Single-process, not persisted. Restart = all pending codes invalidated
# (users just ask for a new one).
_codes: dict[str, dict[str, Any]] = {}
_codes_lock = threading.Lock()


def _gen_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _is_email_allowed(email: str, frontend_id: str) -> bool:
    """Check the resolved Contacts allowlist (global + per-frontend) for the
    given frontend. Case-insensitive email match. Returns True when the
    allowlist is disabled entirely (bootstrap toggle)."""
    if not config.auth_allowlist_enabled:
        return True
    try:
        store = contacts_store.load()
        allowed = contacts_store.resolved_allowlist(store, frontend_id)
    except Exception as e:
        logger.warning(f"Contacts allowlist lookup failed ({e}); denying by default")
        return False
    target = email.strip().lower()
    return any((c.get("email") or "").strip().lower() == target for c in allowed)


# --- Internal API used by the polling loop (pull-inverse path) ---

async def process_request_code(
    session_token: str,
    email: str,
    language: str,
    frontend_id: str,
) -> dict[str, Any]:
    """Pure backend logic — generates a code, persists, sends or returns dev_code.
    Used by both the HTTP endpoint (legacy) and the polling loop's
    `_handle_auth_request`. Never raises; returns a status dict the sidecar
    will push back to the React app verbatim.
    """
    email = (email or "").strip().lower()
    session_token = (session_token or "").strip()
    if not session_token:
        return {"status": "error", "detail": "session_token is required"}

    if not _is_email_allowed(email, frontend_id):
        logger.info(f"Auth denied (not in allowlist): email={email} frontend={frontend_id!r}")
        return {"status": "not_authorized", "email": email}

    code = _gen_code()
    with _codes_lock:
        _codes[session_token] = {
            "email": email,
            "code": code,
            "expires_at": time.time() + config.auth_code_ttl_seconds,
        }

    response: dict[str, Any] = {"status": "code_sent", "email": email}

    if smtp_service.is_configured():
        subject = "Your Collective Bargaining Copilot verification code"
        textlines = [
            f"Your verification code is: {code}",
            "",
            f"It expires in {config.auth_code_ttl_seconds // 60} minutes.",
            "",
            "If you didn't request this, you can ignore the message.",
        ]
        try:
            await smtp_service.send_email(
                to_address=email,
                subject=subject,
                body="\n".join(textlines),
            )
            logger.info(f"Auth code emailed: email={email} session={session_token}")
        except Exception as e:
            # SMTP transient failure — fall back to dev_code so the user isn't
            # stuck. Admin will see the error in logs.
            logger.warning(f"SMTP send failed ({e}); falling back to dev_code")
            response["dev_code"] = code
    else:
        logger.info(
            f"[DEV] SMTP not configured; returning dev_code. "
            f"email={email} session={session_token} code={code}"
        )
        response["dev_code"] = code

    return response


def process_verify_code(session_token: str, code: str) -> dict[str, Any]:
    """Pure backend logic — checks the in-memory code store, burns on success.
    Synchronous (no async I/O). Used by both the HTTP endpoint and the
    polling auth handler.
    """
    session_token = (session_token or "").strip()
    code = (code or "").strip()

    with _codes_lock:
        entry = _codes.get(session_token)
        if not entry:
            return {"status": "invalid_code"}
        if entry["expires_at"] < time.time():
            _codes.pop(session_token, None)
            return {"status": "invalid_code"}
        if entry["code"] != code:
            return {"status": "invalid_code"}
        # One-shot — burn after successful verify
        email = entry["email"]
        _codes.pop(session_token, None)

    logger.info(f"Auth code verified: session={session_token} email={email}")
    return {"status": "verified", "email": email}


# --- HTTP endpoints (legacy thin wrappers) ---
# Kept so you can curl the backend directly from an admin shell while
# debugging. The sidecar no longer hits these — see polling._handle_auth_request.

@router.post("/request-code")
async def request_code(body: RequestCodeBody):
    if not body.session_token.strip():
        raise HTTPException(status_code=400, detail="session_token is required")
    result = await process_request_code(
        body.session_token, body.email, body.language, body.frontend_id,
    )
    if result.get("status") == "not_authorized":
        raise HTTPException(
            status_code=403,
            detail="This email is not authorized for this deployment. Contact your administrator.",
        )
    return result


@router.post("/verify-code")
async def verify_code(body: VerifyCodeBody):
    return process_verify_code(body.session_token, body.code)
