"""LlamaIndex-backed RAG service over a single ChromaDB collection.

A "scope" is one of (global, frontend_id, frontend_id+company_slug). Each
scope has its own `documents/` folder on disk; in storage every chunk
lives in ONE ChromaDB collection at `/app/data/chroma/`, tagged with its
`scope_key` in metadata. Query-time filtering by `scope_key` keeps each
scope's results isolated, while retrieval / reranking / BM25 all run over
the same collection — no per-scope index files, no in-memory dance.

Pipeline (Sprint 10C):
1. Ingest — SimpleDirectoryReader → markdown-aware parser for .md, sentence
   splitter for everything else. Optional Contextual Retrieval prepends a
   short LLM-generated context to each chunk (off by default).
2. Embed — BGE-M3 (1024-dim, multilingual). Drop-in via HuggingFaceEmbedding.
3. Store — ChromaDB persistent collection (HNSW under the hood); `scope_key`
   carried as metadata so one collection serves global / frontend / company
   tiers via metadata filters at query time.
4. Retrieve — hybrid BM25 + vector via QueryFusionRetriever, fetched within
   the scope-filtered candidate pool. BM25 corpus is rebuilt per query from
   the scope's nodes (cheap — Chroma `.get(where=)` is fast).
5. Rerank — cross-encoder bge-reranker-v2-m3 narrows candidates down to
   `rag_reranker_top_n`. Skipped when `rag_reranker_enabled = False`.

Design rules:
- Single persistent Chroma collection. No per-scope JSON index files.
- `invalidate(scope_key)` drops the in-memory wrapper; collection is intact.
- `reindex(scope_key)` deletes that scope's chunks from the collection and
  re-ingests from disk.
- Heavy imports (`chromadb`, `llama_index`, `sentence_transformers`) defer
  until first use — keeps `import` graph cheap for tests + cold paths.
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

# Single Chroma persistent client + collection. All scopes live here.
_chroma_client: Any = None
_chroma_collection: Any = None
_chroma_lock = threading.Lock()
CHROMA_DIR = DATA_DIR / "chroma"
CHROMA_COLLECTION_NAME = "cbc_chunks"

# Per-scope cached LlamaIndex wrappers. Wrapping is cheap, but keeping the
# index objects around avoids reconstructing the StorageContext per query.
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
    # Sprint 11 Phase B — best-available citation pointer inside the source
    # document. Populated from PDFReader's `page_label` metadata when present;
    # empty otherwise (the prompt assembler will fall back to an article /
    # annex regex on the chunk body when it needs a human-readable reference).
    page_label: str = ""


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


def _get_chroma_collection() -> Any:
    """Lazy-init the persistent Chroma client + the single shared collection
    that holds every scope's chunks. Returned object is a ``chromadb`` Collection.
    """
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    with _chroma_lock:
        if _chroma_collection is None:
            import chromadb
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            _chroma_collection = _chroma_client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"Chroma collection {CHROMA_COLLECTION_NAME!r} ready at {CHROMA_DIR} "
                f"({_chroma_collection.count()} chunks total)"
            )
    return _chroma_collection


def _scope_metadata_filter(scope_key: str) -> Any:
    """Return a LlamaIndex MetadataFilters that pins the search to one scope."""
    from llama_index.core.vector_stores.types import (
        ExactMatchFilter,
        MetadataFilters,
    )
    return MetadataFilters(filters=[ExactMatchFilter(key="scope_key", value=scope_key)])


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


def _scope_index_wrapper(scope_key: str) -> Any:
    """Build a thin LlamaIndex VectorStoreIndex that points at the shared
    Chroma collection. The same wrapper works for query-time use; ingest-time
    use is the same call but with explicit `nodes`. Wrapper objects are cheap
    to construct but we cache them per-scope to avoid the StorageContext
    rebuild cost on every query."""
    from llama_index.core import StorageContext, VectorStoreIndex
    from llama_index.vector_stores.chroma import ChromaVectorStore

    _setup_settings()
    collection = _get_chroma_collection()
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        storage_context=storage_context,
    )


def _scope_chunk_count(scope_key: str) -> int:
    """How many chunks the Chroma collection currently holds for this scope.
    Used by stats endpoints + the get_index existence check."""
    try:
        collection = _get_chroma_collection()
        result = collection.get(where={"scope_key": scope_key}, limit=1, include=[])
        # `include=[]` returns just the IDs — counting via .count() with where
        # is not supported by all chroma versions, so do a small probe instead
        # then fall back to a full IDs fetch only when we need the actual
        # number rather than "is it > 0".
        if not result.get("ids"):
            return 0
        # Need the full count — fetch all IDs (cheap; metadata only).
        full = collection.get(where={"scope_key": scope_key}, include=[])
        return len(full.get("ids") or [])
    except Exception as e:
        logger.warning(f"Could not count chunks for scope {scope_key}: {e}")
        return 0


def _build_index(scope_key: str) -> Any | None:
    """Ingest every doc in this scope into the shared Chroma collection.
    Replaces any existing chunks for the scope first. Returns the LlamaIndex
    wrapper (or None if there are no docs)."""
    from llama_index.core import SimpleDirectoryReader

    _setup_settings()
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    if not files:
        # Make sure stale chunks for this scope are gone.
        _delete_scope(scope_key)
        return None
    try:
        reader = SimpleDirectoryReader(input_files=[str(f) for f in files])
        documents = reader.load_data()
        nodes = _parse_nodes(documents)
        for n in nodes:
            n.metadata["scope_key"] = scope_key
            n.metadata["tier"] = _tier_for(scope_key)
        if backend_config.rag_contextual_enabled:
            logger.info(
                f"Contextual enrichment ON — generating context for "
                f"{len(nodes)} chunks in scope {scope_key} (this will take a while)"
            )
            _contextualise_nodes(nodes, documents)

        # Drop existing chunks for this scope so we don't accumulate ghosts
        # on re-ingest. Then insert fresh nodes via LlamaIndex's wrapper —
        # ChromaVectorStore.add() handles the embeddings + metadata write.
        _delete_scope(scope_key)
        wrapper = _scope_index_wrapper(scope_key)
        wrapper.insert_nodes(nodes)

        logger.info(
            f"Built Chroma chunks for scope {scope_key}: {len(files)} files → "
            f"{len(nodes)} nodes "
            f"({sum(1 for d in documents if (d.metadata or {}).get('file_name','').lower().endswith('.md'))} markdown)"
        )
        return wrapper
    except Exception as e:
        logger.error(f"Failed to build index for scope {scope_key}: {e}")
        return None


def _delete_scope(scope_key: str) -> None:
    """Remove every chunk tagged with this scope_key from the Chroma collection."""
    try:
        collection = _get_chroma_collection()
        collection.delete(where={"scope_key": scope_key})
    except Exception as e:
        logger.warning(f"Could not delete chunks for scope {scope_key}: {e}")


def get_index(scope_key: str) -> Any | None:
    """Return the LlamaIndex wrapper for a scope (cache → build-if-empty).

    With Chroma the storage is the collection itself — the wrapper is just a
    LlamaIndex façade. We cache the wrapper to skip StorageContext rebuilds
    on hot paths but it's safe to discard at any time.
    """
    with _indexes_lock:
        if scope_key in _indexes:
            return _indexes[scope_key]

    if _scope_chunk_count(scope_key) > 0:
        wrapper = _scope_index_wrapper(scope_key)
    else:
        wrapper = _build_index(scope_key)

    with _indexes_lock:
        if wrapper is not None:
            _indexes[scope_key] = wrapper
    return wrapper


# --- Public API ---

def reindex(scope_key: str) -> dict[str, Any]:
    """Force a rebuild for a single scope. Used by:
    - Admin "Reindex" button
    - Sprint 5 file watcher when a debounce window expires for the scope
    Also wipes any legacy `rag_index/` JSON dir left over from the
    pre-Sprint-10C SimpleVectorStore layout.
    """
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)

    # Sweep legacy per-scope JSON index directory if still around.
    legacy_dir = _index_dir_for(scope_key)
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir, ignore_errors=True)

    if not files:
        with _indexes_lock:
            _indexes.pop(scope_key, None)
        _delete_scope(scope_key)
        logger.info(f"Reindex {scope_key}: no docs — chunks cleared")
        return {"scope_key": scope_key, "document_count": 0, "node_count": 0}

    new_idx = _build_index(scope_key)
    with _indexes_lock:
        _indexes[scope_key] = new_idx
    node_count = _scope_chunk_count(scope_key)
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
    (embedder, chunk size, Contextual Retrieval) or when the admin triggers a
    global-cascade reindex. Returns one stats dict per scope.
    """
    out: list[dict[str, Any]] = []
    for sk in _discover_all_scope_keys():
        try:
            out.append(reindex(sk))
        except Exception as e:
            logger.exception(f"reindex_all_scopes: scope {sk} failed: {e}")
            out.append({"scope_key": sk, "error": str(e)})
    return out


