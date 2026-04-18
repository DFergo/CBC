"""Prompt management across the three config tiers.

Paths:
- Global: /app/data/prompts/{name}.md
- Frontend: /app/data/campaigns/{fid}/prompts/{name}.md
- Company: /app/data/campaigns/{fid}/companies/{slug}/prompts/{name}.md

See SPEC §2.4 (resolution order) and §4.1 (prompt assembler contract).
Sprint 3 exposes CRUD at all three tiers via the admin API. Actual resolution
(company → frontend → global) is used at chat time, which lands in Sprint 6.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from src.services._paths import (
    PROMPTS_DIR,
    company_dir,
    frontend_dir,
    safe_filename,
)

logger = logging.getLogger("prompt_store")


@dataclass
class PromptFile:
    name: str
    size: int
    modified: float


def _ensure_md(name: str) -> str:
    name = safe_filename(name)
    return name if name.endswith(".md") else f"{name}.md"


def _tier_dir(frontend_id: str | None, company_slug: str | None) -> Path:
    if frontend_id is None and company_slug is None:
        return PROMPTS_DIR
    if frontend_id and company_slug is None:
        return frontend_dir(frontend_id) / "prompts"
    if frontend_id and company_slug:
        return company_dir(frontend_id, company_slug) / "prompts"
    raise ValueError("company_slug requires frontend_id")


def list_prompts(frontend_id: str | None = None, company_slug: str | None = None) -> list[PromptFile]:
    d = _tier_dir(frontend_id, company_slug)
    if not d.exists():
        return []
    result: list[PromptFile] = []
    for p in sorted(d.glob("*.md")):
        st = p.stat()
        result.append(PromptFile(name=p.name, size=st.st_size, modified=st.st_mtime))
    return result


def read_prompt(name: str, frontend_id: str | None = None, company_slug: str | None = None) -> str:
    d = _tier_dir(frontend_id, company_slug)
    path = d / _ensure_md(name)
    if not path.exists():
        raise FileNotFoundError(f"Prompt {path} not found")
    return path.read_text()


def write_prompt(name: str, content: str, frontend_id: str | None = None, company_slug: str | None = None) -> PromptFile:
    d = _tier_dir(frontend_id, company_slug)
    d.mkdir(parents=True, exist_ok=True)
    path = d / _ensure_md(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)
    logger.info(f"Saved prompt {path}")
    st = path.stat()
    return PromptFile(name=path.name, size=st.st_size, modified=st.st_mtime)


def delete_prompt(name: str, frontend_id: str | None = None, company_slug: str | None = None) -> bool:
    d = _tier_dir(frontend_id, company_slug)
    path = d / _ensure_md(name)
    if not path.exists():
        return False
    path.unlink()
    logger.info(f"Deleted prompt {path}")
    return True
