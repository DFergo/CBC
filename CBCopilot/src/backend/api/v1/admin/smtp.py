"""Admin SMTP configuration + test send + per-frontend notification override."""
from fastapi import APIRouter, Depends, HTTPException

from src.api.v1.admin.auth import require_admin
from src.services import smtp_service
from src.services.smtp_service import FrontendNotificationOverride, SMTPConfig

router = APIRouter(prefix="/admin/api/v1/smtp", tags=["admin-smtp"])


@router.get("")
async def get_config(_admin: dict = Depends(require_admin)):
    cfg = smtp_service.load_config()
    return smtp_service.redact_for_response(cfg)


@router.put("")
async def save_config(cfg: SMTPConfig, _admin: dict = Depends(require_admin)):
    if cfg.password == "***":
        existing = smtp_service.load_config()
        cfg = cfg.model_copy(update={"password": existing.password})
    smtp_service.save_config(cfg)
    return smtp_service.redact_for_response(cfg)


@router.post("/test")
async def test_send(_admin: dict = Depends(require_admin)):
    return await smtp_service.send_test()


# --- Per-frontend notification override (admin recipients only) ---

@router.get("/frontend/{frontend_id}")
async def get_frontend_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    override = smtp_service.load_frontend_override(frontend_id)
    return {
        "frontend_id": frontend_id,
        "override": override.model_dump() if override else None,
        "resolved_admin_emails": smtp_service.resolve_admin_emails(frontend_id),
    }


@router.put("/frontend/{frontend_id}")
async def put_frontend_override(
    frontend_id: str,
    override: FrontendNotificationOverride,
    _admin: dict = Depends(require_admin),
):
    smtp_service.save_frontend_override(frontend_id, override)
    return {
        "frontend_id": frontend_id,
        "override": override.model_dump(),
        "resolved_admin_emails": smtp_service.resolve_admin_emails(frontend_id),
    }


@router.delete("/frontend/{frontend_id}")
async def delete_frontend_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    removed = smtp_service.delete_frontend_override(frontend_id)
    if not removed:
        raise HTTPException(404, f"No override exists for frontend {frontend_id!r}")
    return {"frontend_id": frontend_id, "removed": True}


