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

    `allow_reset=True` in Settings lets `wipe_chroma_and_reindex_all()` call
    `client.reset()` to fully clear in-memory state AND on-disk data in one
    atomic step — without this, reset() silently no-ops (chromadb's default
    safeguard) and a subsequent rmtree leaves the client's cached collection
    schema in a broken state (e.g. a 384-dim collection trying to accept
    1024-dim embeddings from a swapped embedder).
    """
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    with _chroma_lock:
        if _chroma_collection is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=ChromaSettings(allow_reset=True),
            )
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

    Markdown: MarkdownNodeParser splits by markdown heading, which preserves
    the section label as metadata on every node (e.g. "ANEXO I — Tablas
    salariales" stays tied to its table rows). BUT MarkdownNodeParser does
    NOT enforce a token cap — a heading with a 30 k-token body comes out as
    ONE node. For big CBAs structured under a few top-level headings, that
    produced one giant node per document, which:
      - silently truncated BGE-M3 embeddings (model cap is 8192 tokens) —
        retrieval only "saw" the first ~30 % of the document.
      - injected the entire document into every turn's system prompt (the
        `## Retrieved CBA / policy excerpts` section ballooned to 125 k chars).
      - killed Ollama's prefix cache utility (every turn re-prefilled a huge
        prompt; re-question TTFT stuck at 30-90 s instead of ~10 s).

    Sprint 15 fix: pipe markdown nodes through a second-pass SentenceSplitter
    that enforces the configured chunk_size cap. Header metadata is preserved
    on every sub-node by re-wrapping the text in a fresh Document with the
    parent node's metadata before re-splitting.

    Everything else (.pdf / .txt / .docx): SentenceSplitter directly with the
    configured chunk size/overlap — unchanged, this path was always correct.
    """
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
    from llama_index.core.schema import Document

    md_docs: list[Any] = []
    other_docs: list[Any] = []
    for d in documents:
        name = (d.metadata or {}).get("file_name", "") or (d.metadata or {}).get("file_path", "") or ""
        if name.lower().endswith(".md"):
            md_docs.append(d)
        else:
            other_docs.append(d)

    sentence_parser = SentenceSplitter(
        chunk_size=backend_config.rag_chunk_size,
        chunk_overlap=CHUNK_OVERLAP,
    )

    nodes: list[Any] = []
    if md_docs:
        md_parser = MarkdownNodeParser()
        md_header_nodes = md_parser.get_nodes_from_documents(md_docs)
        # Second pass: any md node that exceeds chunk_size gets split further.
        # Rewrapping as Document preserves the header-derived metadata onto
        # every sub-chunk (Sprint 11 Phase B inline citations depend on it).
        for hn in md_header_nodes:
            wrapper = Document(text=hn.text, metadata=hn.metadata or {})
            nodes.extend(sentence_parser.get_nodes_from_documents([wrapper]))
    if other_docs:
        nodes.extend(sentence_parser.get_nodes_from_documents(other_docs))

    # Observability: per-document summary so future regressions are visible
    # without pulling session JSONs. Enumerates one log line per input doc.
    if documents:
        by_doc: dict[str, list[int]] = {}
        for n in nodes:
            key = (n.metadata or {}).get("file_name") or (n.metadata or {}).get("file_path") or "?"
            by_doc.setdefault(key, []).append(len(n.text or ""))
        for name, sizes in by_doc.items():
            if not sizes:
                continue
            logger.info(
                f"chunker: {name} → {len(sizes)} nodes "
                f"(max={max(sizes)} chars, min={min(sizes)} chars, "
                f"mean={sum(sizes) // len(sizes)} chars)"
            )
            # Defensive warning: a node exceeding BGE-M3's 8192-token input
            # cap gets silently truncated in the embedding, degrading recall
            # for the remainder of its text. Rough char→token ratio 3 for ES.
            suspect = max(sizes)
            if suspect > 30000:
                logger.warning(
                    f"chunker: {name} has a {suspect}-char node — probably "
                    f">8192 tokens → BGE-M3 embedding will be TRUNCATED. "
                    f"Expected ≤4500 chars per chunk at chunk_size=1024."
                )
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
    # Drop the cached BM25 retriever for this scope so the next query rebuilds
    # fresh. Sprint 15 H — prevents stale retrievers after a reindex.
    _invalidate_bm25_cache(scope_key)


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


