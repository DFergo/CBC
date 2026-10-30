"""Admin: frontend registry CRUD + per-frontend branding + session settings.

Primary key is `frontend_id` — the stable string the frontend uses in its own
`deployment_frontend.json` (e.g. "packaging-eu"). Same ID keys
/app/data/campaigns/{frontend_id}/ where all per-frontend config lives.

Per-frontend config changes are pushed to the sidecar on save so they take
effect immediately (HRDD push pattern, not polling).
"""
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.api.v1.admin.branding import TranslationBundle
from src.services import (
    branding_store,
    llm_override_store,
    orgs_override_store,
    rag_settings_store,
    resolvers,
    session_settings_store,
)
from src.services.branding_store import Branding
from src.services import frontend_client
from src.services.frontend_registry import registry
from src.services.llm_override_store import LLMOverride
from src.services.orgs_override_store import OrgsOverride
from src.services.rag_settings_store import RAGSettings
from src.services.session_settings_store import SessionSettings

logger = logging.getLogger("admin.frontends")

router = APIRouter(prefix="/admin/api/v1/frontends", tags=["admin-frontends"])

PUSH_TIMEOUT = 5.0
# Reachability + auth probe: the sidecar must answer GET config with the
# entry's final mode. Generous timeout — a frontend that just came up over a
# slow office LAN shouldn't be rejected as unreachable.
CONFIG_PROBE_TIMEOUT = 10.0

MIN_SECRET_LENGTH = frontend_client.MIN_SECRET_LENGTH
_CRED_FIELDS = {"auth_mode", "signing_secret", "extra_headers"}


async def _probe(url: str, entry: dict[str, Any]) -> None:
    """Confirm a frontend URL is reachable AND accepts the entry's mode before
    the registry points at it (adapted from HRDDHelper admin/frontends.py).

    Probes `GET {url}/internal/config`; the client rewrites it to
    `/backend/v1/config` (signed or not) unless the mode is legacy. Host-
    agnostic: works for an IP, a hostname, a `.local` name or a Tailscale
    MagicDNS name — we decide on reachability, never on the shape of the
    string. (Caveat: the backend container may not resolve `.local` names
    even if the host can — that's why the reconciler can pass `?verify=false`
    and push a pre-resolved IP.)
    """
    mode = frontend_client.auth_mode(entry)
    try:
        async with frontend_client.ProbeClient(entry, timeout=CONFIG_PROBE_TIMEOUT) as client:
            r = await client.get(f"{url.rstrip('/')}/internal/config")
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 401 and mode == frontend_client.MODE_SIGNED:
            detail = (f"Frontend at {url} rejected the signature — check that its CBC_BACKEND_SECRET matches "
                      f"this frontend's secret (or CBC_FRONTEND_SECRET here) and that both clocks are in sync")
        elif code == 401:
            detail = (f"Frontend at {url} requires signed requests — choose 'Signed', or start the frontend "
                      f"with BACKEND_SURFACE_AUTH=trusted-network")
        elif code == 404 and mode != frontend_client.MODE_LEGACY:
            detail = (f"No backend surface at {url} — use the frontend's backend port (container port 8080), "
                      f"not the public one; a frontend on the old image needs mode 'Legacy'")
        else:
            detail = f"URL not reachable ({url}): {e}"
        raise HTTPException(400, detail)
    except httpx.HTTPError as e:
        raise HTTPException(400, f"URL not reachable ({url}): {e}")


async def _push(frontend_id: str, path: str, body: dict[str, Any]) -> None:
    """POST to the sidecar. Logs on failure — admin save shouldn't fail just
    because the sidecar is momentarily offline (it'll pick up the override
    from disk on its next boot or periodic refresh).
    """
    fe = registry.get(frontend_id)
    if not fe:
        return
    url = f"{fe['url'].rstrip('/')}{path}"
    try:
        async with frontend_client.AsyncClient(timeout=PUSH_TIMEOUT) as client:
            r = await client.post(url, json=body)
            if r.status_code // 100 != 2:
                logger.warning(f"Push {path} → {url} returned HTTP {r.status_code}: {r.text[:200]}")
            else:
                logger.info(f"Pushed {path} → {frontend_id} OK")
    except httpx.HTTPError as e:
        logger.warning(f"Push {path} → {url} failed: {e}")


