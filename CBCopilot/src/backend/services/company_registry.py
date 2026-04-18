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


class Company(BaseModel):
    slug: str
    display_name: str
    enabled: bool = True
    sort_order: int = 0
    is_compare_all: bool = False
    prompt_mode: str = "inherit"  # inherit | own | combine
    rag_mode: str = "combine_all"  # own_only | inherit_frontend | inherit_all | combine_frontend | combine_all
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


def list_companies(frontend_id: str) -> list[Company]:
    data = read_json(companies_file(frontend_id), default=[])
    if not isinstance(data, list):
        logger.warning(f"companies.json for {frontend_id} is not a list; returning empty")
        return []
    result: list[Company] = []
    for entry in data:
        try:
            result.append(Company(**entry))
        except Exception as e:
            logger.warning(f"Skipping malformed company entry in {frontend_id}: {e}")
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
