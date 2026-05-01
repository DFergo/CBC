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
import re
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
# Sprint 16 — second collection on the same client for structured table cards.
# Lives alongside `cbc_chunks` so `client.reset()` on wipe-and-reindex-all
# clears both in one atomic step without extra plumbing.
_tables_collection: Any = None
_chroma_lock = threading.Lock()
CHROMA_DIR = DATA_DIR / "chroma"
CHROMA_COLLECTION_NAME = "cbc_chunks"
TABLES_COLLECTION_NAME = "cbc_tables"

# Per-scope cached LlamaIndex wrappers. Wrapping is cheap, but keeping the
# index objects around avoids reconstructing the StorageContext per query.
_indexes: dict[str, Any] = {}
_indexes_lock = threading.Lock()

# Per-scope locks that serialise _build_index calls for the same scope_key.
# Sprint 16 Fase 0.b — without this, two threads could enter _build_index
# concurrently (e.g. admin Wipe & Reindex in a worker thread + a chat query
# calling get_index() at the same moment). Both would run _delete_scope on
# an empty collection and then both insert their 44 nodes → 88 chunks in
# Chroma. BM25 rebuilt with 88 nodes. Serialising per-scope keeps the
# delete/insert atomic for each builder.
#
# RLock (not Lock) — Sprint 16 task #38 follow-up: `get_index` also needs
# to acquire this lock to avoid a redundant 2× rebuild during wipe. Since
# `get_index` then calls `_build_index` which re-acquires the same lock
# from the same thread, we need reentrant semantics.
_build_locks: dict[str, threading.RLock] = {}
_build_locks_mutex = threading.Lock()


def _get_build_lock(scope_key: str) -> threading.RLock:
    with _build_locks_mutex:
        lock = _build_locks.get(scope_key)
        if lock is None:
            lock = threading.RLock()
            _build_locks[scope_key] = lock
        return lock


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
    # Sprint 18 Fase 3 — clause id ("Art. 23", "Section 13.4.1", "ANEXO I")
    # detected at chunk time by `_segment_by_clause` and propagated through
    # the SentenceSplitter onto every sub-chunk that came out of the same
    # clause body. Empty when the source text had no clause headers (intros
    # / preambles, freeform sections). Citation panel prefers this over the
    # body-regex fallback because it's authoritative.
    clause_id: str = ""


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


def _get_tables_collection() -> Any:
    """Sprint 16 — parallel collection to `cbc_chunks` for structured table
    cards. Each row is one extracted table; its document is the card text
    (`name + description + source_location + columns`) and its metadata holds
    the scope_key + doc_name + table_id so we can load the raw CSV from disk
    at query time.

    Uses the same `_chroma_client` as prose chunks so `client.reset()` in
    `wipe_chroma_and_reindex_all` clears both collections atomically."""
    global _chroma_client, _tables_collection
    if _tables_collection is not None:
        return _tables_collection
    with _chroma_lock:
        if _tables_collection is None:
            # Force the prose collection path to run first — it initialises
            # `_chroma_client` on the same settings. We just piggyback.
            _get_chroma_collection()
            _tables_collection = _chroma_client.get_or_create_collection(
                name=TABLES_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"Chroma collection {TABLES_COLLECTION_NAME!r} ready at {CHROMA_DIR} "
                f"({_tables_collection.count()} table cards total)"
            )
    return _tables_collection


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


# --- Sprint 18 Fase 3 — Clause-aware segmentation -----------------------
#
# CBAs across countries share one structural signal: every substantive rule
# lives under a numbered clause header (Art. 23 ES/IT/AU, Article 23 FR/EN,
# Cláusula 23 ES/AU, Section 13.4.1 AU enterprise agreements, ANEXO I/II ES,
# Annexe I/II FR). The Sprint 15 chunker respects markdown headings but
# slices clause bodies arbitrarily by token count once inside a heading,
# producing chunks like "...complemento por nocturnidad equivale al [CHUNK
# BREAK] resto del párrafo" — half a rule cited at retrieval time.
#
# This pre-pass detects clause headers and uses them as forced chunk
# boundaries: each clause becomes its own pseudo-doc fed to the splitter,
# so Article N never spans two retrieved chunks unless its body alone
# exceeds chunk_size (in which case the sub-chunks all inherit the same
# clause_id metadata for citation propagation).

