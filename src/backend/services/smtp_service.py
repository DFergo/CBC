"""SMTP configuration + test send + notification routing.

Global config:
    host / port / username / password / use_tls / from_address
    admin_notification_emails: list[str]  — recipients for admin notifications
    send_summary_to_user: bool            — email user their session summary
    send_summary_to_admin: bool           — email admin(s) the session summary
    send_new_document_to_admin: bool      — email admin(s) on user doc upload

Per-frontend override (notifications.json under /app/data/campaigns/{fid}/):
    admin_emails_mode: "replace" | "append"
    admin_notification_emails: list[str]

Resolution: when a frontend triggers a notification, call `resolve_admin_emails(fid)`
to get the effective recipient list (global, or per-frontend replace/append).
The three toggles are global only — per-frontend overrides affect RECIPIENTS,
not whether a notification fires.

Password is stored on the data volume (not committed). API key env-var pattern
from SPEC §8.3 could be applied in a future sprint if desired.
"""
import logging
from pathlib import Path
from typing import Any, Literal

import aiosmtplib
from email.message import EmailMessage
from pydantic import BaseModel, Field

from src.services._paths import (
    SMTP_CONFIG_FILE,
    atomic_write_json,
    frontend_dir,
    read_json,
)

logger = logging.getLogger("smtp")


class SMTPConfig(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_address: str = ""
    admin_notification_emails: list[str] = Field(default_factory=list)
    send_summary_to_user: bool = True
    send_summary_to_admin: bool = False
    send_new_document_to_admin: bool = True


class FrontendNotificationOverride(BaseModel):
    admin_emails_mode: Literal["replace", "append"] = "replace"
    admin_notification_emails: list[str] = Field(default_factory=list)


def _notifications_file(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "notifications.json"


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Sprint 3 shipped with `authorized_emails` in SMTP config (moved to Contacts).
    Drop it silently on load so the field doesn't surface in the UI.
    """
    data.pop("authorized_emails", None)
    return data


def load_config() -> SMTPConfig:
    data = read_json(SMTP_CONFIG_FILE)
    if not isinstance(data, dict):
        return SMTPConfig()
    try:
        return SMTPConfig(**_migrate_legacy(data))
    except Exception as e:
        logger.warning(f"Invalid smtp_config.json ({e}); returning defaults")
        return SMTPConfig()


def save_config(cfg: SMTPConfig) -> None:
    atomic_write_json(SMTP_CONFIG_FILE, cfg.model_dump())
    logger.info("SMTP config saved")


def redact_for_response(cfg: SMTPConfig) -> dict[str, Any]:
    data = cfg.model_dump()
    data["password"] = "***" if cfg.password else ""
    return data


def is_configured(cfg: SMTPConfig | None = None) -> bool:
    c = cfg if cfg is not None else load_config()
    return bool(c.host and c.from_address)


# --- Per-frontend notification override ---

def load_frontend_override(frontend_id: str) -> FrontendNotificationOverride | None:
    data = read_json(_notifications_file(frontend_id))
    if not isinstance(data, dict):
        return None
    try:
        return FrontendNotificationOverride(**data)
    except Exception as e:
        logger.warning(f"Invalid notifications.json for {frontend_id}: {e}")
        return None


def save_frontend_override(frontend_id: str, override: FrontendNotificationOverride) -> None:
    atomic_write_json(_notifications_file(frontend_id), override.model_dump())
    logger.info(f"Notification override saved for frontend {frontend_id}")


def delete_frontend_override(frontend_id: str) -> bool:
    path = _notifications_file(frontend_id)
    if path.exists():
        path.unlink()
        logger.info(f"Notification override removed for frontend {frontend_id}")
        return True
    return False


def resolve_admin_emails(frontend_id: str | None = None) -> list[str]:
    """Final list of admin recipients for a notification.

    - No frontend → global list
    - Frontend without override → global list
    - replace mode → per-frontend list only
    - append mode → global + per-frontend, deduped (preserves global order)
    """
    cfg = load_config()
    global_list = list(cfg.admin_notification_emails)
    if not frontend_id:
        return global_list
    override = load_frontend_override(frontend_id)
    if not override:
        return global_list
    if override.admin_emails_mode == "replace":
        return list(override.admin_notification_emails)
    # append
    merged = list(global_list)
    for e in override.admin_notification_emails:
        if e not in merged:
            merged.append(e)
    return merged


# --- Sending ---

async def send_email(
    to_address: str | list[str],
    subject: str,
    body: str,
    cfg: SMTPConfig | None = None,
) -> None:
    c = cfg if cfg is not None else load_config()
    if not is_configured(c):
        raise RuntimeError("SMTP is not configured")

    recipients = [to_address] if isinstance(to_address, str) else list(to_address)
    if not recipients:
        raise ValueError("No recipients")

    msg = EmailMessage()
    msg["From"] = c.from_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=c.host,
        port=c.port,
        username=c.username or None,
        password=c.password or None,
        start_tls=c.use_tls,
    )


async def send_test(cfg: SMTPConfig | None = None) -> dict[str, Any]:
    c = cfg if cfg is not None else load_config()
    if not is_configured(c):
        return {"ok": False, "error": "SMTP is not configured (host or from_address missing)"}
    try:
        await send_email(
            to_address=c.from_address,
            subject="CBC — SMTP test",
            body="This is a test message from the CBC admin panel. If you received this, SMTP is working.",
            cfg=c,
        )
        return {"ok": True}
    except Exception as e:
        logger.warning(f"SMTP test failed: {e}")
        return {"ok": False, "error": str(e)}


async def check_smtp_health() -> None:
    c = load_config()
    if not is_configured(c):
        logger.info("SMTP not configured (skipping startup check)")
        return
    try:
        smtp = aiosmtplib.SMTP(hostname=c.host, port=c.port, start_tls=c.use_tls, timeout=5)
        await smtp.connect()
        await smtp.quit()
        logger.info("SMTP startup check: OK")
    except Exception as e:
        logger.warning(f"SMTP startup check failed: {e}")
