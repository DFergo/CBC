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

Sprint 16 followup: when the admin hasn't filled country metadata (they
rarely do post-upload), `derive_country_tags` can auto-detect the country
from the filename itself using a best-effort map of country names to ISO-2
codes. Sheets with "Spain" / "Germany" / "México" in the filename win a
tag without manual curation. Collisions (e.g. "USA" subword) are filtered
by requiring the token to sit between separators.
"""
import logging
import re
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


# --- Filename-based country detection (Sprint 16 followup) ---------------
#
# Best-effort map from English / Spanish / native-language country name to
# ISO-3166 alpha-2. Covers the set of jurisdictions UNI Graphical &
# Packaging actually deals with; extend as new affiliates land. Keys are
# lower-case because matching is case-insensitive. Multi-word countries use
# underscore keys ("south_africa") — the tokeniser joins adjacent tokens
# before lookup, so filenames like "CBA-South-Africa-...pdf" still match.
_COUNTRY_FROM_FILENAME: dict[str, str] = {
    # Europe
    "spain": "ES", "españa": "ES", "espana": "ES",
    "france": "FR", "francia": "FR",
    "germany": "DE", "alemania": "DE", "deutschland": "DE",
    "italy": "IT", "italia": "IT",
    "portugal": "PT",
    "netherlands": "NL", "holanda": "NL", "nederland": "NL",
    "belgium": "BE", "belgica": "BE", "bélgica": "BE",
    "uk": "GB", "united_kingdom": "GB", "reino_unido": "GB", "britain": "GB",
    "ireland": "IE", "irlanda": "IE",
    "poland": "PL", "polonia": "PL", "polska": "PL",
    "czech": "CZ", "czechia": "CZ", "chequia": "CZ",
    "slovakia": "SK", "eslovaquia": "SK",
    "austria": "AT",
    "switzerland": "CH", "suiza": "CH", "schweiz": "CH",
    "denmark": "DK", "dinamarca": "DK",
    "sweden": "SE", "suecia": "SE",
    "norway": "NO", "noruega": "NO",
    "finland": "FI", "finlandia": "FI",
    "greece": "GR", "grecia": "GR",
    "turkey": "TR", "turquia": "TR", "turquía": "TR",
    "romania": "RO", "rumania": "RO", "rumanía": "RO",
    "hungary": "HU", "hungria": "HU",
    "bulgaria": "BG",
    "croatia": "HR", "croacia": "HR", "hrvatska": "HR",
    "serbia": "RS",
    "slovenia": "SI", "eslovenia": "SI",
    # Americas
    "usa": "US", "united_states": "US", "estados_unidos": "US",
    "canada": "CA", "canadá": "CA",
    "mexico": "MX", "méxico": "MX",
    "brazil": "BR", "brasil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE", "perú": "PE",
    "uruguay": "UY",
    "venezuela": "VE",
    # Asia
    "india": "IN",
    "china": "CN",
    "japan": "JP", "japón": "JP", "japon": "JP",
    "south_korea": "KR", "corea": "KR",
    "taiwan": "TW", "taiwán": "TW",
    "philippines": "PH", "filipinas": "PH",
    "thailand": "TH", "tailandia": "TH",
    "vietnam": "VN",
    "indonesia": "ID",
    "malaysia": "MY", "malasia": "MY",
    "singapore": "SG", "singapur": "SG",
    # Africa / Oceania
    "south_africa": "ZA", "sudafrica": "ZA", "sudáfrica": "ZA",
    "morocco": "MA", "marruecos": "MA",
    "egypt": "EG", "egipto": "EG",
    "tunisia": "TN", "tunez": "TN", "túnez": "TN",
    "australia": "AU",
    "new_zealand": "NZ",
}

# Tokenise by any common separator admins stick in filenames. Covers hyphen,
# underscore, whitespace, dot, en-dash, em-dash.
_FILENAME_SPLIT_RE = re.compile(r"[\-_\s\.–—]+")


def _detect_country_from_filename(filename: str) -> str | None:
    """Best-effort ISO-2 from a filename. Matches single tokens first
    ("spain") and then adjacent 2-token joins ("south", "africa" →
    "south_africa") so multi-word countries aren't missed. Returns None
    if nothing in the map hits."""
    stem = Path(filename).stem.lower()
    tokens = [t for t in _FILENAME_SPLIT_RE.split(stem) if t]
    for tok in tokens:
        iso = _COUNTRY_FROM_FILENAME.get(tok)
        if iso:
            return iso
    for i in range(len(tokens) - 1):
        joined = f"{tokens[i]}_{tokens[i + 1]}"
        iso = _COUNTRY_FROM_FILENAME.get(joined)
        if iso:
            return iso
    return None


def derive_country_tags(scope_key: str, filenames: list[str] | None = None) -> list[str]:
    """Return sorted unique ISO-2 country tags for this scope's docs.

    Used to auto-populate `Company.country_tags` on every reindex.

    Two layers:
    1. Explicit `country` values in `metadata.json` (admin curated). Always
       included.
    2. Sprint 16 followup — when `filenames` is provided, any file without
       an explicit country in metadata gets country auto-detected from the
       filename via `_detect_country_from_filename`. This means CBAs
       uploaded without admin follow-up still populate company.country_tags,
       which Compare All's country-filter relies on.
    """
    md = load(scope_key)
    countries: set[str] = set()
    for v in md.values():
        c = (v.get("country") or "").strip().upper()
        if c:
            countries.add(c)
    if filenames:
        for fn in filenames:
            explicit = (md.get(fn, {}).get("country") or "").strip()
            if explicit:
                continue
            detected = _detect_country_from_filename(fn)
            if detected:
                countries.add(detected)
    return sorted(countries)