def _serialise(fe: dict[str, Any]) -> dict[str, Any]:
    """Registry entry for the admin. Secrets are write-only: the admin only
    sees whether they are set and the names of the extra headers."""
    mode = frontend_client.auth_mode(fe)
    _, source = frontend_client.effective_secret(fe)
    return {
        "frontend_id": fe["frontend_id"],
        "url": fe["url"],
        "name": fe["name"],
        "enabled": fe.get("enabled", True),
        "status": fe.get("status", "unknown"),
        "last_seen": fe.get("last_seen"),
        "created_at": fe.get("created_at"),
        "metadata": fe.get("metadata", {}),
        "auth_mode": mode,
        "signing_source": source if mode == frontend_client.MODE_SIGNED else "",
        "signing_enabled": mode == frontend_client.MODE_SIGNED and bool(source),
        "extra_header_names": sorted((fe.get("extra_headers") or {}).keys()),
        # What the frontend itself reports on each poll ("signed" | "trusted-network").
        "surface_auth": fe.get("surface_auth"),
    }


def _check_mode(mode: str) -> None:
    if mode not in frontend_client.AUTH_MODES:
        raise HTTPException(400, f"auth_mode must be one of {', '.join(frontend_client.AUTH_MODES)}")


def _check_secret(secret: str) -> None:
    if secret and len(secret) < MIN_SECRET_LENGTH:
        raise HTTPException(400, f"Signing secret must be at least {MIN_SECRET_LENGTH} characters")


def _check_signable(entry: dict[str, Any]) -> None:
    if frontend_client.auth_mode(entry) == frontend_client.MODE_SIGNED and not frontend_client.effective_secret(entry)[0]:
        raise HTTPException(
            400,
            "Signed mode needs a secret: set CBC_FRONTEND_SECRET on the backend (installation secret) "
            "or enter a secret for this frontend.",
        )


# --- Registry CRUD ---

class RegisterRequest(BaseModel):
    url: str  # the frontend's BACKEND port URL (container port 8080) — or the old URL in legacy mode
    name: str
    # "signed" (default: own secret, else the installation secret CBC_FRONTEND_SECRET),
    # "unsigned" (trusted network) or "legacy" (frontend on the image from before the two-port split).
    auth_mode: str = frontend_client.MODE_SIGNED
    signing_secret: str = ""  # optional per-frontend secret; blank = installation secret
    extra_headers: dict[str, str] = {}


class UpdateRequest(BaseModel):
    url: str | None = None
    name: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None
    auth_mode: str | None = None
    # None = unchanged; "" = remove the per-frontend secret (falls back to the installation secret)
    signing_secret: str | None = None
    # None = unchanged; {} = remove. Values are write-only (never returned).
    extra_headers: dict[str, str] | None = None


@router.get("")
async def list_frontends(_admin: dict = Depends(require_admin)):
    return {
        "frontends": [_serialise(f) for f in registry.list_all()],
        "global_secret_configured": bool(frontend_client.global_secret()),
    }


@router.post("", status_code=201)
async def register_frontend(req: RegisterRequest, _admin: dict = Depends(require_admin)):
    url = req.url.strip().rstrip("/")
    if not url:
        raise HTTPException(400, "url is required")
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    secret = req.signing_secret.strip()
    _check_mode(req.auth_mode)
    _check_secret(secret)
    entry = {"auth_mode": req.auth_mode, "signing_secret": secret, "extra_headers": req.extra_headers}
    _check_signable(entry)
    for other in registry.list_all():
        if (other.get("url") or "").rstrip("/") == url:
            raise HTTPException(409, f"URL {url} already used by frontend {other.get('frontend_id')!r}")

    # Verify the frontend is reachable and accepts this mode before saving anything.
    await _probe(url, entry)

    fe = registry.register(url=url, name=req.name.strip())
    fe = registry.update(fe["frontend_id"], **entry)
    return {"frontend": _serialise(fe)}


@router.get("/{frontend_id}")
async def get_frontend(frontend_id: str, _admin: dict = Depends(require_admin)):
    fe = registry.get(frontend_id)
    if not fe:
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")
    return {"frontend": _serialise(fe)}


