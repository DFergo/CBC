"""Storage layout + atomic write helpers.

All disk-backed services go through these helpers so paths are consistent
and JSON writes survive crashes (write to .tmp, rename — atomic on POSIX).

See SPEC §2.4 (three-tier config) for the rationale behind the layout.
"""
import json
import os
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("CBC_DATA_DIR", "/app/data"))

# --- Global tier ---
PROMPTS_DIR = DATA_DIR / "prompts"
DOCUMENTS_DIR = DATA_DIR / "documents"
RAG_INDEX_DIR = DATA_DIR / "rag_index"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
SESSIONS_DIR = DATA_DIR / "sessions"

# --- Frontend tier ---
CAMPAIGNS_DIR = DATA_DIR / "campaigns"

# --- Global config files ---
LLM_CONFIG_FILE = DATA_DIR / "llm_config.json"
SMTP_CONFIG_FILE = DATA_DIR / "smtp_config.json"
GLOSSARY_FILE = KNOWLEDGE_DIR / "glossary.json"
ORGANIZATIONS_FILE = KNOWLEDGE_DIR / "organizations.json"
# Sprint 15 phase 4: admin-editable runtime overrides that need to survive
# container restart. Sibling of llm_config.json, covers the RAG-pipeline
# knobs that `backend_config` holds (rag_chunk_size, rag_embedding_model,
# rag_contextual_enabled) — LLMConfig fields already persist via
# llm_config_store. See runtime_overrides_store.py.
RUNTIME_OVERRIDES_FILE = DATA_DIR / "runtime_overrides.json"


def frontend_dir(frontend_id: str) -> Path:
    return CAMPAIGNS_DIR / frontend_id


def company_dir(frontend_id: str, company_slug: str) -> Path:
    return frontend_dir(frontend_id) / "companies" / company_slug


def companies_file(frontend_id: str) -> Path:
    return frontend_dir(frontend_id) / "companies.json"


def ensure_dirs() -> None:
    """Create the core directory tree if missing. Idempotent."""
    for d in (PROMPTS_DIR, DOCUMENTS_DIR, RAG_INDEX_DIR, KNOWLEDGE_DIR, SESSIONS_DIR, CAMPAIGNS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically — tmp then rename. Survives crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def safe_filename(name: str) -> str:
    """Reject path traversal and empty names. Returns the cleaned basename."""
    if not name or name in (".", ".."):
        raise ValueError(f"Invalid filename: {name!r}")
    if "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(f"Path separators not allowed in filename: {name!r}")
    return name