def reindex_frontend_cascade(frontend_id: str) -> list[dict[str, Any]]:
    """Rebuild the frontend-tier index plus every company under it. Used by
    the frontend-tier RAGSection's "Reindex frontend + companies" button.
    The global scope is NOT touched.
    """
    from src.services._paths import CAMPAIGNS_DIR
    targets: list[str] = [frontend_id]
    companies_dir = CAMPAIGNS_DIR / frontend_id / "companies"
    if companies_dir.exists():
        for co_dir in companies_dir.iterdir():
            if co_dir.is_dir() and (co_dir / "documents").exists():
                targets.append(f"{frontend_id}/{co_dir.name}")
    out: list[dict[str, Any]] = []
    for sk in targets:
        try:
            out.append(reindex(sk))
        except Exception as e:
            logger.exception(f"reindex_frontend_cascade: scope {sk} failed: {e}")
            out.append({"scope_key": sk, "error": str(e)})
    return out


def _scope_nodes_from_chroma(scope_key: str) -> list[Any]:
    """Pull every TextNode for a scope back out of the Chroma collection.
    Used to feed the per-query BM25 corpus. Cheap because we only fetch the
    (text, metadata) projection, no embeddings."""
    from llama_index.core.schema import TextNode

    collection = _get_chroma_collection()
    try:
        raw = collection.get(
            where={"scope_key": scope_key},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        logger.warning(f"Could not fetch nodes for BM25 in scope {scope_key}: {e}")
        return []

    ids = raw.get("ids") or []
    docs = raw.get("documents") or []
    metas = raw.get("metadatas") or []
    nodes: list[Any] = []
    for i, doc_id in enumerate(ids):
        text = docs[i] if i < len(docs) else ""
        meta = metas[i] if i < len(metas) else {}
        nodes.append(TextNode(id_=doc_id, text=text or "", metadata=meta or {}))
    return nodes


def _hybrid_retrieve(scope_key: str, idx: Any, query_text: str, fetch_k: int) -> list[Any]:
    """Fuse dense (BGE-M3, scope-filtered) + lexical (BM25 over scope nodes)
    and return ranked NodeWithScore objects. Reciprocal rank fusion combines
    them. Falls back to pure vector retrieval if BM25 isn't available.

    Both retrievers are pinned to the same scope: the vector side via a
    Chroma metadata filter, the BM25 side via the docs we hand to it.
    """
    vector_retriever = idx.as_retriever(
        similarity_top_k=fetch_k,
        filters=_scope_metadata_filter(scope_key),
    )
    try:
        from llama_index.core.retrievers import QueryFusionRetriever
        from llama_index.retrievers.bm25 import BM25Retriever

        scope_nodes = _scope_nodes_from_chroma(scope_key)
        if not scope_nodes:
            return vector_retriever.retrieve(query_text)
        bm25_retriever = BM25Retriever.from_defaults(
            nodes=scope_nodes,
            similarity_top_k=fetch_k,
        )
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
    """Retrieve top-k chunks from one scope. Returns [] when the scope is
    empty (no docs ingested yet).

    Pipeline: scope-filtered hybrid retrieve `rag_reranker_fetch_k` chunks
    from the shared Chroma collection → cross-encoder rerank to
    `rag_reranker_top_n` (or the explicit `top_k` if passed).
    """
    idx = get_index(scope_key)
    if idx is None or _scope_chunk_count(scope_key) == 0:
        return []
    try:
        fetch_k = max(
            backend_config.rag_reranker_fetch_k,
            top_k or backend_config.rag_reranker_top_n,
        )
        nodes = _hybrid_retrieve(scope_key, idx, query_text, fetch_k)
        final_top_n = top_k or backend_config.rag_reranker_top_n
        nodes = _rerank(nodes, query_text, final_top_n)
        return [
            Chunk(
                text=n.node.text,
                score=getattr(n, "score", 0.0) or 0.0,
                source=n.node.metadata.get("file_name", "(unknown)"),
                tier=n.node.metadata.get("tier", _tier_for(scope_key)),
                scope_key=scope_key,
                page_label=str(n.node.metadata.get("page_label") or ""),
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
    """Cheap read of file count + Chroma chunk count for the scope.
    "indexed" is True iff at least one chunk lives in the collection for it."""
    docs_dir = _docs_dir_for(scope_key)
    files = _list_indexable_files(docs_dir)
    n_chunks = _scope_chunk_count(scope_key)
    return {
        "scope_key": scope_key,
        "document_count": len(files),
        "indexed": n_chunks > 0,
        "node_count": n_chunks,
    }
