"""Glossary + organizations (global only for Sprint 3).

Per-frontend orgs list lands in Sprint 4 (§2.4 orgs_mode: global / own / combine).
"""
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.services._paths import (
    GLOSSARY_FILE,
    ORGANIZATIONS_FILE,
    atomic_write_json,
    read_json,
)

logger = logging.getLogger("knowledge_store")


class GlossaryTerm(BaseModel):
    term: str
    definition: str = ""
    translations: dict[str, str] = Field(default_factory=dict)


class Organization(BaseModel):
    name: str
    type: str = ""
    country: str = ""
    description: str = ""


def list_glossary() -> list[GlossaryTerm]:
    data = read_json(GLOSSARY_FILE, default=[])
    if not isinstance(data, list):
        return []
    out: list[GlossaryTerm] = []
    for e in data:
        try:
            out.append(GlossaryTerm(**e))
        except Exception as ex:
            logger.warning(f"Skipping malformed glossary entry: {ex}")
    return out


def save_glossary(terms: list[GlossaryTerm]) -> None:
    atomic_write_json(GLOSSARY_FILE, [t.model_dump() for t in terms])


def list_organizations() -> list[Organization]:
    data = read_json(ORGANIZATIONS_FILE, default=[])
    if not isinstance(data, list):
        return []
    out: list[Organization] = []
    for e in data:
        try:
            out.append(Organization(**e))
        except Exception as ex:
            logger.warning(f"Skipping malformed org entry: {ex}")
    return out


def save_organizations(orgs: list[Organization]) -> None:
    atomic_write_json(ORGANIZATIONS_FILE, [o.model_dump() for o in orgs])


def raw_glossary() -> Any:
    """Returns raw JSON-serializable data (for bulk import/export)."""
    return read_json(GLOSSARY_FILE, default=[])


def raw_organizations() -> Any:
    return read_json(ORGANIZATIONS_FILE, default=[])
