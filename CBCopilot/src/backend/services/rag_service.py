"""LlamaIndex-backed RAG service.

A "scope" is one of (global, frontend_id, frontend_id+company_slug). Each
scope has its own `documents/` folder and a sibling `rag_index/` folder
where the persisted index lives. The service caches in-memory
VectorStoreIndex objects keyed by `scope_key` and uses the same scope_key
shape that `resolvers.resolve_rag_paths` returns — the chat engine in
Sprint 6 just calls `query_scopes(resolver_paths, query)`.

Design rules:
- Lazy load: indexes load from disk on first use, build if absent.
- `invalidate(scope_key)` drops the in-memory entry. The next query reloads
  from disk. Used by the file watcher on document changes.
- `reindex(scope_key)` forces a rebuild from disk and persists.
- Heavy imports (`llama_index`, `sentence_transformers`) defer until first
  use — keeps `import` graph cheap for tests + cold paths.
"""
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services._paths import (
    DATA_DIR,
    DOCUMENTS_DIR,
    company_dir,
    frontend_dir,
)

logger = logging.getLogger("rag")

# Per SPEC §4.2.
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
DEFAULT_TOP_K = 5

# Admin RAG accepts these. Session RAG additionally accepts .docx (handled in
# session_rag.py — Phase D).
ADMIN_ALLOWED_EXTS = {".pdf", ".txt", ".md"}

# Lazy-loaded singletons.
_embed_model: Any = None
_embed_lock = threading.Lock()

# Per-scope cached indexes. Keyed by `scope_key` (e.g. "global",
# "packaging-eu", "packaging-eu/amcor").
_indexes: dict[str, Any] = {}
_indexes_lock = threading.Lock()


@dataclass
class Chunk:
    """One retrieved chunk with provenance for prompt assembly + citations."""
    text: str
    score: float
    source: str        # original filename (e.g. "amcor_australia_2024.pdf")
    tier: str          # 'global' | 'frontend' | 'company' | 'session'
    scope_key: str     # 'global', 'packaging-eu', 'packaging-eu/amcor', 'session-XXXX'


# --- Path helpers ---

def scope_key_for(frontend_id: str | None, company_slug: str | None) -> str:
    if not frontend_id:
        return "global"
    if not company_slug:
        return frontend_id
    return f"{frontend_id}/{company_slug}"


def _docs_dir_for(scope_key: str) -> Path:
    if scope_key == "global":
        return DOCUMENTS_DIR
    parts = scope_key.split("/")
    if len(parts) == 1:
        return frontend_dir(parts[0]) / "documents"
    if len(parts) == 2:
        return company_dir(parts[0], parts[1]) / "documents"
    raise ValueError(f"Bad scope_key {scope_key!r}")


def _index_dir_for(scope_key: str) -> Path:
    if scope_key == "global":
        return DATA_DIR / "rag_index"
    parts = scope_key.split("/")
    if len(parts) == 1:
        return frontend_dir(parts[0]) / "rag_index"
    if len(parts) == 2:
        return company_dir(parts[0], parts[1]) / "rag_index"
    raise ValueError(f"Bad scope_key {scope_key!r}")


def _tier_for(scope_key: str) -> str:
    if scope_key == "global":
        return "global"
    return "company" if "/" in scope_key else "frontend"


# --- LlamaIndex wiring (lazy) ---

def _get_embed_model() -> Any:
    """Load the embedding model on first use. The Dockerfile pre-downloads the
    weights so this only does the local-disk load, not a network call.
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is None:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            _embed_model = HuggingFaceEmbedding(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
            )
            logger.info("Loaded embedding model all-MiniLM-L6-v2")
    return _embed_model


def _setup_settings() -> None:
    """Configure LlamaIndex's global Settings. Cheap to call repeatedly."""
    from llama_index.core import Settings
    Settings.embed_model = _get_embed_model()
    Settings.llm = None  # we drive the LLM ourselves; LlamaIndex never calls one
    Settings.chunk_size = CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP


# --- Indexing ---

