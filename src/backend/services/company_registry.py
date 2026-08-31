"""Per-frontend company CRUD.

Data layout: /app/data/campaigns/{frontend_id}/companies.json as a JSON array.
See SPEC §4.4 for the company config shape.
"""
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.services._paths import (
    atomic_write_json,
    companies_file,
    read_json,
    frontend_dir,
)

logger = logging.getLogger("company_registry")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _slugify(name: str) -> str:
    """Derive a filesystem-safe slug from a display name. Same shape as
    frontend_registry's slugify so admins can predict folder names when
    navigating /app/data/campaigns/{frontend_id}/companies/{slug}/ on disk.
    Falls back to 'company' if the input collapses to empty.
    """
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "company"


def next_unique_slug(frontend_id: str, base: str) -> str:
    """Return `base`, or `base-2`, `base-3`, … until we find an unused slug
    for this frontend. Used so admins can add two companies with the same
    display name (e.g. "Smurfit Kappa") without worrying about collisions.
    """
    existing = {c.slug for c in list_companies(frontend_id)}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def slug_for_name(frontend_id: str, display_name: str) -> str:
    """Convenience: slugify + uniqueness check in one call."""
    return next_unique_slug(frontend_id, _slugify(display_name))


class Company(BaseModel):
    slug: str
    display_name: str
    enabled: bool = True
    is_compare_all: bool = False
    # When the chat session resolves RAG for this company, layer in higher tiers?
    # Both default true — admins opt OUT of inheritance per tier.
    combine_frontend_rag: bool = True
    combine_global_rag: bool = True
    country_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"Invalid slug {v!r}: lowercase letters, digits, and hyphens only; must start with alphanumeric; max 64 chars"
            )
        return v


# Migration map for the legacy `rag_mode` enum (5 values reducible to 2 bools).
_LEGACY_RAG_MODE: dict[str, tuple[bool, bool]] = {
    "own_only":          (False, False),
    "inherit_frontend":  (True,  False),
    "combine_frontend":  (True,  False),
    "inherit_all":       (True,  True),
    "combine_all":       (True,  True),
}


def _migrate_legacy(entry: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy `rag_mode` strings into the new pair of bools.

    Pydantic's default `extra="ignore"` silently drops unknown keys, so old
    `companies.json` entries would lose their setting AND get the True/True
    default — accidentally turning every "own_only" company into "combine_all".
    Catch that here before validation runs.
    """
    if "rag_mode" in entry and "combine_frontend_rag" not in entry:
        cf, cg = _LEGACY_RAG_MODE.get(entry["rag_mode"], (True, True))
        entry["combine_frontend_rag"] = cf
        entry["combine_global_rag"] = cg
    entry.pop("rag_mode", None)
    return entry


def list_companies(frontend_id: str) -> list[Company]:
    data = read_json(companies_file(frontend_id), default=[])
    if not isinstance(data, list):
        logger.warning(f"companies.json for {frontend_id} is not a list; returning empty")
        return []
    result: list[Company] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        entry = _migrate_legacy(dict(entry))
        try:
            result.append(Company(**entry))
        except Exception as e:
            logger.warning(f"Skipping malformed company entry in {frontend_id}: {e}")
    # Compare All entries first, then alphabetical by display_name (case-insensitive).
    result.sort(key=lambda c: (0 if c.is_compare_all else 1, c.display_name.lower()))
    return result


def _save_all(frontend_id: str, companies: list[Company]) -> None:
    frontend_dir(frontend_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(companies_file(frontend_id), [c.model_dump() for c in companies])


def create_company(frontend_id: str, company: Company) -> Company:
    existing = list_companies(frontend_id)
    if any(c.slug == company.slug for c in existing):
        raise ValueError(f"Company with slug {company.slug!r} already exists for frontend {frontend_id!r}")
    existing.append(company)
    _save_all(frontend_id, existing)
    logger.info(f"Created company {company.slug} for frontend {frontend_id}")
    return company


def update_company(frontend_id: str, slug: str, patch: dict[str, Any]) -> Company:
    companies = list_companies(frontend_id)
    for i, c in enumerate(companies):
        if c.slug == slug:
            merged = {**c.model_dump(), **patch, "slug": slug}  # slug is immutable here
            companies[i] = Company(**merged)
            _save_all(frontend_id, companies)
            logger.info(f"Updated company {slug} for frontend {frontend_id}")
            return companies[i]
    raise KeyError(f"Company {slug!r} not found for frontend {frontend_id!r}")


def delete_company(frontend_id: str, slug: str) -> bool:
    companies = list_companies(frontend_id)
    filtered = [c for c in companies if c.slug != slug]
    if len(filtered) == len(companies):
        return False
    _save_all(frontend_id, filtered)
    logger.info(f"Deleted company {slug} for frontend {frontend_id}")
    return True