def wipe_chroma_and_reindex_all() -> dict[str, Any]:
    """Delete the entire Chroma collection + all caches, then rebuild every
    scope from scratch. Required whenever the embedding model or chunk size
    changes, because:

    - Embedding dim change (e.g. MiniLM 384 → BGE-M3 1024) makes existing
      vectors incompatible with new ones in the same Chroma collection.
    - Chunk size change produces a different set of nodes; keeping legacy
      chunks alongside new ones would confuse retrieval and double-count.

    Sprint 15 phase 3.1 rewrite — the original shutil.rmtree approach left
    chromadb's in-memory client with a stale cached collection schema,
    producing "Collection expecting dim 384, got 1024" errors after every
    wipe. Fix: require `client.reset()` to succeed (which needs the client
    initialised with `allow_reset=True`) — it atomically clears in-memory
    state AND on-disk data. Only if reset fails do we fall back to rmtree.

    Steps:
    1. Drop every in-memory cache so the next call picks up new config.
    2. Call `client.reset()` — atomic wipe of in-memory + on-disk state.
       Belt-and-braces rmtree after, in case reset missed a directory.
    3. Call `reindex_all_scopes()` and raise if any scope fails, so the
       admin UI surfaces the problem instead of showing a false-positive
       "done" state over a broken index.

    Returns: `{"scopes_reindexed": N, "stats": [...], "embedding_model": ...,
               "chunk_size": ...}` when every scope ingested successfully.
    Raises on any ingestion failure — partial states are never acceptable.
    """
    global _chroma_client, _chroma_collection, _embed_model, _reranker
    import shutil

    logger.warning(
        f"Wipe & reindex triggered: chroma={CHROMA_DIR}, "
        f"new embedding={backend_config.rag_embedding_model}, "
        f"new chunk_size={backend_config.rag_chunk_size}"
    )

    # 1. Drop in-memory caches.
    with _indexes_lock:
        _indexes.clear()
    _invalidate_bm25_cache(None)  # all scopes
    with _embed_lock:
        _embed_model = None
    with _reranker_lock:
        _reranker = None

    # 2. Nuke Chroma. `client.reset()` is the supported path (allow_reset=True
    #    in the client Settings, see _get_chroma_collection). Fall back to
    #    manual rmtree only if reset fails.
    with _chroma_lock:
        reset_ok = False
        if _chroma_client is not None:
            try:
                _chroma_client.reset()
                reset_ok = True
                logger.info("Chroma client.reset() succeeded — in-memory + on-disk cleared")
            except Exception as e:
                logger.warning(f"Chroma client.reset() failed, falling back to rmtree: {e}")
        _chroma_client = None
        _chroma_collection = None
        if not reset_ok and CHROMA_DIR.exists():
            try:
                shutil.rmtree(CHROMA_DIR, ignore_errors=False)
                logger.info(f"Fallback rmtree of {CHROMA_DIR} succeeded")
            except OSError as e:
                logger.error(f"Could not remove chroma dir {CHROMA_DIR}: {e}")
                raise

    # 3. Rebuild every scope. `_get_chroma_collection()` creates a fresh
    #    collection on demand when `reindex()` calls `_scope_index_wrapper()`.
    #    Critically: every scope's ingest must succeed — a mixed state where
    #    some scopes embedded fine and others errored is worse than failing
    #    loudly and forcing the admin to retry.
    stats = reindex_all_scopes()
    errs = [s for s in stats if s.get("error")]
    if errs:
        err_summary = "; ".join(f"{s['scope_key']}: {s['error']}" for s in errs[:5])
        raise RuntimeError(
            f"{len(errs)}/{len(stats)} scopes failed to reindex after wipe. "
            f"First failures: {err_summary}"
        )

    return {
        "scopes_reindexed": len(stats),
        "stats": stats,
        "embedding_model": backend_config.rag_embedding_model,
        "chunk_size": backend_config.rag_chunk_size,
    }


# Allowlist of embedding models that the Dockerfile pre-downloads. Admins
# picking one outside this list would force a network download at request
# time (slow, may fail with no HF token) — so we refuse the change.
SUPPORTED_EMBEDDING_MODELS: tuple[str, ...] = (
    "BAAI/bge-m3",
    "sentence-transformers/all-MiniLM-L6-v2",
)

SUPPORTED_CHUNK_SIZES: tuple[int, ...] = (512, 1024, 1536, 2048)


def update_runtime_rag_settings(
    chunk_size: int | None = None,
    embedding_model: str | None = None,
) -> dict[str, Any]:
    """Update `backend_config.rag_chunk_size` / `.rag_embedding_model` in
    memory. Returns whether either value changed, so the admin UI can decide
    whether to prompt for a Wipe & Reindex All.

    Persistence: the values are NOT written back to `deployment_backend.json`.
    Matches the contextual-toggle pattern — ephemeral unless the admin edits
    the JSON manually. Keeps this endpoint side-effect-free on disk.
    """
    changed_chunk = False
    changed_embed = False
    if chunk_size is not None:
        if chunk_size not in SUPPORTED_CHUNK_SIZES:
            raise ValueError(
                f"chunk_size {chunk_size} not supported; "
                f"pick one of {SUPPORTED_CHUNK_SIZES}"
            )
        if chunk_size != backend_config.rag_chunk_size:
            backend_config.rag_chunk_size = chunk_size
            changed_chunk = True
    if embedding_model is not None:
        if embedding_model not in SUPPORTED_EMBEDDING_MODELS:
            raise ValueError(
                f"embedding_model {embedding_model!r} not supported; "
                f"pick one of {SUPPORTED_EMBEDDING_MODELS}"
            )
        if embedding_model != backend_config.rag_embedding_model:
            backend_config.rag_embedding_model = embedding_model
            changed_embed = True
    return {
        "chunk_size": backend_config.rag_chunk_size,
        "embedding_model": backend_config.rag_embedding_model,
        "changed": changed_chunk or changed_embed,
        "requires_wipe_and_reindex": changed_chunk or changed_embed,
    }


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