_CLAUSE_HEADER_RE = re.compile(
    r"(?im)^\s*("
    r"Art\.?\s*\d+(?:\.\d+)*"          # Art. 23, Art 12.4, Art.12.4.1
    r"|Art[íi]culo\s+\d+"               # Artículo 23
    r"|Article\s+\d+"                   # Article 23 (FR formal, EN)
    r"|Articolo\s+\d+"                  # Articolo 23 (IT)
    r"|Cl[áa]usula\s+\d+"               # Cláusula 23
    r"|Clause\s+\d+"                    # Clause 23
    r"|Section\s+\d+(?:\.\d+)*"         # Section 13.4.1 (AU EAs)
    r"|ANEXO\s+[IVX]+"                  # ANEXO I, II, III (ES uppercase)
    r"|Anexo\s+[IVX\d]+"                # Anexo I or Anexo 2 (ES)
    r"|Annexe?\s+(?:[IVX]+|\d+)"        # Annexe I / Annex 2 (FR / EN)
    r")\b[\.\s:\-—–]*",
    re.UNICODE,
)


def _segment_by_clause(text: str) -> list[tuple[str, str]]:
    """Split text into (clause_id, body) tuples. Body extends from one
    clause header (inclusive) up to the next header (exclusive) or EOF.
    Text before the first header is yielded with clause_id="" (intro /
    preamble).

    Returns [("", text)] when the text contains no clause headers (so the
    splitter still gets the full text). Returns [] for empty input.
    """
    if not text or not text.strip():
        return []
    matches = list(_CLAUSE_HEADER_RE.finditer(text))
    if not matches:
        return [("", text)]
    segments: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        intro = text[: matches[0].start()]
        if intro.strip():
            segments.append(("", intro))
    for i, m in enumerate(matches):
        clause_id = re.sub(r"\s+", " ", m.group(1).strip())
        # Normalise "Art." → "Art." (canonical) and similar shorthands so
        # downstream citation hits dedup cleanly.
        if clause_id.lower().startswith("art ") or clause_id.lower().startswith("art."):
            num_match = re.search(r"\d+(?:\.\d+)*", clause_id)
            if num_match:
                clause_id = f"Art. {num_match.group(0)}"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start() : end]
        if body.strip():
            segments.append((clause_id, body))
    return segments


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

    Sprint 18 Fase 3: clause-aware pre-segmentation. Inside each markdown
    heading-section (and inside non-markdown docs), `_segment_by_clause`
    splits by clause header. Each clause becomes its own pseudo-doc fed
    to the SentenceSplitter so Art. N body integrity is preserved (unless
    the clause itself is longer than chunk_size, in which case all sub-
    chunks inherit the same `clause_id` metadata for citation panel use).

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

    def _emit_clause_aware(parent_text: str, parent_meta: dict[str, Any]) -> list[Any]:
        """Run clause segmentation on `parent_text`, then SentenceSplitter
        per segment, propagating `clause_id` to every sub-chunk's metadata."""
        out: list[Any] = []
        for clause_id, segment in _segment_by_clause(parent_text):
            seg_meta = dict(parent_meta) if parent_meta else {}
            if clause_id:
                seg_meta["clause_id"] = clause_id
            wrapper = Document(text=segment, metadata=seg_meta)
            out.extend(sentence_parser.get_nodes_from_documents([wrapper]))
        return out

    nodes: list[Any] = []
    if md_docs:
        md_parser = MarkdownNodeParser()
        md_header_nodes = md_parser.get_nodes_from_documents(md_docs)
        # Second pass: clause-aware pre-segment, then SentenceSplitter caps
        # any clause that's longer than chunk_size. Header metadata flows
        # through unchanged; clause_id is added per segment when detected.
        for hn in md_header_nodes:
            nodes.extend(_emit_clause_aware(hn.text or "", hn.metadata or {}))
    if other_docs:
        # PDF / TXT / DOCX also get clause-aware splits — AU enterprise
        # agreements use Section 13.4.1, FR formal docs use Article N, etc.
        # When no clause headers are detected, _segment_by_clause yields the
        # whole text as a single ("", text) entry → falls through to the
        # SentenceSplitter as before.
        for od in other_docs:
            nodes.extend(_emit_clause_aware(od.text or "", od.metadata or {}))

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


