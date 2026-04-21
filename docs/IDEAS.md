# CBC — Ideas Backlog

Feature ideas captured during development but not yet scoped into a sprint. Each entry shows when it was captured and, when known, a candidate sprint to land it in.

Statuses: `captured` → `triaged` → `planned` (→ Sprint N) → `shipped` / `rejected`.

---

## ChromaDB as vector store (drop SimpleVectorStore when scale demands it)

**Captured:** 2026-04-21 (Sprint 9)
**Status:** **shipped** in Sprint 10C (2026-04-21). Single persistent Chroma collection at `/app/data/chroma/`, `scope_key` as metadata filter — one DB serves global / frontend / company tiers. HNSW + BM25 scope-aware + cross-encoder rerank all ride on top.
**Candidate sprint:** TBD — trigger on one of (100+ empresas con docs / latencia de query > 50 ms / consumo de RAM por multi-scope noticeable)
**Context:** Sprint 9 overhauled the RAG quality (BGE-M3 + rerank + optional Contextual Retrieval). Persistence + framework choice were reviewed in the same breath. LlamaIndex's default `SimpleVectorStore` persists fine on disk, but it's brute-force cosine search and each scope is a separate index file — that's fine for now, becomes a problem as CBC scales to 200+ CBAs across many frontends.

**Idea:** Migrate the vector store layer to **ChromaDB embedded** (no server) via `llama-index-vector-stores-chroma`. Three concrete wins:

1. HNSW indexing → sub-10 ms queries at 100k+ vectors instead of tens of ms with brute-force.
2. Native metadata filtering — let `scope_key` become a filter on one big collection rather than N separate indexes. Simplifies `rag_service._indexes` bookkeeping and cuts RAM use when many scopes are warm.
3. Drop-in replacement in LlamaIndex — swap `VectorStoreIndex(nodes)` for `VectorStoreIndex.from_vector_store(ChromaVectorStore(...))`. ~30 lines in `rag_service.py`.

**Open questions:**
- One collection with `scope_key` metadata, or one collection per frontend? Per-frontend gives natural multi-tenancy for when CBC runs N campaigns; single collection is simpler code.
- Migration from current `SimpleVectorStore` persist dirs — one-shot script that reads each scope's existing index and re-ingests into Chroma.
- Embedding re-compute not needed — we can read BGE-M3 vectors out of the old index and write them into Chroma directly.
- Backup story: Chroma stores SQLite + Parquet under the hood. Already volume-backed, so nothing new, but worth documenting in INSTALL.md.
- Qdrant (separate container, HNSW + better filtering + hybrid native) as the NEXT upgrade when CBC runs 500k+ vectors or multiple backend hosts.

**Prerequisite work:**
- Nothing — Sprint 9's BGE-M3 embeddings + hybrid retrieval already live comfortably in any vector store.
- Decision gate is measurement, not code readiness. Watch query latency + RAM as corpus grows; migrate when `SimpleVectorStore` hurts.

**Rejected alternatives (for context):**
- SQLite-vec: minimalism is its only selling point; gains over `SimpleVectorStore` for CBC are marginal and LlamaIndex integration is less mature.
- Qdrant today: overkill. Add the container dependency only when we genuinely outgrow Chroma embedded.

---

## LLM provider options: Ollama, LM Studio, API

**Captured:** 2026-04-18 (Sprint 3)
**Status:** planned → Sprint 3 (admin UI + config schema) and Sprint 6 (chat engine exercises all three); promoted via `/spec` on 2026-04-18. Spec landed in §4.7 + §5.1 (Tab 1 global + Tab 2 per-frontend override) + §4.9 + §8.3. Code: `llm_config_store.py` already supports all three provider types; `PerFrontendLLMPanel.tsx` exposes the override toggle in Sprint 4B.
**Candidate sprint:** 3 (LLM admin config UI) + 6 (chat engine actually uses it)
**Context:** SPEC §4.7 currently lists "LM Studio, Ollama (OpenAI-compatible API)". Both are local providers on `host.docker.internal`. The admin LLM tab should offer three distinct provider types: Ollama, LM Studio, and "API" (remote cloud providers — Anthropic, OpenAI, etc.) as separate, first-class options.

**Idea:** "la selección de llm incluir opciones ollama, lm studio y api." — admin's LLM configuration dropdown lets the user pick per slot (inference / summariser) between the two local runtimes and a remote cloud API, with whatever credentials / endpoint fields each option needs.

**Open questions:**
- Which cloud providers under "API"? Anthropic only, OpenAI only, both, or a generic "OpenAI-compatible endpoint" that also fits Groq / Together / Mistral?
- Where do API keys live? Env var at container start, admin-panel input (stored encrypted in config), or both?
- Can different slots use different providers (e.g. API for inference, local Ollama for summariser)? HRDD's LLM provider supports per-slot config, so yes in principle.
- Per-frontend LLM override (HRDD pattern) should still work for cloud API slots — confirm.
- Streaming: all three options must keep SSE streaming working end-to-end with the pull-inverse pattern.
- Cost tracking / rate limiting for remote API — in scope for v1.0 or defer?

**Prerequisite work:**
- Sprint 1 backend config already allows LM Studio / Ollama endpoints — schema will need an `api` provider block with `endpoint`, `api_key`, `model` fields
- Sprint 3 is building the LLM admin tab — easiest place to land this
- `llm_provider.py` (adapted from HRDD in Sprint 6) needs a third branch for remote API (auth headers, different error shapes)
- Security: API keys must not be committed or logged — extend secret-redaction pattern

---

## CBA sidepanel in chat — browse & download loaded agreements

**Captured:** 2026-04-18 (Sprint 2)
**Status:** **shipped** across Sprint 11 Phase A (sidepanel + downloads via pull-inverse) and Sprint 11 Phase B (inline `[filename, page/article]` citation pills with click-to-highlight, 2026-04-21). Gated per-frontend by `cba_sidepanel_enabled` + the separate `cba_citations_enabled` flag.
**Candidate sprint:** ~~6 (Chat Engine) or a new sprint between 6 and 8~~ — done in Sprint 11.
**Context:** Company buttons on CompanySelectPage originally showed inline country tags (e.g. `AU · US · DE · BR`). Daniel removed them: cluttered, and the information belongs somewhere more useful.

**Idea:** During chat, a side panel lists the CBAs loaded for the current company (for "Compare All" mode, all loaded CBAs filtered by comparison scope). Each entry shows country, language, document type, and a download button.

**Open questions:**
- Only company-scoped documents, or include frontend + global RAG too (subject to `rag_mode`)?
- Download the original file or a normalized text excerpt?
- Permission model — all users can download, or admin-only?
- Does download count as data egress we need to audit (logging + rate limit)?
- Does this replace, supplement, or sit alongside inline citations in chat responses?

**Prerequisite work already in place:**
- `country_tags` is still in the `Company` type + `companies.json` — Sprint 2 only removed the button display, not the data
- Sprint 5's RAG metadata (country, language, document_type) fits what the panel needs

---

<!-- Append new ideas above this line. Never delete; mark rejected instead. -->
