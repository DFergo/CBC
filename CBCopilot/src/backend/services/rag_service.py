"""LlamaIndex-backed RAG service.

A "scope" is one of (global, frontend_id, frontend_id+company_slug). Each
scope has its own `documents/` folder and a sibling `rag_index/` folder
where the persisted index lives. The service caches in-memory
VectorStoreIndex objects keyed by `scope_key` and uses the same scope_key
shape that `resolvers.resolve_rag_paths` returns — the chat engine in
Sprint 6 just calls `query_scopes(resolver_paths, query)`.

Pipeline (Sprint 9):
1. Ingest — SimpleDirectoryReader → markdown-aware parser for .md, sentence
   splitter for everything else. Optional Contextual Retrieval prepends a
   short LLM-generated context to each chunk (off by default).
2. Embed — BGE-M3 (1024-dim, multilingual). Drop-in via HuggingFaceEmbedding.
3. Retrieve — hybrid BM25 + vector via QueryFusionRetriever, fetch top
   `rag_reranker_fetch_k` candidates.
4. Rerank — cross-encoder bge-reranker-v2-m3 reduces to top
   `rag_reranker_top_n`. Skipped if rag_reranker_enabled = False.

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

from src.core.config import config as backend_config
from src.services._paths import (
    DATA_DIR,
    DOCUMENTS_DIR,
    company_dir,
    frontend_dir,
)

logger = logging.getLogger("rag")

# These are kept as module constants in case session_rag.py imports them
# directly. The runtime values come from backend_config so admins can tune
# them via deployment_backend.json without redeploying code.
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 8

# Admin RAG accepts these. Session RAG additionally accepts .docx (handled in
# session_rag.py — Phase D).
ADMIN_ALLOWED_EXTS = {".pdf", ".txt", ".md"}

# Lazy-loaded singletons.
_embed_model: Any = None
_embed_lock = threading.Lock()
_reranker: Any = None
_reranker_lock = threading.Lock()

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
    Model name is admin-configurable via `rag_embedding_model` in
    deployment_backend.json (default: BAAI/bge-m3).
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is None:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            model_name = backend_config.rag_embedding_model
            _embed_model = HuggingFaceEmbedding(model_name=model_name)
            logger.info(f"Loaded embedding model {model_name}")
    return _embed_model


def _get_reranker() -> Any | None:
    """Lazy-load the cross-encoder reranker. Returns None if disabled in
    config or if the package isn't available."""
    if not backend_config.rag_reranker_enabled:
        return None
    global _reranker
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is None:
            try:
                from llama_index.core.postprocessor import SentenceTransformerRerank
                _reranker = SentenceTransformerRerank(
                    model=backend_config.rag_reranker_model,
                    top_n=backend_config.rag_reranker_top_n,
                )
                logger.info(f"Loaded reranker {backend_config.rag_reranker_model}")
            except Exception as e:
                logger.warning(f"Reranker unavailable ({e}); falling back to no rerank")
                return None
    return _reranker


def _setup_settings() -> None:
    """Configure LlamaIndex's global Settings. Cheap to call repeatedly."""
    from llama_index.core import Settings
    Settings.embed_model = _get_embed_model()
    Settings.llm = None  # we drive the LLM ourselves; LlamaIndex never calls one
    Settings.chunk_size = backend_config.rag_chunk_size
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


def _parse_nodes(documents: list[Any]) -> list[Any]:
    """Route docs through the right chunker by file extension.

    Markdown: MarkdownNodeParser splits by header, so a section like
    "## ANEXO I — Tablas salariales" stays WITH its table rows in the same
    node. Critical for CBA annexes where the heading is the only semantic
    ground for otherwise numeric content.

    Everything else: SentenceSplitter with the configured chunk size/overlap.
    """
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter

    md_docs: list[Any] = []
    other_docs: list[Any] = []
    for d in documents:
        name = (d.metadata or {}).get("file_name", "") or (d.metadata or {}).get("file_path", "") or ""
        if name.lower().endswith(".md"):
            md_docs.append(d)
        else:
            other_docs.append(d)

    nodes: list[Any] = []
    if md_docs:
        md_parser = MarkdownNodeParser()
        nodes.extend(md_parser.get_nodes_from_documents(md_docs))
    if other_docs:
        sentence_parser = SentenceSplitter(
            chunk_size=backend_config.rag_chunk_size,
            chunk_overlap=CHUNK_OVERLAP,
        )
        nodes.extend(sentence_parser.get_nodes_from_documents(other_docs))
    return nodes