@router.patch("/{frontend_id}")
async def update_frontend(
    frontend_id: str,
    req: UpdateRequest,
    verify: bool = True,
    _admin: dict = Depends(require_admin),
):
    """Update a frontend in place. The `frontend_id` never changes, so all
    campaign config keyed to it (prompts, branding, RAG, auth, LLM overrides,
    translations) is preserved — we update, we do NOT delete + re-register.

    `enabled` / `name` / `metadata` behave as before. `url` is validated:
      - normalised (rstrip '/') to match register/registry behaviour;
      - rejected with 409 if another frontend already owns it (ALWAYS checked,
        even when verify=false);
      - reachability-checked with 400 if unreachable, UNLESS `?verify=false`
        (the launchd reconciler pushes a host-resolved IP the backend
        container might not otherwise reach the same way).

    URL + mode + credentials are verified together, with the values that will
    be in effect after the update — migrating a frontend (new port + new mode
    + secret) is one verified save, never two half-verified ones.

    The poller reads `registry.list_enabled()` every tick, so a change takes
    effect on the next poll without a restart.
    """
    existing = registry.get(frontend_id)
    if not existing:
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")

    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if "auth_mode" in patch:
        _check_mode(patch["auth_mode"])
    if "signing_secret" in patch:
        patch["signing_secret"] = patch["signing_secret"].strip()
        _check_secret(patch["signing_secret"])
    if _CRED_FIELDS & patch.keys():
        # Pin the mode explicitly: entries from before modes existed derive it from
        # their secret, and removing that secret must not silently switch to legacy.
        patch.setdefault("auth_mode", frontend_client.auth_mode(existing))
        _check_signable({**existing, **patch})

    if "url" in patch:
        new_url = patch["url"].rstrip("/")
        patch["url"] = new_url
        # Collision: never let two ids point at the same sidecar. Checked
        # regardless of verify so the reconciler can't create a duplicate.
        for other in registry.list_all():
            if other.get("frontend_id") == frontend_id:
                continue
            if (other.get("url") or "").rstrip("/") == new_url:
                raise HTTPException(409, f"URL {new_url} already used by frontend {other.get('frontend_id')!r}")

    if verify and (({"url"} | _CRED_FIELDS) & patch.keys()):
        final = {**existing, **patch}
        await _probe(final["url"], final)

    updated = registry.update(frontend_id, **patch)
    if _CRED_FIELDS & patch.keys():
        logger.info(f"Frontend {frontend_id} access mode set to {frontend_client.auth_mode(updated)}")
    return {"frontend": _serialise(updated)}


@router.delete("/{frontend_id}")
async def delete_frontend(frontend_id: str, _admin: dict = Depends(require_admin)):
    if not registry.remove(frontend_id):
        raise HTTPException(404, f"Frontend {frontend_id!r} not found")
    return {"status": "deleted", "frontend_id": frontend_id}


# --- Per-frontend branding ---

def _require_registered(frontend_id: str) -> None:
    if not registry.get(frontend_id):
        raise HTTPException(404, f"Frontend {frontend_id!r} not registered. Register it first on the Frontends tab.")


@router.get("/{frontend_id}/branding")
async def get_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    b = branding_store.load(frontend_id)
    return {"frontend_id": frontend_id, "branding": b.model_dump() if b else None}


