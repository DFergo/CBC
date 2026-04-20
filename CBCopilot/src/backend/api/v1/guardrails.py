"""Public (non-admin) guardrail endpoint.

Sidecars proxy this so ChatShell can read the current warn / end
thresholds at mount time. Knowing the thresholds isn't sensitive — an
attacker can probe them by counting triggers. The admin-authed endpoint
(`/admin/api/v1/guardrails`) returns the full pattern catalogue too.
"""
from fastapi import APIRouter

from src.services import guardrails

router = APIRouter(prefix="/api/v1/guardrails", tags=["guardrails"])


@router.get("/thresholds")
async def get_thresholds():
    return guardrails.get_thresholds()