# Persistent single-worker thread pool used to offload the per-chunk async
# LLM call into a separate thread that can safely start its own event loop
# via asyncio.run(). Needed because the original `asyncio.new_event_loop()`
# + `run_until_complete()` approach failed with "Cannot run the event loop
# while another loop is running" when the caller is itself inside an async
# context (the FastAPI admin endpoint that toggles contextual retrieval).
# A single worker keeps chunk processing sequential — concurrent calls to
# the summariser LLM would compete for the same slot at the runtime anyway.
_ctx_executor: "concurrent.futures.ThreadPoolExecutor | None" = None


def _get_ctx_executor() -> "concurrent.futures.ThreadPoolExecutor":
    global _ctx_executor
    import concurrent.futures
    if _ctx_executor is None:
        _ctx_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ctxret",
        )
    return _ctx_executor


def _generate_chunk_context(document_text: str, chunk_text: str) -> str:
    """Synchronously get a context line for one chunk from whichever slot the
    admin has routed CR to (default: compressor — small fast slot, e.g.
    qwen3.5-9b on Ollama). Sprint 15 phase 5 made this configurable via
    `LLMConfig.routing.contextual_retrieval_slot` so a 100-CBA reindex drops
    from ~35h on the summariser (qwen3.5-122b) to ~3-4h on the compressor.

    Errors are swallowed — we return "" so the chunk still indexes without
    enrichment rather than blocking the whole reindex on a transient LLM hiccup.

    Runs the async `llm_provider.chat()` call inside a dedicated worker thread
    with its own event loop (via `asyncio.run()`). Works whether the caller is
    on the FastAPI main loop (admin reindex) or a pure sync background (file
    watcher), which the previous `asyncio.new_event_loop()` path did not.
    """
    import asyncio

    from src.services import llm_provider
    from src.services.llm_config_store import load_config

    doc_excerpt = (document_text or "")[: backend_config.rag_contextual_max_doc_chars]
    prompt = _CONTEXT_PROMPT.format(document=doc_excerpt, chunk=chunk_text)
    messages = [{"role": "user", "content": prompt}]

    # Read the routing toggle on every call so an admin flip takes effect
    # without a restart. Cheap — the config read is a file + JSON parse, and
    # it's dwarfed by the LLM call itself.
    try:
        cr_slot = load_config().routing.contextual_retrieval_slot
    except Exception:
        cr_slot = "compressor"  # safe fallback if LLMConfig read fails

    def _call() -> str:
        # asyncio.run() creates a fresh event loop in THIS thread. Since the
        # executor runs us in a separate thread from the FastAPI main loop,
        # there is no running-loop conflict.
        return asyncio.run(
            llm_provider.chat(messages, slot=cr_slot, frontend_id=None)
        )

    try:
        return _get_ctx_executor().submit(_call).result()
    except Exception as e:
        logger.warning(f"Contextual enrichment failed for one chunk: {e}")
        return ""


