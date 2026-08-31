"""Authorized contacts directory (adapted from HRDD's contacts system).

Schema:
- Global list of contacts (authoritative allowlist when no per-frontend override)
- Per-frontend overrides with `replace` or `append` mode

Storage: /app/data/contacts.json
    {
        "global": [Contact, ...],
        "per_frontend": {
            "packaging-eu": {"mode": "replace" | "append", "contacts": [Contact, ...]}
        }
    }

Contact fields mirror HRDD exactly so the xlsx template is portable between apps.
"""
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.services._paths import DATA_DIR, atomic_write_json, read_json

logger = logging.getLogger("contacts_store")

CONTACTS_FILE = DATA_DIR / "contacts.json"

CONTACT_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "organization",
    "country",
    "sector",
    "registered_by",
)

OverrideMode = Literal["replace", "append"]


class Contact(BaseModel):
    email: str
    first_name: str = ""
    last_name: str = ""
    organization: str = ""
    country: str = ""
    sector: str = ""
    registered_by: str = ""


class FrontendOverride(BaseModel):
    mode: OverrideMode = "replace"
    contacts: list[Contact] = Field(default_factory=list)


def _normalise_contact(raw: dict[str, Any]) -> dict[str, str] | None:
    """Accept a loose dict (e.g. from xlsx/csv row), normalise to CONTACT_FIELDS.

    Returns None if the email field is missing or empty.
    """
    norm: dict[str, str] = {}
    email = str(raw.get("email", "") or "").strip().lower()
    if not email:
        return None
    norm["email"] = email
    for f in CONTACT_FIELDS:
        if f == "email":
            continue
        v = raw.get(f, "")
        norm[f] = str(v or "").strip()
    return norm


def _sanitise_list(contacts: list[Any]) -> list[dict[str, str]]:
    """Drop invalid entries, normalise fields, dedupe by email (last wins)."""
    seen: dict[str, dict[str, str]] = {}
    for raw in contacts:
        if isinstance(raw, dict):
            c = _normalise_contact(raw)
        elif isinstance(raw, Contact):
            c = _normalise_contact(raw.model_dump())
        else:
            c = None
        if c:
            seen[c["email"]] = c
    return list(seen.values())


def load() -> dict[str, Any]:
    data = read_json(CONTACTS_FILE, default=None)
    if not isinstance(data, dict):
        return {"global": [], "per_frontend": {}}
    return {
        "global": data.get("global", []) if isinstance(data.get("global"), list) else [],
        "per_frontend": data.get("per_frontend", {}) if isinstance(data.get("per_frontend"), dict) else {},
    }


def save(store: dict[str, Any]) -> dict[str, Any]:
    """Sanitise and persist. Returns the cleaned store."""
    clean: dict[str, Any] = {
        "global": _sanitise_list(store.get("global", [])),
        "per_frontend": {},
    }
    for fid, override in (store.get("per_frontend") or {}).items():
        if not isinstance(override, dict):
            continue
        mode = override.get("mode", "replace")
        if mode not in ("replace", "append"):
            mode = "replace"
        clean["per_frontend"][fid] = {
            "mode": mode,
            "contacts": _sanitise_list(override.get("contacts", [])),
        }
    atomic_write_json(CONTACTS_FILE, clean)
    return clean


def contacts_for_scope(store: dict[str, Any], scope: str) -> list[dict[str, str]]:
    """Read the contacts list for a scope literal: 'global' or 'frontend:<id>'."""
    if scope == "global":
        return list(store.get("global", []))
    if scope.startswith("frontend:"):
        fid = scope.split(":", 1)[1]
        return list((store.get("per_frontend") or {}).get(fid, {}).get("contacts", []))
    raise ValueError(f"Invalid scope: {scope!r}")


def resolved_allowlist(store: dict[str, Any], frontend_id: str) -> list[dict[str, str]]:
    """Return the effective contacts list for a frontend, honouring mode.

    - No override → global
    - mode='replace' → per-frontend list only
    - mode='append' → global + per-frontend, deduped by email
    """
    pf = (store.get("per_frontend") or {}).get(frontend_id)
    if not pf:
        return list(store.get("global", []))
    mode = pf.get("mode", "replace")
    frontend_list = list(pf.get("contacts", []))
    if mode == "replace":
        return frontend_list
    # append
    by_email: dict[str, dict[str, str]] = {c["email"]: c for c in store.get("global", [])}
    for c in frontend_list:
        by_email[c["email"]] = c
    return list(by_email.values())
