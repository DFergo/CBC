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

_COMPANIES_FILE = Path("/app/config/companies.json")

# Pushed overrides from the backend cached on disk so they survive restarts.
_DATA_DIR = Path("/app/data")
_BRANDING_CACHE = _DATA_DIR / "pushed_branding.json"
_SESSION_SETTINGS_CACHE = _DATA_DIR / "pushed_session_settings.json"


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

    # Branding: `custom=True` means the pushed payload fully overrides. Otherwise
    # fall back to the baseline JSON's branding block.
    if pushed_branding.get("custom"):
        branding = {k: v for k, v in pushed_branding.items() if k != "custom"}
    else:
        branding = _base_config.get("branding", {})

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

    Body: `{"custom": True, app_title, logo_url, primary_color, secondary_color}`
          or `{"custom": False}` to clear the override and fall back to baseline.
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
        return {"companies": data if isinstance(data, list) else data.get("companies", [])}
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read companies.json: {e}")
        return {"companies": []}


# --- Auth (Sprint 2 stub — real SMTP via backend arrives Sprint 7) ---

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


# --- Survey queue (Sprint 2) ---

MESSAGE_TTL = 300
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