def _contextualise_nodes(nodes: list[Any], documents: list[Any]) -> int:
    """Mutate `nodes` in place — prepend an LLM-generated context line to each
    node's text. Returns the count of chunks that actually got enriched so
    the caller can detect total-failure scenarios (e.g. the asyncio bug that
    hit every chunk in Sprint 15 phase 4).

    Cost: one LLM call per chunk. With ~25 chunks per doc and a local summariser
    at 10-30 s per call, expect 5-15 minutes per document. Surface progress in
    the log so admins see it isn't stuck.
    """
    if not nodes:
        return 0
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
    return enriched


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
    wrapper (or None if there are no docs).

    Serialised per-scope via `_get_build_lock(scope_key)` — see the lock
    declaration above for the concurrent-duplicate bug this prevents."""
    from llama_index.core import SimpleDirectoryReader

    with _get_build_lock(scope_key):
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
                enriched = _contextualise_nodes(nodes, documents)
                # Safety net: if CR is on but literally every chunk's LLM call
                # failed, the reindex would silently produce a plain (non-CR)
                # index while the admin thinks they turned enrichment on. Raise
                # here so the endpoint surfaces the problem and can roll back.
                if nodes and enriched == 0:
                    raise RuntimeError(
                        f"Contextual enrichment produced 0 enriched chunks out of "
                        f"{len(nodes)} for scope {scope_key}. Check summariser slot "
                        f"health + backend logs for per-chunk errors."
                    )

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

            # Sprint 16 — structured table extraction. Every file is also fed
            # to the table extractor; any detected tables are persisted as CSV
            # + manifest on disk and embedded as card entries in the separate
            # `cbc_tables` Chroma collection (via _embed_tables_for_scope).
            # Independent of prose chunking — a doc can contribute to both
            # collections or just to prose.
            try:
                _extract_and_embed_tables(scope_key, files)
            except Exception as e:
                # Don't fail the whole reindex if table extraction breaks —
                # prose retrieval is the primary RAG path. Log and continue.
                logger.warning(f"table extraction for scope {scope_key} failed: {e}")

            return wrapper
        except Exception as e:
            logger.error(f"Failed to build index for scope {scope_key}: {e}")
            return None


def _delete_scope(scope_key: str) -> None:
    """Remove every chunk tagged with this scope_key from both Chroma
    collections (prose + tables). On-disk CSVs are left in place — they get
    overwritten by the next `_extract_and_embed_tables` for this scope, or
    explicitly purged by `wipe_chroma_and_reindex_all`."""
    try:
        collection = _get_chroma_collection()
        collection.delete(where={"scope_key": scope_key})
    except Exception as e:
        logger.warning(f"Could not delete chunks for scope {scope_key}: {e}")
    try:
        tcol = _get_tables_collection()
        tcol.delete(where={"scope_key": scope_key})
    except Exception as e:
        logger.warning(f"Could not delete table cards for scope {scope_key}: {e}")
    # Drop the cached BM25 retriever for this scope so the next query rebuilds
    # fresh. Sprint 15 H — prevents stale retrievers after a reindex.
    _invalidate_bm25_cache(scope_key)


def _purge_all_tables_on_disk() -> None:
    """Remove every `tables/` dir under /app/data/ and /app/data/campaigns.
    Called from `wipe_chroma_and_reindex_all` to match the Chroma reset —
    the next reindex re-extracts tables from source documents, so anything
    lingering from before is either redundant or stale."""
    from src.services import table_extractor
    scopes_seen: set[str] = set()
    # global
    scopes_seen.add("global")
    # frontend + company tiers
    for sk in _discover_all_scope_keys():
        scopes_seen.add(sk)
    for sk in scopes_seen:
        table_extractor.delete_scope_tables(sk)


def _extract_and_embed_tables(scope_key: str, files: list[Path]) -> int:
    """Sprint 16 — extract structured tables from each file and embed a
    metadata card per table into `cbc_tables`. CSVs are persisted on disk so
    we don't round-trip through Chroma for the verbatim table content
    (Chroma's metadata has a size limit, and multi-KB CSVs don't belong in
    a vector store anyway).

    Re-running for the same scope is idempotent: the prior `_delete_scope`
    already purged this scope's table cards from Chroma, and
    `table_extractor.save_tables_for_doc` wipes the per-doc dir before
    rewriting. This function also cleans up orphan dirs (tables/{stem}
    whose source doc no longer exists in the scope) so file-watcher
    deletions don't leave stale CSVs behind.

    Returns the total number of embedded cards for observability."""
    from src.services import table_extractor

    embed_model = _get_embed_model()
    tcol = _get_tables_collection()

    # Orphan cleanup: list existing table dirs for this scope and remove any
    # whose doc_stem doesn't match a current file. The watcher path doesn't
    # know which specific doc was deleted — it just re-runs reindex for the
    # scope — so doing the reconciliation here keeps the on-disk state in
    # sync regardless of the change type.
    scope_tables_root = table_extractor.tables_root_for(scope_key)
    if scope_tables_root.exists():
        current_stems = {Path(f.name).stem for f in files}
        # Normalise current stems through the same sanitiser that
        # save_tables_for_doc uses, so orphan detection matches on-disk names.
        current_stems_sanitised = {table_extractor._sanitise(s) for s in current_stems}
        for sub in scope_tables_root.iterdir():
            if not sub.is_dir():
                continue
            if sub.name not in current_stems_sanitised:
                import shutil
                try:
                    shutil.rmtree(sub)
                    logger.info(f"tables: removed orphan dir {sub}")
                except OSError as e:
                    logger.warning(f"tables: could not remove orphan {sub}: {e}")

    total_cards = 0
    for f in files:
        tables = table_extractor.extract_tables_for_file(f)
        if not tables:
            continue
        table_extractor.save_tables_for_doc(scope_key, f.name, tables)

        card_texts = [t.as_card_text() for t in tables]
        # Batch-embed to amortise the forward-pass cost.
        try:
            vectors = embed_model.get_text_embedding_batch(card_texts)
        except Exception:
            # Fallback one-by-one if the embedder doesn't support batch.
            vectors = [embed_model.get_text_embedding(ct) for ct in card_texts]

        ids = [f"{scope_key}::{f.name}::{t.id}" for t in tables]
        metadatas = [
            {
                "scope_key": scope_key,
                "tier": _tier_for(scope_key),
                "doc_name": f.name,
                "table_id": t.id,
                "table_name": t.name,
                "source_location": t.source_location,
                "row_count": t.row_count,
            }
            for t in tables
        ]
        tcol.upsert(
            ids=ids,
            documents=card_texts,
            embeddings=vectors,
            metadatas=metadatas,
        )
        total_cards += len(tables)

    if total_cards:
        logger.info(f"tables: scope={scope_key} embedded {total_cards} cards across {len(files)} files")
    return total_cards


def query_tables(scope_keys: list[str], query_text: str, top_k: int = 2) -> list[dict[str, Any]]:
    """Retrieve the top-K table cards matching `query_text` across the given
    scopes, then load each hit's raw CSV from disk. Returned dicts carry
    everything the prompt assembler needs to render a `## Relevant tables`
    section: name, description, source_location, csv_text, doc_name,
    table_id, scope_key.

    Returns `[]` on any error so a broken table path never breaks the main
    chat flow."""
    from src.services import table_extractor

    if not scope_keys or not query_text:
        return []

    try:
        tcol = _get_tables_collection()
        if tcol.count() == 0:
            return []
        embed_model = _get_embed_model()
        qvec = embed_model.get_text_embedding(query_text)
        # Chroma's `where` accepts `{"scope_key": {"$in": [...]}}` for multi
        # scope filtering. Single scope also works as {"scope_key": value}
        # but $in is uniform.
        where = {"scope_key": {"$in": list(scope_keys)}}
        result = tcol.query(
            query_embeddings=[qvec],
            n_results=top_k,
            where=where,
        )
    except Exception as e:
        logger.warning(f"query_tables failed: {e}")
        return []

    # Chroma returns list-of-lists because we can query multiple vectors at
    # once; we only ever pass one, so index [0].
    ids = (result.get("ids") or [[]])[0]
    mds = (result.get("metadatas") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    dists = (result.get("distances") or [[]])[0] if result.get("distances") else [None] * len(ids)

    out: list[dict[str, Any]] = []
    for hit_id, md, card_text, dist in zip(ids, mds, docs, dists):
        md = md or {}
        scope_key = md.get("scope_key", "")
        doc_name = md.get("doc_name", "")
        table_id = md.get("table_id", "")
        csv_text = table_extractor.load_csv(scope_key, doc_name, table_id) or ""
        out.append({
            "scope_key": scope_key,
            "doc_name": doc_name,
            "table_id": table_id,
            "name": md.get("table_name", ""),
            "source_location": md.get("source_location", ""),
            "row_count": md.get("row_count", 0),
            "card_text": card_text or "",
            "csv_text": csv_text,
            "distance": dist,
        })
    if out:
        logger.info(
            f"tables.query scopes={scope_keys} q={query_text[:60]!r}... "
            f"top_k={top_k} returned={len(out)}"
        )
    return out


def get_index(scope_key: str) -> Any | None:
    """Return the LlamaIndex wrapper for a scope (cache → build-if-empty).

    With Chroma the storage is the collection itself — the wrapper is just a
    LlamaIndex façade. We cache the wrapper to skip StorageContext rebuilds
    on hot paths but it's safe to discard at any time.

    Sprint 16 #38 — when wipe_chroma_and_reindex_all is mid-flight for this
    scope, an incoming chat query used to fire a redundant `_build_index`
    (both threads saw 0 chunks before the admin thread had inserted its
    batch). We now acquire the scope's build_lock before deciding whether
    to build: if the admin thread is inside, we wait, and once it exits
    `_scope_chunk_count` returns the fresh count and we just wrap (no
    rebuild). RLock lets the same thread re-acquire in `_build_index`
    when a real rebuild is needed.
    """
    with _indexes_lock:
        if scope_key in _indexes:
            return _indexes[scope_key]

    build_lock = _get_build_lock(scope_key)
    with build_lock:
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

    Sprint 16 followup: also feed the filenames to `derive_country_tags` so
    docs without explicit country metadata still contribute a tag via the
    filename auto-detector (e.g. "CBA—Amcor—Lezo—Spain.md" → ES).
    """
    if "/" not in scope_key:
        return
    fid, slug = scope_key.split("/", 1)
    try:
        from src.services import company_registry, document_metadata
        docs_dir = _docs_dir_for(scope_key)
        filenames = [p.name for p in _list_indexable_files(docs_dir)] if docs_dir.exists() else []
        tags = document_metadata.derive_country_tags(scope_key, filenames=filenames)
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
    global _chroma_client, _chroma_collection, _tables_collection, _embed_model, _reranker
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
        _tables_collection = None  # Sprint 16 — drop the cached handle too
        if not reset_ok and CHROMA_DIR.exists():
            try:
                shutil.rmtree(CHROMA_DIR, ignore_errors=False)
                logger.info(f"Fallback rmtree of {CHROMA_DIR} succeeded")
            except OSError as e:
                logger.error(f"Could not remove chroma dir {CHROMA_DIR}: {e}")
                raise

    # 2b. Sprint 16 — also purge the on-disk CSV + manifest tree so stale
    # tables from a previous extractor version / doc set don't linger. The
    # next `_extract_and_embed_tables` call during reindex rebuilds them
    # from source.
    _purge_all_tables_on_disk()

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
    memory AND persist to `runtime_overrides.json` so they survive container
    restarts (Sprint 15 phase 4).

    Returns whether either value changed so the admin UI can decide whether
    to prompt for a Wipe & Reindex All.
    """
    from src.services import runtime_overrides_store

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

    # Persist both changed fields in one write so the next backend restart
    # picks them up instead of reverting to deployment_backend.json defaults.
    persist_payload: dict[str, Any] = {}
    if changed_chunk:
        persist_payload["rag_chunk_size"] = backend_config.rag_chunk_size
    if changed_embed:
        persist_payload["rag_embedding_model"] = backend_config.rag_embedding_model
    if persist_payload:
        runtime_overrides_store.save_overrides(**persist_payload)

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

    Sprint 18 — fetch_k is now `max(rag_reranker_fetch_k, top_k * 3)`.
    Without the *3 multiplier, when `top_k` is bumped (dynamic top-K
    based on corpus size), `fetch_k` could equal `top_k` → reranker
    becomes a no-op because every fetched chunk is already in the
    final set. *3 gives the cross-encoder real candidates to choose
    among at every K.
    """
    idx = get_index(scope_key)
    if idx is None or _scope_chunk_count(scope_key) == 0:
        return []
    try:
        final_top_n = top_k or backend_config.rag_reranker_top_n
        fetch_k = max(
            backend_config.rag_reranker_fetch_k,
            final_top_n * 3,
        )
        nodes = _hybrid_retrieve(scope_key, idx, query_text, fetch_k)
        nodes = _rerank(nodes, query_text, final_top_n)
        chunks = [
            Chunk(
                text=n.node.text,
                score=getattr(n, "score", 0.0) or 0.0,
                source=n.node.metadata.get("file_name", "(unknown)"),
                tier=n.node.metadata.get("tier", _tier_for(scope_key)),
                scope_key=scope_key,
                page_label=str(n.node.metadata.get("page_label") or ""),
                clause_id=str(n.node.metadata.get("clause_id") or ""),
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


# --- Sprint 18 — Dynamic top-K -------------------------------------------
#
# The static `RAG_TOP_K_PER_SCOPE = 5` constant in prompt_assembler couldn't
# scale: with 1 doc loaded it was fine, with 23 docs it left ~80% of the
# corpus invisible to the LLM ("compara vacaciones" → 4 of 23 docs cited;
# "list FR convenios" → 4 of 15 enumerated). The fix scales K linearly with
# the number of source files in the active scopes, capped on both ends so
# small corpora don't pay rerank cost they don't need and huge corpora
# don't blow the prompt budget.
#
# Numbers picked from observed corpora:
#   1 doc   →  K=5    (status quo)
#   5 docs  →  K=10   (~2 chunks/doc on average)
#   23 docs →  K=40   (cap)
#   50 docs →  K=40   (capped — at this scale query rewriting from
#                      Sprint 18 phase 3 is the right next move)
#
# Reranker cost scales with fetch_k = top_k * 3 (see `query`), so K=40
# means the cross-encoder scores ~120 candidates per scope. On the bge-
# reranker-v2-m3 with batch size 32, that's ~4 batches ≈ 1-2 s extra
# latency vs K=5.

_DYNAMIC_TOP_K_FLOOR = 5
_DYNAMIC_TOP_K_CEIL = 40
_DYNAMIC_TOP_K_PER_DOC = 2


def compute_dynamic_top_k(scope_keys: list[str]) -> int:
    """Return a top_k_per_scope appropriate for the size of the active scopes.

    Used by `prompt_assembler._resolve_rag` so single-doc sessions stay cheap
    and big-corpus sessions get enough recall to actually cover the docs the
    user expects to see cited.

    Counts files via `_list_indexable_files` per scope and sums them; this
    matches what `_build_index` indexes. Empty scopes contribute zero so
    they don't inflate K artificially.
    """
    total_files = 0
    for sk in scope_keys:
        try:
            docs_dir = _docs_dir_for(sk)
        except ValueError:
            continue
        if not docs_dir.exists():
            continue
        try:
            total_files += len(_list_indexable_files(docs_dir))
        except OSError:
            continue
    return min(max(_DYNAMIC_TOP_K_FLOOR, total_files * _DYNAMIC_TOP_K_PER_DOC), _DYNAMIC_TOP_K_CEIL)


def compute_dynamic_tables_top_k(scope_keys: list[str], is_compare_all: bool) -> int:
    """Tables top-K. Lower base than prose because each table card is dense
    metadata + a CSV — fewer cards needed for the same retrieval coverage.
    Compare All doubles the cap because each company contributes its own
    tables and we want at least one per company to land in the prompt.
    """
    base = compute_dynamic_top_k(scope_keys) // 4
    floor = 2
    ceil = 12 if is_compare_all else 6
    return min(max(floor, base), ceil)


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
