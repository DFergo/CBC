# Adapted from HRDDHelper/src/frontend/sidecar/main.py
# Sprint 2: health, config, companies, auth stubs, survey queue.
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

app = FastAPI(title="CBC Frontend Sidecar", version="0.2.0")

_config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "/app/config/deployment_frontend.json")
_config: dict[str, Any] = {}
if os.path.exists(_config_path):
    with open(_config_path) as f:
        _config = json.load(f)

_COMPANIES_FILE = Path("/app/config/companies.json")


@app.get("/internal/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/config")
async def get_config():
    return {
        "role": "frontend",
        "frontend_id": _config.get("frontend_id", "default"),
        "auth_required": _config.get("auth_required", True),
        "disclaimer_enabled": _config.get("disclaimer_enabled", True),
        "instructions_enabled": _config.get("instructions_enabled", True),
        "compare_all_enabled": _config.get("compare_all_enabled", True),
        "session_resume_hours": _config.get("session_resume_hours", 48),
        "branding": _config.get("branding", {}),
    }


# --- Companies (Sprint 2: sidecar-local stub; Sprint 3 moves this to backend) ---

@app.get("/internal/companies")
async def get_companies():
    if not _COMPANIES_FILE.exists():
        return {"companies": []}
    try:
        data = json.loads(_COMPANIES_FILE.read_text())
        return {"companies": data if isinstance(data, list) else data.get("companies", [])}
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read companies.json: {e}")
        return {"companies": []}


# --- Auth (Sprint 2 stub — real SMTP via backend arrives Sprint 7) ---
# Codes live in-memory on the sidecar. Response includes `dev_code` so the
# frontend can show it in a dev banner. Remove `dev_code` when Sprint 7 wires
# real email delivery.

_auth_codes: dict[str, str] = {}


class AuthRequestCode(BaseModel):
    session_token: str
    email: str


class AuthVerifyCode(BaseModel):
    session_token: str
    code: str


@app.post("/internal/auth/request-code")
async def request_auth_code(req: AuthRequestCode):
    code = f"{random.randint(0, 999999):06d}"
    _auth_codes[req.session_token] = code
    logger.info(f"[DEV STUB] Auth code for {req.email} ({req.session_token}): {code}")
    return {"status": "code_sent", "dev_code": code}


@app.post("/internal/auth/verify-code")
async def verify_auth_code(req: AuthVerifyCode):
    expected = _auth_codes.get(req.session_token)
    if expected and req.code == expected:
        _auth_codes.pop(req.session_token, None)
        return {"status": "verified"}
    return {"status": "invalid_code"}


# --- Survey queue (Sprint 2: enqueue survey; backend consumes from Sprint 6) ---

MESSAGE_TTL = 300  # seconds
_queue: list[dict[str, Any]] = []
_queue_lock = asyncio.Lock()


class SurveySubmit(BaseModel):
    session_token: str
    survey: dict[str, Any]
    language: str = "en"


@app.post("/internal/queue")
async def enqueue_message(msg: SurveySubmit):
    async with _queue_lock:
        _queue.append({**msg.model_dump(), "created_at": time.time()})
    logger.info(
        f"Survey submitted: session={msg.session_token} "
        f"company={msg.survey.get('company_slug')} "
        f"country={msg.survey.get('country')} "
        f"query={(msg.survey.get('initial_query') or '')[:60]}..."
    )
    return {"status": "queued"}


@app.get("/internal/queue")
async def dequeue_messages():
    now = time.time()
    async with _queue_lock:
        valid = [m for m in _queue if now - m["created_at"] < MESSAGE_TTL]
        _queue.clear()
    return {"messages": valid}