# --- Anthropic Contextual Retrieval (toggleable) ---
# When `rag_contextual_enabled` is True, every chunk gets a short LLM-generated
# context sentence prepended at index time so embeddings carry document-level
# grounding. Approach from Anthropic's Sept-2024 paper, adapted to call the
# local summariser slot instead of Claude.

_CONTEXT_PROMPT = """\
<document>
{document}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>

Please give a short, succinct context (1-2 sentences, max 60 words) that
situates this chunk within the overall document for the purposes of improving
search retrieval of the chunk. Mention the section / annex / article number
when applicable. Answer ONLY with the succinct context, no preamble.\
"""


def _generate_chunk_context(document_text: str, chunk_text: str) -> str:
    """One synchronous call to the summariser slot to produce a context line.
    Errors are swallowed — we return "" so the chunk still indexes without
    enrichment rather than blocking the whole reindex on a transient LLM hiccup.

    Uses a private event loop so this works whether the caller is on the
    FastAPI main loop (admin reindex) or a background thread (file watcher).
    """
    import asyncio

    from src.services import llm_provider

    doc_excerpt = (document_text or "")[: backend_config.rag_contextual_max_doc_chars]
    prompt = _CONTEXT_PROMPT.format(document=doc_excerpt, chunk=chunk_text)
    messages = [{"role": "user", "content": prompt}]
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                llm_provider.chat(messages, slot="summariser", frontend_id=None)
            )
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Contextual enrichment failed for one chunk: {e}")
        return ""


def _contextualise_nodes(nodes: list[Any], documents: list[Any]) -> None:
    """Mutate `nodes` in place — prepend an LLM-generated context line to each
    node's text. Per-document text is fetched from `documents` by file_name
    so chunks know what's around them.

    Cost: one LLM call per chunk. With ~25 chunks per doc and a local summariser
    at 10-30 s per call, expect 5-15 minutes per document. Surface progress in
    the log so admins see it isn't stuck.
    """
    if not nodes:
        return
    # Index documents by file_name for quick lookup
    doc_by_file: dict[str, str] = {}
    for d in documents:
        fname = (d.metadata or {}).get("file_name") or ""
        if fname:
            doc_by_file[fname] = (d.text or "")

    total = len(nodes)
    enriched = 0
    for i, node in enumerate(nodes):
        fname = (node.metadata or {}).get("file_name") or ""
        doc_text = doc_by_file.get(fname, "")
        if not doc_text or not node.text:
            continue
        context = _generate_chunk_context(doc_text, node.text).strip()
        if context:
            # Anthropic's recipe: prepend the context with a header so both
            # the embedder and BM25 weigh it correctly.
            node.set_content(f"[CONTEXT] {context}\n\n{node.text}")
            enriched += 1
        if (i + 1) % 5 == 0 or (i + 1) == total:
            logger.info(f"Contextual enrichment: {i + 1}/{total} chunks ({enriched} enriched)")


def _build_index(scope_key: str) -> Any | None:
    """Build a fresh VectorStoreIndex from disk. Returns None if no docs."""
    from llama_index.core import SimpleDirectoryReader, VectorStoreIndex

    _setup_settings()
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    if not files:
        return None
    try:
        reader = SimpleDirectoryReader(input_files=[str(f) for f in files])
        documents = reader.load_data()
        nodes = _parse_nodes(documents)
        # Tag every node so retrieved chunks know where they came from. The
        # node parsers copy doc metadata onto each node already, we just add
        # scope_key + tier on top.
        for n in nodes:
            n.metadata["scope_key"] = scope_key
            n.metadata["tier"] = _tier_for(scope_key)
        # Anthropic Contextual Retrieval: prepend an LLM-generated context
        # line to every chunk. Gated behind the global toggle because it adds
        # substantial LLM cost at index time.
        if backend_config.rag_contextual_enabled:
            logger.info(
                f"Contextual enrichment ON — generating context for "
                f"{len(nodes)} chunks in scope {scope_key} (this will take a while)"
            )
            _contextualise_nodes(nodes, documents)
        index = VectorStoreIndex(nodes)
        index_dir = _index_dir_for(scope_key)
        index_dir.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(persist_dir=str(index_dir))
        logger.info(
            f"Built index for scope {scope_key}: {len(files)} files → {len(nodes)} nodes "
            f"({sum(1 for d in documents if (d.metadata or {}).get('file_name','').lower().endswith('.md'))} markdown)"
        )
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


