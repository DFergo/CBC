"""3-tier resolution logic (SPEC §2.4 + Sprint 4B clarifications).

**Prompts** — winner-takes-all (NOT stacked):
- Normal role prompts (core.md, guardrails.md, cba_advisor.md, context_template.md):
    company → frontend → global
- Compare All prompt (compare_all.md): frontend → global (NEVER company —
    the mode is cross-company by definition).

**RAG docs** — stackable, controlled by company.rag_mode + frontend.rag_standalone:
- Single-company chat: company docs (always) + frontend docs (if rag_mode
    inherits frontend) + global docs (if rag_mode inherits all AND NOT
    frontend.rag_standalone).
- Compare All: union of per-company docs (filtered by comparison_scope) +
    frontend docs + global docs (unless frontend.rag_standalone).

**Orgs** — mode-based per frontend: inherit | own | combine.

The resolvers are used by the chat engine (Sprint 6) and exposed via
/admin/api/v1/resolvers/* endpoints for admin preview.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.services import (
    branding_defaults_store,
    branding_store,
    company_registry,
    orgs_override_store,
    rag_settings_store,
)
from src.services._paths import (
    DOCUMENTS_DIR,
    PROMPTS_DIR,
    company_dir,
    frontend_dir,
)
from src.services.branding_store import Branding

logger = logging.getLogger("resolvers")

Tier = Literal["global", "frontend", "company", "none"]
COMPARE_ALL_PROMPT = "compare_all.md"


@dataclass
class PromptResolution:
    tier: Tier
    name: str
    path: Path | None
    content: str | None


@dataclass
class RAGResolution:
    paths: list[dict[str, Any]]  # [{tier, scope_key, path, doc_count}]
    frontend_standalone: bool


# --- Prompts ---

def _prompt_path(name: str, frontend_id: str | None, company_slug: str | None) -> Path:
    if frontend_id and company_slug:
        return company_dir(frontend_id, company_slug) / "prompts" / name
    if frontend_id:
        return frontend_dir(frontend_id) / "prompts" / name
    return PROMPTS_DIR / name


def _ensure_md(name: str) -> str:
    return name if name.endswith(".md") else f"{name}.md"


def resolve_prompt(
    name: str,
    frontend_id: str | None = None,
    company_slug: str | None = None,
    is_compare_all: bool = False,
) -> PromptResolution:
    """Return the prompt that would be used for this (frontend, company) context.

    Compare All MODE skips the company tier even if a company_slug is passed —
    that matches the user's mental model: compare_all.md is a cross-company
    prompt and no single company "owns" it.
    """
    name = _ensure_md(name)
    compare_all_mode = is_compare_all or name == COMPARE_ALL_PROMPT
    # Order of tiers to try
    tiers: list[tuple[Tier, Path]] = []
    if not compare_all_mode and frontend_id and company_slug:
        tiers.append(("company", _prompt_path(name, frontend_id, company_slug)))
    if frontend_id:
        tiers.append(("frontend", _prompt_path(name, frontend_id, None)))
    tiers.append(("global", _prompt_path(name, None, None)))

    for tier, path in tiers:
        if path.exists():
            try:
                return PromptResolution(tier=tier, name=name, path=path, content=path.read_text())
            except OSError as e:
                logger.warning(f"Prompt {path} present but unreadable: {e}")
                continue

    return PromptResolution(tier="none", name=name, path=None, content=None)


# --- RAG ---

def _company_docs_dir(frontend_id: str, slug: str) -> Path:
    return company_dir(frontend_id, slug) / "documents"


def _frontend_docs_dir(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "documents"


def _count_docs(d: Path) -> int:
    if not d.exists():
        return 0
    return sum(1 for p in d.iterdir() if p.is_file() and not p.name.startswith("."))


def _frontend_is_standalone(frontend_id: str) -> bool:
    """True when this frontend has globally opted out of the global RAG tier."""
    return not rag_settings_store.load(frontend_id).combine_global_rag


def _company_filter_by_scope(
    companies: list[company_registry.Company],
    scope: str | None,
    user_country: str | None,
) -> list[company_registry.Company]:
    """Compare All scope filter.

    - 'global' (or None): every enabled company
    - 'national': only companies whose country_tags include user_country
    - 'regional': Sprint 5+ will define region groupings; for now treat as 'global'
      since we don't have the region mapping yet. Log a note.
    """
    if scope in (None, "global"):
        return companies
    if scope == "regional":
        logger.info("Compare All scope 'regional' not yet implemented; falling back to 'global'")
        return companies
    if scope == "national":
        if not user_country:
            return []  # No country → no national match
        cc = user_country.upper()
        return [c for c in companies if cc in (tag.upper() for tag in c.country_tags)]
    return companies


def resolve_rag_paths(
    frontend_id: str,
    company_slug: str | None = None,
    is_compare_all: bool = False,
    comparison_scope: str | None = None,
    user_country: str | None = None,
) -> RAGResolution:
    """Return the ordered list of document directories to load for this session.

    Each entry is {tier, scope_key, path, doc_count}. Sprint 5's real RAG
    indexer will read from these paths and build a combined index at query time.
    """
    standalone = _frontend_is_standalone(frontend_id) if frontend_id else False
    out: list[dict[str, Any]] = []

    if is_compare_all:
        companies = company_registry.list_companies(frontend_id)
        companies = [c for c in companies if c.enabled and not c.is_compare_all]
        companies = _company_filter_by_scope(companies, comparison_scope, user_country)
        for co in companies:
            p = _company_docs_dir(frontend_id, co.slug)
            out.append({
                "tier": "company",
                "scope_key": f"{frontend_id}/{co.slug}",
                "path": str(p),
                "doc_count": _count_docs(p),
            })
        fp = _frontend_docs_dir(frontend_id)
        out.append({
            "tier": "frontend",
            "scope_key": frontend_id,
            "path": str(fp),
            "doc_count": _count_docs(fp),
        })
        if not standalone:
            out.append({
                "tier": "global",
                "scope_key": "",
                "path": str(DOCUMENTS_DIR),
                "doc_count": _count_docs(DOCUMENTS_DIR),
            })
        return RAGResolution(paths=out, frontend_standalone=standalone)

    # Single-company
    if not (frontend_id and company_slug):
        return RAGResolution(paths=[], frontend_standalone=standalone)
    co = next((c for c in company_registry.list_companies(frontend_id) if c.slug == company_slug), None)
    if not co:
        return RAGResolution(paths=[], frontend_standalone=standalone)

    cp = _company_docs_dir(frontend_id, company_slug)
    out.append({
        "tier": "company",
        "scope_key": f"{frontend_id}/{company_slug}",
        "path": str(cp),
        "doc_count": _count_docs(cp),
    })
    if co.combine_frontend_rag:
        fp = _frontend_docs_dir(frontend_id)
        out.append({
            "tier": "frontend",
            "scope_key": frontend_id,
            "path": str(fp),
            "doc_count": _count_docs(fp),
        })
    if co.combine_global_rag and not standalone:
        out.append({
            "tier": "global",
            "scope_key": "",
            "path": str(DOCUMENTS_DIR),
            "doc_count": _count_docs(DOCUMENTS_DIR),
        })
    return RAGResolution(paths=out, frontend_standalone=standalone)


# --- Orgs ---

def resolve_orgs(frontend_id: str | None = None) -> dict[str, Any]:
    """Return the effective organizations list + mode for a given frontend.

    - No frontend or no override: global list, mode='inherit'
    - mode='own': per-frontend list only
    - mode='combine': global + per-frontend, deduped by name
    """
    from src.services import knowledge_store

    global_list = [o.model_dump() for o in knowledge_store.list_organizations()]
    if not frontend_id:
        return {"mode": "inherit", "organizations": global_list, "count": len(global_list)}
    override = orgs_override_store.load(frontend_id)
    if not override:
        return {"mode": "inherit", "organizations": global_list, "count": len(global_list)}
    mode = override.mode
    if mode == "own":
        return {"mode": "own", "organizations": override.organizations, "count": len(override.organizations)}
    if mode == "combine":
        by_name: dict[str, dict[str, Any]] = {o["name"]: o for o in global_list}
        for o in override.organizations:
            by_name[o["name"]] = o
        merged = list(by_name.values())
        return {"mode": "combine", "organizations": merged, "count": len(merged)}
    # 'inherit' mode stored explicitly
    return {"mode": "inherit", "organizations": global_list, "count": len(global_list)}


# --- Branding ---

def resolve_branding(frontend_id: str) -> tuple[Tier, dict[str, Any]]:
    """Effective branding for a frontend, merged per-field across tiers.

    Per-field merge (not winner-takes-all): the deepest non-empty value wins.
    Empty strings in an override = "inherit lower tier" rather than "force empty".
    Order (lowest → highest precedence): hardcoded baseline (in the sidecar,
    unknown to the backend) → global defaults → per-frontend override.

    Returns (tier, fields_dict). `tier` is the deepest tier that contributed
    any non-empty field (`"frontend"` > `"global"` > `"none"`). `fields_dict`
    contains only the non-empty fields the backend wants to push down — the
    sidecar fills in the rest from the hardcoded baseline.
    """
    defaults = branding_defaults_store.load()
    override = branding_store.load(frontend_id)

    merged: dict[str, Any] = {}
    if defaults:
        for k, v in defaults.model_dump().items():
            if v:
                merged[k] = v
    if override:
        for k, v in override.model_dump().items():
            if v:
                merged[k] = v

    if override and any(override.model_dump().values()):
        return ("frontend", merged)
    if defaults and any(defaults.model_dump().values()):
        return ("global", merged)
    return ("none", merged)


def branding_push_payload(frontend_id: str) -> dict[str, Any]:
    """Body for POST /internal/branding on this frontend's sidecar.

    `{custom: True, ...non_empty_fields}` when any tier contributes — sidecar
    merges those onto its hardcoded baseline. `{custom: False}` when no tier
    contributes — sidecar clears the cache and uses pure baseline.
    """
    tier, fields = resolve_branding(frontend_id)
    if tier == "none":
        return {"custom": False}
    return {"custom": True, **fields}