@router.put("/{frontend_id}/branding")
async def put_branding(frontend_id: str, branding: Branding, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    branding_store.save(frontend_id, branding)
    # Push resolved (override wins here → sends override). Uses the resolver so the
    # logic stays in one place.
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": branding.model_dump()}


@router.delete("/{frontend_id}/branding")
async def delete_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = branding_store.delete(frontend_id)
    # After deleting the override, resolver returns either global defaults (if set)
    # or {custom: False} (sidecar falls back to its deployment_frontend.json baseline).
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend translation bundle (download / upload) ---

@router.get("/{frontend_id}/branding/translations")
async def get_branding_translations(frontend_id: str, _admin: dict = Depends(require_admin)):
    """Export this frontend's translation bundle as JSON.

    404 if no per-frontend override exists — can't export what isn't there.
    """
    _require_registered(frontend_id)
    b = branding_store.load(frontend_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No per-frontend branding override to export")
    return TranslationBundle.from_branding(b).model_dump()


@router.put("/{frontend_id}/branding/translations")
async def put_branding_translations(frontend_id: str, bundle: TranslationBundle, _admin: dict = Depends(require_admin)):
    """Import a translation bundle into this frontend's override.

    Overwrites source text + translations; preserves non-text fields (logo,
    colors, app_title, org_name). Creates an override record if none exists.
    """
    _require_registered(frontend_id)
    current = branding_store.load(frontend_id) or Branding()
    updated = bundle.apply_to(current)
    branding_store.save(frontend_id, updated)
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": updated.model_dump()}


@router.post("/{frontend_id}/branding/auto-translate")
async def auto_translate_frontend_branding(frontend_id: str, _admin: dict = Depends(require_admin)):
    """Fill missing language keys in this frontend's branding override using the summariser LLM.

    Uses the frontend's own LLM override if one is set (via resolve_llm_config),
    falling back to the global LLM config otherwise. Existing non-empty
    translations are preserved.
    """
    from src.services.branding_translator import auto_translate_branding
    _require_registered(frontend_id)
    current = branding_store.load(frontend_id)
    if current is None:
        raise HTTPException(status_code=404, detail="No per-frontend branding override to translate")
    if not (current.disclaimer_text.strip() or current.instructions_text.strip()):
        raise HTTPException(status_code=400, detail="No source text in disclaimer_text or instructions_text")
    updated, stats = await auto_translate_branding(current, frontend_id=frontend_id, overwrite=False)
    branding_store.save(frontend_id, updated)
    await _push(frontend_id, "/internal/branding", resolvers.branding_push_payload(frontend_id))
    return {"frontend_id": frontend_id, "branding": updated.model_dump(), "stats": stats}


# --- Per-frontend session settings ---

@router.get("/{frontend_id}/session-settings")
async def get_session_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    s = session_settings_store.load(frontend_id)
    return {"frontend_id": frontend_id, "settings": s.model_dump() if s else None}


@router.put("/{frontend_id}/session-settings")
async def put_session_settings(frontend_id: str, settings: SessionSettings, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    session_settings_store.save(frontend_id, settings)
    await _push(frontend_id, "/internal/session-settings", session_settings_store.to_push_payload(settings))
    return {"frontend_id": frontend_id, "settings": settings.model_dump()}


@router.delete("/{frontend_id}/session-settings")
async def delete_session_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = session_settings_store.delete(frontend_id)
    await _push(frontend_id, "/internal/session-settings", session_settings_store.to_push_payload(None))
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend RAG settings ---

@router.get("/{frontend_id}/rag-settings")
async def get_rag_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    s = rag_settings_store.load(frontend_id)
    return {"frontend_id": frontend_id, "settings": s.model_dump()}


@router.put("/{frontend_id}/rag-settings")
async def put_rag_settings(frontend_id: str, settings: RAGSettings, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    rag_settings_store.save(frontend_id, settings)
    return {"frontend_id": frontend_id, "settings": settings.model_dump()}


@router.delete("/{frontend_id}/rag-settings")
async def delete_rag_settings(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = rag_settings_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed, "settings": rag_settings_store.load(frontend_id).model_dump()}


# --- Per-frontend organizations override ---

@router.get("/{frontend_id}/orgs")
async def get_orgs_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    o = orgs_override_store.load(frontend_id)
    return {"frontend_id": frontend_id, "override": o.model_dump() if o else None}


@router.put("/{frontend_id}/orgs")
async def put_orgs_override(
    frontend_id: str,
    override: OrgsOverride,
    _admin: dict = Depends(require_admin),
):
    _require_registered(frontend_id)
    orgs_override_store.save(frontend_id, override)
    return {"frontend_id": frontend_id, "override": override.model_dump()}


@router.delete("/{frontend_id}/orgs")
async def delete_orgs_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = orgs_override_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed}


# --- Per-frontend LLM override (per-slot opt-in) ---

@router.get("/{frontend_id}/llm")
async def get_llm_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    override = llm_override_store.load(frontend_id)
    return {"frontend_id": frontend_id, "override": override.model_dump()}


@router.put("/{frontend_id}/llm")
async def put_llm_override(
    frontend_id: str,
    cfg: LLMOverride,
    _admin: dict = Depends(require_admin),
):
    _require_registered(frontend_id)
    llm_override_store.save(frontend_id, cfg)
    return {"frontend_id": frontend_id, "override": cfg.model_dump()}


@router.delete("/{frontend_id}/llm")
async def delete_llm_override(frontend_id: str, _admin: dict = Depends(require_admin)):
    _require_registered(frontend_id)
    removed = llm_override_store.delete(frontend_id)
    return {"frontend_id": frontend_id, "removed": removed}