# Sprint 15 follow-up (item H) — BM25 retriever cache keyed by scope.
#
# Before this cache, _hybrid_retrieve rebuilt the BM25 index from scratch on
# EVERY query: fetched all scope nodes from Chroma, tokenised them, built the
# IDF tables. With 45 chunks on the Amcor CBA that was ~6-7 s per query —
# observable in logs as `bm25s:Building index from IDs objects ... 7.15s/it`.
# A meaningful fraction of the Sprint 15 post-fix TTFT.
#
# The cache holds (retriever, chunk_count_when_built) per scope. On each
# query we re-check the current Chroma count for the scope; mismatch means
# chunks were added/removed (reindex, delete) and we rebuild. `_delete_scope`
# and `_build_index` also explicitly invalidate as a belt-and-braces (avoids
# a window where a user's query sees stale retriever results before the
# count-check fires on the next query).
#
# Thread-safety: simple dict reads/writes are GIL-atomic for str keys. Worst
# case under concurrent access: two queries rebuild simultaneously, second
# overwrites first — benign, no corruption.
_bm25_cache: dict[str, tuple[Any, int]] = {}


def _invalidate_bm25_cache(scope_key: str | None = None) -> None:
    """Drop cached BM25 retrievers so the next query rebuilds. Pass a
    scope_key to target one; omit to clear all (useful for startup / tests)."""
    if scope_key is None:
        _bm25_cache.clear()
    else:
        _bm25_cache.pop(scope_key, None)


def _hybrid_retrieve(scope_key: str, idx: Any, query_text: str, fetch_k: int) -> list[Any]:
    """Fuse dense (BGE-M3, scope-filtered) + lexical (BM25 over scope nodes)
    and return ranked NodeWithScore objects. Reciprocal rank fusion combines
    them. Falls back to pure vector retrieval if BM25 isn't available.

    Both retrievers are pinned to the same scope: the vector side via a
    Chroma metadata filter, the BM25 side via the docs we hand to it. The
    BM25Retriever is cached in `_bm25_cache` per scope and invalidated on
    chunk-count change (auto) or on `_delete_scope` / `_build_index` calls
    (explicit).
    """
    vector_retriever = idx.as_retriever(
        similarity_top_k=fetch_k,
        filters=_scope_metadata_filter(scope_key),
    )
    try:
        from llama_index.core.retrievers import QueryFusionRetriever
        from llama_index.retrievers.bm25 import BM25Retriever

        current_count = _scope_chunk_count(scope_key)
        if current_count == 0:
            return vector_retriever.retrieve(query_text)

        cached = _bm25_cache.get(scope_key)
        if cached is not None and cached[1] == current_count:
            bm25_retriever = cached[0]
            # Update top_k in case the caller requested a different fetch_k
            # than the one the retriever was built with — bm25s honours the
            # attribute at retrieval time.
            try:
                bm25_retriever.similarity_top_k = fetch_k
            except Exception:
                pass
        else:
            scope_nodes = _scope_nodes_from_chroma(scope_key)
            if not scope_nodes:
                return vector_retriever.retrieve(query_text)
            bm25_retriever = BM25Retriever.from_defaults(
                nodes=scope_nodes,
                similarity_top_k=fetch_k,
            )
            _bm25_cache[scope_key] = (bm25_retriever, current_count)
            logger.info(
                f"bm25: rebuilt retriever for scope {scope_key} "
                f"({current_count} nodes)"
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
        chunks = [
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
        # Sprint 15 observability: record what the retrieval surfaced so RAG
        # quality regressions are visible in OrbStack without needing to dump
        # session JSONs. One-liner per scope.
        if chunks:
            sizes = [len(c.text) for c in chunks]
            logger.info(
                f"rag.query scope={scope_key} "
                f"q={query_text[:50]!r}... "
                f"fetch_k={fetch_k} rerank_top={final_top_n} "
                f"returned={len(chunks)} "
                f"max_chunk={max(sizes)} chars, mean={sum(sizes) // len(sizes)} chars"
            )
        else:
            logger.info(
                f"rag.query scope={scope_key} "
                f"q={query_text[:50]!r}... returned=0"
            )
        return chunks
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
    if out:
        total_chars = sum(len(c.text) for c in out)
        logger.info(
            f"rag.query_scopes n_scopes={len(scope_keys)} "
            f"total_chunks={len(out)} total_chars={total_chars}"
        )
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
