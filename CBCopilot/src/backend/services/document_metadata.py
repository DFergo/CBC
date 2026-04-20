"""Per-directory `metadata.json` for RAG documents.

Each `documents/` folder may carry a sibling `metadata.json` mapping
`filename → {country, language, document_type}`. The country field powers
the auto-derived `Company.country_tags` (Sprint 5 wiring) and Compare All
filtering by country.

Shape on disk:

    {
      "amcor_australia_2024.pdf": {"country": "AU", "language": "en", "document_type": "cba"},
      "amcor_germany_2023.pdf":   {"country": "DE", "language": "de", "document_type": "cba"}
    }

Empty / missing values are valid — they just don't contribute to derived
fields. The admin UI surfaces this as a per-document mini-form at the
company tier.
"""
import logging
from pathlib import Path

from src.services._paths import (
    DOCUMENTS_DIR,
    atomic_write_json,
    company_dir,
    frontend_dir,
    read_json,
)

logger = logging.getLogger("doc_metadata")

# Free-form for now; admin UI uses these as a hint.
KNOWN_DOCUMENT_TYPES = ["cba", "policy", "code_of_conduct", "agreement", "other"]


def _path_for_scope(scope_key: str) -> Path:
    if scope_key == "global":
        return DOCUMENTS_DIR / "metadata.json"
    parts = scope_key.split("/")
    if len(parts) == 1:
        return frontend_dir(parts[0]) / "documents" / "metadata.json"
    if len(parts) == 2:
        return company_dir(parts[0], parts[1]) / "documents" / "metadata.json"
    raise ValueError(f"Bad scope_key {scope_key!r}")


def load(scope_key: str) -> dict[str, dict[str, str]]:
    """Return `{filename: {country, language, document_type}}`. Missing → {}."""
    data = read_json(_path_for_scope(scope_key))
    if not isinstance(data, dict):
        return {}
    # Defensive: ignore non-dict entries.
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save(scope_key: str, metadata: dict[str, dict[str, str]]) -> None:
    p = _path_for_scope(scope_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, metadata)
    logger.info(f"Document metadata saved for scope {scope_key} ({len(metadata)} entries)")


def update_one(scope_key: str, filename: str, fields: dict[str, str]) -> dict[str, str]:
    """Merge `fields` into the metadata for one filename. Returns the merged dict."""
    md = load(scope_key)
    existing = md.get(filename, {})
    merged = {**existing, **{k: (v or "").strip() for k, v in fields.items()}}
    md[filename] = merged
    save(scope_key, md)
    return merged


def remove_one(scope_key: str, filename: str) -> bool:
    md = load(scope_key)
    if filename not in md:
        return False
    del md[filename]
    save(scope_key, md)
    return True


def derive_country_tags(scope_key: str) -> list[str]:
    """Return sorted unique non-empty `country` values for this scope's docs.

    Used to auto-populate `Company.country_tags` on every reindex.
    """
    md = load(scope_key)
    countries = {(v.get("country") or "").strip().upper() for v in md.values()}
    countries.discard("")
    return sorted(countries)