def _discover_all_scope_keys() -> list[str]:
    """Enumerate every scope that currently has a documents/ folder on disk:
    global, each frontend, and each company under each frontend. Used by
    reindex_all_scopes when toggling Contextual Retrieval or another
    corpus-wide change.
    """
    from src.services._paths import CAMPAIGNS_DIR
    out: list[str] = ["global"]
    if not CAMPAIGNS_DIR.exists():
        return out
    for fe_dir in CAMPAIGNS_DIR.iterdir():
        if not fe_dir.is_dir():
            continue
        fid = fe_dir.name
        if (fe_dir / "documents").exists():
            out.append(fid)
        companies_dir = fe_dir / "companies"
        if companies_dir.exists():
            for co_dir in companies_dir.iterdir():
                if not co_dir.is_dir():
                    continue
                if (co_dir / "documents").exists():
                    out.append(f"{fid}/{co_dir.name}")
    return out


def reindex_all_scopes() -> list[dict[str, Any]]:
    """Rebuild every scope's index. Used when a pipeline-wide setting changes
    (embedder, chunk size, Contextual Retrieval). Returns one stats dict per
    scope so the caller can surface per-scope counts.
    """
    out: list[dict[str, Any]] = []
    for sk in _discover_all_scope_keys():
        try:
            out.append(reindex(sk))
        except Exception as e:
            logger.exception(f"reindex_all_scopes: scope {sk} failed: {e}")
            out.append({"scope_key": sk, "error": str(e)})
    return out


def _hybrid_retrieve(idx: Any, query_text: str, fetch_k: int) -> list[Any]:
    """Fuse dense (BGE-M3) + lexical (BM25) retrieval and return ranked
    NodeWithScore objects. BGE-M3 is strong multilingual, BM25 catches exact
    keyword hits ("Anexo I", "Salarios diarios") that dense retrievers can
    still miss on short-form numeric content. Reciprocal rank fusion combines
    them. Falls back to pure vector retrieval if BM25 isn't available.
    """
    vector_retriever = idx.as_retriever(similarity_top_k=fetch_k)
    try:
        from llama_index.core.retrievers import QueryFusionRetriever
        from llama_index.retrievers.bm25 import BM25Retriever

        nodes = list(idx.docstore.docs.values())
        if not nodes:
            return vector_retriever.retrieve(query_text)
        bm25_retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=fetch_k)
        fused = QueryFusionRetriever(
            [vector_retriever, bm25_retriever],
            similarity_top_k=fetch_k,
            num_queries=1,  # no LLM-driven query expansion; we have no LLM wired into Settings
            mode="reciprocal_rerank",
            use_async=False,
            verbose=False,
        )
        return fused.retrieve(query_text)
    except Exception as e:
        logger.warning(f"Hybrid retrieval unavailable ({e}); falling back to vector-only")
        return vector_retriever.retrieve(query_text)


def _rerank(nodes: list[Any], query_text: str, top_n: int) -> list[Any]:
    """Cross-encoder reranker pass over the hybrid candidates. Narrows the
    fetched set down to the most relevant top_n using bge-reranker-v2-m3.
    Returns `nodes` unchanged if the reranker isn't available."""
    rr = _get_reranker()
    if rr is None or not nodes:
        return nodes[:top_n]
    try:
        from llama_index.core import QueryBundle
        reranked = rr.postprocess_nodes(nodes, query_bundle=QueryBundle(query_text))
        return reranked[:top_n]
    except Exception as e:
        logger.warning(f"Rerank failed ({e}); using hybrid order")
        return nodes[:top_n]


def query(scope_key: str, query_text: str, top_k: int | None = None) -> list[Chunk]:
    """Retrieve top-k chunks from one scope. Returns [] when there's no index.

    Pipeline: hybrid retrieve `rag_reranker_fetch_k` → cross-encoder rerank to
    `rag_reranker_top_n` (or the explicit `top_k` if passed).
    """
    idx = get_index(scope_key)
    if idx is None:
        return []
    try:
        fetch_k = max(
            backend_config.rag_reranker_fetch_k,
            top_k or backend_config.rag_reranker_top_n,
        )
        nodes = _hybrid_retrieve(idx, query_text, fetch_k)
        final_top_n = top_k or backend_config.rag_reranker_top_n
        nodes = _rerank(nodes, query_text, final_top_n)
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
    top_k_per_scope: int | None = None,
) -> list[Chunk]:
    """Query several scopes and concatenate results sorted by score. Per-scope
    top_k defaults to `rag_reranker_top_n` from config, so scope_keys that
    contribute nothing simply drop out.
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
