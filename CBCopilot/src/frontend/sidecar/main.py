# Adapted from HRDDHelper/src/frontend/sidecar/main.py
# Sprint 1 scope: health + config only.
# Message queue, SSE streaming, auth, uploads, recovery land in later sprints
# alongside the React pages that use them.
import json
import logging
import os
from typing import Any

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sidecar")

app = FastAPI(title="CBC Frontend Sidecar", version="0.1.0")

_config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "/app/config/deployment_frontend.json")
_config: dict[str, Any] = {}
if os.path.exists(_config_path):
    with open(_config_path) as f:
        _config = json.load(f)


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
