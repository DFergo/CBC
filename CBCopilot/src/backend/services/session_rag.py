"""Per-session RAG: temporary index for files the user uploads during chat.

Layout (D3=A): everything for a session lives under one tree, so auto-destroy
(ADR-005) is a single rmtree.

    /app/data/sessions/{token}/
    ├── uploads/                ← original files the user dropped in
    │   └── employee_handbook.pdf
    └── rag_index/              ← LlamaIndex artefacts for those files

Session RAG accepts `.pdf`, `.txt`, `.md`, `.docx` (admin RAG keeps the
narrower set without `.docx`). Sprint 6 will wire the chat upload UI; Sprint
5 ships the backend pipeline + a curl-testable endpoint.
"""
import logging
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services._paths import DATA_DIR

logger = logging.getLogger("session_rag")

SESSIONS_DIR = DATA_DIR / "sessions"

# Session RAG accepts .docx in addition to the admin set.
SESSION_ALLOWED_EXTS = {".pdf", ".txt", ".md", ".docx"}

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_indexes: dict[str, Any] = {}        # session_token -> VectorStoreIndex
_indexes_lock = threading.Lock()


@dataclass
class SessionUpload:
    name: str
    size: int


def _sanitize_token(token: str) -> str:
    if not _TOKEN_RE.match(token or ""):
        raise ValueError(f"Invalid session token format: {token!r}")
    return token


def _session_dir(token: str) -> Path:
    return SESSIONS_DIR / _sanitize_token(token)


def _uploads_dir(token: str) -> Path:
    return _session_dir(token) / "uploads"


def _index_dir(token: str) -> Path:
    return _session_dir(token) / "rag_index"


def _safe_filename(name: str) -> str:
    """Strip path components and reject anything weird."""
    name = Path(name).name  # drop directories
    if not name or name.startswith("."):
        raise ValueError(f"Invalid filename: {name!r}")
    if Path(name).suffix.lower() not in SESSION_ALLOWED_EXTS:
        raise ValueError(
            f"File type {Path(name).suffix!r} not allowed for session RAG. "
            f"Accepted: {sorted(SESSION_ALLOWED_EXTS)}"
        )
    return name


# --- Public API ---

def init_session(token: str) -> None:
    """Create the session's directory tree. Idempotent."""
    _uploads_dir(token).mkdir(parents=True, exist_ok=True)


def list_uploads(token: str) -> list[SessionUpload]:
    d = _uploads_dir(token)
    if not d.exists():
        return []
    return [
        SessionUpload(name=p.name, size=p.stat().st_size)
        for p in sorted(d.iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]


def ingest_upload(token: str, filename: str, content: bytes) -> SessionUpload:
    """Save a user-uploaded file, append it to the session's index, persist.

    Strategy: rebuild the session's index from scratch each time (small
    document counts per session — typically 0–5 files — so the cost is fine
    and avoids LlamaIndex incremental-update edge cases).
    """
    filename = _safe_filename(filename)
    init_session(token)
    path = _uploads_dir(token) / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    logger.info(f"Session {token}: ingested {filename} ({len(content)} bytes)")

    # Drop cache; build will repopulate on next query.
    with _indexes_lock:
        _indexes.pop(token, None)
    _build_index(token)
    return SessionUpload(name=filename, size=len(content))


def get_chunks_for_files(token: str, filenames: list[str]) -> list[dict[str, Any]]:
    """Return every indexed chunk whose source file is in `filenames`.

    Used by the chat-turn handler when the user attaches one or more files
    in *this* turn — we bypass semantic retrieval and inject the full file
    content directly, so the model can't miss it regardless of how vague
    the user's text message is.
    """
    if not filenames:
        return []
    wanted = set(filenames)
    idx = _get_index(token)
    if idx is None:
        return []
    out: list[dict[str, Any]] = []
    try:
        for node in idx.docstore.docs.values():
            fname = node.metadata.get("file_name")
            if fname and fname in wanted:
                out.append({
                    "text": node.text,
                    "score": 1.0,  # forced inclusion
                    "source": fname,
                    "tier": "session",
                    "scope_key": f"session-{token}",
                })
    except Exception as e:
        logger.warning(f"Failed to enumerate session chunks for {token}: {e}")
    return out


def query(token: str, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Top-k chunks from the session's uploaded files. [] when no uploads."""
    idx = _get_index(token)
    if idx is None:
        return []
    try:
        retriever = idx.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query_text)
        return [
            {
                "text": n.node.text,
                "score": getattr(n, "score", 0.0) or 0.0,
                "source": n.node.metadata.get("file_name", "(unknown)"),
                "tier": "session",
                "scope_key": f"session-{token}",
            }
            for n in nodes
        ]
    except Exception as e:
        logger.error(f"Session query failed for {token}: {e}")
        return []


def destroy_session(token: str) -> bool:
    """Auto-destroy hook: rmtree the entire session directory and drop the cache.
    Returns True if anything was deleted.
    """
    with _indexes_lock:
        _indexes.pop(token, None)
    d = _session_dir(token)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    logger.info(f"Destroyed session RAG for {token}")
    return True


# --- Internal ---

def _get_index(token: str) -> Any | None:
    with _indexes_lock:
        if token in _indexes:
            return _indexes[token]
    idx = _load_index(token) or _build_index(token)
    with _indexes_lock:
        if idx is not None:
            _indexes[token] = idx
    return idx


def _list_files(token: str) -> list[Path]:
    d = _uploads_dir(token)
    if not d.exists():
        return []
    return [
        p for p in sorted(d.iterdir())
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SESSION_ALLOWED_EXTS
    ]


def _setup_settings() -> None:
    # Reuse rag_service's lazy embedding loader so we share the model + config
    from src.services import rag_service
    rag_service._setup_settings()


def _build_index(token: str) -> Any | None:
    from llama_index.core import SimpleDirectoryReader, VectorStoreIndex

    files = _list_files(token)
    if not files:
        # Wipe persisted index if it exists (no docs left)
        if _index_dir(token).exists():
            shutil.rmtree(_index_dir(token), ignore_errors=True)
        with _indexes_lock:
            _indexes.pop(token, None)
        return None

    _setup_settings()
    try:
        reader = SimpleDirectoryReader(input_files=[str(f) for f in files])
        documents = reader.load_data()
        for d in documents:
            d.metadata["scope_key"] = f"session-{token}"
            d.metadata["tier"] = "session"
        index = VectorStoreIndex.from_documents(documents)
        index_dir = _index_dir(token)
        index_dir.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(persist_dir=str(index_dir))
        with _indexes_lock:
            _indexes[token] = index
        node_count = len(index.docstore.docs) if hasattr(index, "docstore") else 0
        logger.info(f"Built session index for {token}: {len(files)} files → {node_count} nodes")
        return index
    except Exception as e:
        logger.error(f"Failed to build session index for {token}: {e}")
        return None


def _load_index(token: str) -> Any | None:
    from llama_index.core import StorageContext, load_index_from_storage

    index_dir = _index_dir(token)
    if not (index_dir / "index_store.json").exists():
        return None
    _setup_settings()
    try:
        sc = StorageContext.from_defaults(persist_dir=str(index_dir))
        return load_index_from_storage(sc)
    except Exception as e:
        logger.warning(f"Failed to load session index for {token}: {e}")
        return None