def _list_indexable_files(docs_dir: Path) -> list[Path]:
    """Single-level scan, admin-allowed extensions only, no hidden files."""
    if not docs_dir.exists():
        return []
    out: list[Path] = []
    for p in sorted(docs_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name.startswith("._"):
            continue
        if p.suffix.lower() not in ADMIN_ALLOWED_EXTS:
            continue
        out.append(p)
    return out


def _build_index(scope_key: str) -> Any | None:
    """Build a fresh VectorStoreIndex from disk. Returns None if no docs."""
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

    _setup_settings()
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    if not files:
        return None
    try:
        reader = SimpleDirectoryReader(input_files=[str(f) for f in files])
        documents = reader.load_data()
        # Tag every node so retrieved chunks know where they came from
        for d in documents:
            d.metadata["scope_key"] = scope_key
            d.metadata["tier"] = _tier_for(scope_key)
        index = VectorStoreIndex.from_documents(documents)
        index_dir = _index_dir_for(scope_key)
        index_dir.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(persist_dir=str(index_dir))
        node_count = len(index.docstore.docs) if hasattr(index, "docstore") else 0
        logger.info(f"Built index for scope {scope_key}: {len(files)} files → {node_count} nodes")
        return index
    except Exception as e:
        logger.error(f"Failed to build index for scope {scope_key}: {e}")
        return None


def _load_index(scope_key: str) -> Any | None:
    """Load a persisted index from disk, or None if not present / broken."""
    from llama_index.core import StorageContext, load_index_from_storage

    index_dir = _index_dir_for(scope_key)
    if not (index_dir / "index_store.json").exists():
        return None
    _setup_settings()
    try:
        sc = StorageContext.from_defaults(persist_dir=str(index_dir))
        idx = load_index_from_storage(sc)
        node_count = len(idx.docstore.docs) if hasattr(idx, "docstore") else 0
        logger.info(f"Loaded existing index for scope {scope_key} ({node_count} nodes)")
        return idx
    except Exception as e:
        logger.warning(f"Failed to load index for scope {scope_key} ({e}); will rebuild on next access")
        return None


def get_index(scope_key: str) -> Any | None:
    """Return the index for a scope (cache → disk → build). Thread-safe."""
    with _indexes_lock:
        if scope_key in _indexes:
            return _indexes[scope_key]
    # Heavy work outside the lock to avoid blocking other scopes
    idx = _load_index(scope_key) or _build_index(scope_key)
    with _indexes_lock:
        if idx is not None:
            _indexes[scope_key] = idx
    return idx


# --- Public API ---

def reindex(scope_key: str) -> dict[str, Any]:
    """Force a rebuild for a single scope. Used by:
    - Admin "Reindex" button
    - Sprint 5 file watcher when a debounce window expires for the scope
    """
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    if not files:
        with _indexes_lock:
            _indexes.pop(scope_key, None)
        index_dir = _index_dir_for(scope_key)
        if index_dir.exists():
            shutil.rmtree(index_dir, ignore_errors=True)
        logger.info(f"Reindex {scope_key}: no docs — index cleared")
        return {"scope_key": scope_key, "document_count": 0, "node_count": 0}

    new_idx = _build_index(scope_key)
    with _indexes_lock:
        _indexes[scope_key] = new_idx
    node_count = len(new_idx.docstore.docs) if new_idx and hasattr(new_idx, "docstore") else 0
    _sync_derived_country_tags(scope_key)
    return {"scope_key": scope_key, "document_count": len(files), "node_count": node_count}


def _sync_derived_country_tags(scope_key: str) -> None:
    """Company-tier scopes only: refresh `Company.country_tags` from the docs'
    metadata.json. No-op for global / frontend scopes (those don't have a
    Company record).
    """
    if "/" not in scope_key:
        return
    fid, slug = scope_key.split("/", 1)
    try:
        from src.services import company_registry, document_metadata
        tags = document_metadata.derive_country_tags(scope_key)
        company_registry.update_company(fid, slug, {"country_tags": tags})
        logger.info(f"Derived country_tags for {scope_key}: {tags}")
    except Exception as e:
        logger.warning(f"Could not sync derived country_tags for {scope_key}: {e}")


def invalidate(scope_key: str) -> None:
    """Drop the in-memory entry without rebuilding. Next access reloads from
    disk (or rebuilds). File watcher uses this when a debounce expires AND
    we want to defer the (potentially expensive) rebuild to the first query.
    """
    with _indexes_lock:
        _indexes.pop(scope_key, None)


def query(scope_key: str, query_text: str, top_k: int = DEFAULT_TOP_K) -> list[Chunk]:
    """Retrieve top-k chunks from one scope. Returns [] when there's no index."""
    idx = get_index(scope_key)
    if idx is None:
        return []
    try:
        retriever = idx.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query_text)
        return [
            Chunk(
                text=n.node.text,
                score=getattr(n, "score", 0.0) or 0.0,
                source=n.node.metadata.get("file_name", "(unknown)"),
                tier=n.node.metadata.get("tier", _tier_for(scope_key)),
                scope_key=scope_key,
            )
            for n in nodes
        ]
    except Exception as e:
        logger.error(f"Query failed on scope {scope_key}: {e}")
        return []


def query_scopes(
    scope_keys: list[str],
    query_text: str,
    top_k_per_scope: int = DEFAULT_TOP_K,
) -> list[Chunk]:
    """Query several scopes and concatenate results sorted by score.

    Sprint 6 may add reranking / dedup; for now this is enough for the
    chat engine to assemble a context block.
    """
    out: list[Chunk] = []
    for sk in scope_keys:
        out.extend(query(sk, query_text, top_k_per_scope))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def index_stats(scope_key: str) -> dict[str, Any]:
    """Cheap read of file count + on-disk index presence. Doesn't load the index."""
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    index_dir = _index_dir_for(scope_key)
    has_index = (index_dir / "index_store.json").exists()
    return {
        "scope_key": scope_key,
        "document_count": len(files),
        "indexed": has_index,
    }
