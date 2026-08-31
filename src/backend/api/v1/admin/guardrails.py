"""Admin read-only view of the runtime guardrails (Sprint 7.5 D4).

Returns the full pattern catalogue + thresholds + sample responses. The
viewer in `GeneralTab.tsx` renders this so admins know what's being
matched without needing to crack open the Python source.

Patterns are source-hardcoded in v1 — admin-editable rules are out of
scope until the tuning exercise shows the default list isn't enough.
"""
from fastapi import APIRouter, Depends

from src.api.v1.admin.auth import require_admin
from src.services import guardrails

router = APIRouter(prefix="/admin/api/v1/guardrails", tags=["admin-guardrails"])


@router.get("")
async def get_all(_admin: dict = Depends(require_admin), language: str = "en"):
    return {
        "categories": guardrails.get_patterns(),
        "thresholds": guardrails.get_thresholds(),
        "sample_responses": guardrails.get_sample_responses(language),
    }
