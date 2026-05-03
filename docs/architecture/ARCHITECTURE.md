# CBC — Living Architecture

**Audience:** dual-use — Claude reads this at every sprint start to skip rediscovering the system from source code; Daniel reads this as an operator manual to find which admin toggle controls what without opening VS Code.

**Authoritative scope:** the post-Sprint-16 state. When something here doesn't match the running system, the running system is right and this doc is stale — open a PR fixing the doc as part of the next sprint (the `/sprint` skill includes that step in Finalizing).

**Conventions:**
- Every behaviour an admin can change cites the exact UI path: `Admin → Tab → Section → control name`.
- Every backend behaviour cites the file path: `CBCopilot/src/backend/services/{name}.py`.
- Every persisted state cites the disk path: `/app/data/...`.

---

## §1 System overview

CBC (Collective Bargaining Copilot) is a UNI Global Union — Graphical & Packaging tool that lets trade-union representatives query a corpus of collective bargaining agreements (CBAs), company policies, and reference knowledge to support negotiations. Pull-inverse architecture inherited from HRDD Helper: the backend polls each frontend's sidecar instead of frontends pushing into the backend, so frontends can sit behind firewalls or NATs without inbound connectivity.

The unit of configuration is a three-tier hierarchy: **Global → Frontend → Company**. Each tier can override prompts, RAG documents, organizations, LLM slots, branding, session settings. The prompt assembler resolves these at every turn following a "company override → frontend override → global default" lookup chain. RAG retrieval can union the tiers (configurable via the per-tier "Combine RAG" toggles).

Inside the backend, RAG is hybrid: a single ChromaDB persistent collection (`cbc_chunks`) holds vector + BM25 indices for prose chunks across every scope, with a metadata filter `scope_key` selecting which scope a query reads. A second collection (`cbc_tables`, Sprint 16) holds card-style entries for structured tables extracted from documents at ingest. A cross-encoder reranker (`bge-reranker-v2-m3`) tightens the top-K. The LLM provider is OpenAI-compatible streaming with three slots (inference / compressor / summariser), each independently routable to Ollama, LM Studio, or any compatible endpoint.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          BROWSERS (users)                                │
└────────────────┬───────────────────────────────────┬─────────────────────┘
                 │                                   │
                 ▼                                   ▼
        ┌────────────────┐                  ┌────────────────┐
        │  Frontend A    │                  │  Frontend B    │
        │  (Vite SPA +   │                  │  (Vite SPA +   │
        │  sidecar queue)│                  │  sidecar queue)│
        └────────┬───────┘                  └────────┬───────┘
                 │                                   │
                 │   GET /internal/queue   (poll)    │
                 │   POST /internal/stream/{token}/chunk (push)
                 │                                   │
                 ▼                                   ▼
        ┌──────────────────────────────────────────────────┐
        │                 CBC Backend                      │
        │   FastAPI + asyncio                              │
        │                                                  │
        │   polling.py ── prompt_assembler.py              │
        │       │              │                           │
        │       │              ├─→ rag_service ── Chroma   │
        │       │              ├─→ session_rag             │
        │       │              ├─→ knowledge_store         │
        │       │              └─→ orgs_override_store     │
        │       │                                          │
        │       └─→ llm_provider ── Ollama / LM Studio     │
        │                                                  │
        │   rag_watcher (file events → debounced reindex)  │
        │   session_lifecycle (idle scan, every 300 s)     │
        │   admin/* routers (FastAPI sub-apps)             │
        │                                                  │
        └────────┬─────────────────────────────────────────┘
                 │
                 ▼
        ┌────────────────────────────────────────────────┐
        │         /app/data/  (the source of truth)      │
        │  prompts · documents · chroma · campaigns/     │
        │  sessions · knowledge · *_config.json · ...    │
        └────────────────────────────────────────────────┘
```

External dependencies (Ollama / LM Studio / Hugging Face for the cached embedder + reranker) live outside the container; nothing else is networked. There is no database — every piece of state is a JSON file on disk under `/app/data/` (atomic-write pattern), or a directory of binary indices under `/app/data/chroma/`.

---

## §2 Services layer

Every file under `CBCopilot/src/backend/services/`. One entry each: responsibility, state, callers.

### `branding_defaults_store.py`
Manages global branding defaults (app_title, org_name, logo_url, primary_color, secondary_color, disclaimer_text, instructions_text). State: none. Read by polling loop's branding push and by frontend sidecars at first session.
**UI:** `Admin → General → Branding`.

### `branding_store.py`
Per-frontend branding overrides. State: none. Read by polling loop's push.
**UI:** `Admin → Frontends → {frontend} → Branding panel`.

### `branding_translator.py`
Calls the summariser LLM to autotranslate disclaimer / instructions across the 15 supported UI languages. State: none. Triggered by an admin button.
**UI:** `Admin → General → Branding → Auto-translate` (also available per-frontend).

### `company_registry.py`
Reads / writes `campaigns/{frontend_id}/companies.json`; resolves slug → display name + per-company combine flags. State: per-frontend cache.
**UI:** `Admin → Frontends → {frontend} → Companies panel`. Edits cascade into `Admin → Frontends → {frontend} → Company → {company} → ...` per-tier blocks.

### `contacts_store.py`
Allowlist of authorised end-user emails when `auth_required` is on. Backed by `/app/data/knowledge/contacts.json` (NOT `smtp_config.json`'s admin recipients).
**UI:** `Admin → Registered Users` tab.

### `context_compressor.py`
Sliding-window compressor that summarises older turns once the assembled prompt exceeds `compression.first_threshold` (default 20000 chars), then steps every `compression.step_size` (15000) chars beyond that. Uses the `compressor` LLM slot.
**UI:** `Admin → General → LLM → Context compression` (toggle + thresholds).

### `document_metadata.py`
Per-directory `metadata.json` mapping `filename → {country, language, document_type}`. Country values feed `Company.country_tags`, which Compare All filters by. Sprint 16 follow-up: `derive_country_tags(scope_key, filenames)` also auto-detects country from filename via a ~80-entry name-to-ISO-2 map (covers UNI G&P jurisdictions in EN + ES + native names) for docs the admin hasn't tagged manually.
**UI:** `Admin → Frontends → {frontend} → Company → {company} → RAG documents → metadata edit per file` (country / language / document_type).

### `frontend_registry.py`
Tracks frontends registered with the backend: `{frontend_id, name, url, status, last_seen, enabled}`. Active frontends advertise via `/internal/health`; offline ones are still listed but skipped by the polling loop.
**UI:** `Admin → Frontends` tab (add / edit / disable).

### `guardrails.py`
Pre-LLM content filter. Two regex categories: hate / violence / discrimination, and prompt-injection patterns. Triggers a per-session counter; warn at `guardrail_warn_at` (2), terminate at `guardrail_max_triggers` (5). State: compiled regex tables loaded at import time.
**UI:** `Admin → General → Guardrails` (info card; thresholds are code constants for now, not editable).

### `knowledge_store.py`
Reads / writes `/app/data/knowledge/{glossary,organizations}.json`. Glossary is term → definition; organizations is a list of dicts (name, type, country, description).
**UI:** `Admin → General → Glossary` and `Admin → General → Organizations`. Plus per-frontend organization overrides at `Admin → Frontends → {frontend} → Per-frontend orgs`.

### `llm_config_store.py`
Persists three slots (inference / compressor / summariser) with provider + model + temperature + max_tokens; plus `compression`, `routing`, `disable_thinking`, `max_concurrent_turns`. Provider probing is cached.
**UI:** `Admin → General → LLM`.

### `llm_override_store.py`
Per-frontend slot overrides on top of the global `llm_config.json`.
**UI:** `Admin → Frontends → {frontend} → Per-frontend LLM panel`.

### `llm_provider.py`
OpenAI-compatible streaming. Per-slot httpx client, circuit-breaker on `_fail_state` (3 failures in 60 s → 300 s cooldown), `INACTIVITY_TIMEOUT = 60 s` per chunk, `STREAM_TIMEOUT = 300 s` per request. Strips `<think>` blocks when `disable_thinking=True`. Builds the body with `think: false` for Ollama. Diagnostic log line on every request.

### `orgs_override_store.py`
Per-frontend organizations list overrides on top of the global organizations JSON.
**UI:** `Admin → Frontends → {frontend} → Per-frontend orgs panel`.

### `polling.py`
The backbone. Two background tasks scheduled at lifespan:
- `polling_loop` (interval 2 s): per-frontend tick — health check, push state if the frontend just (re)connected, drain `/internal/queue` for queued user turns, spawn per-turn coroutines into `_turn_semaphore` (sized from `max_concurrent_turns`, default 4).
- `cancel_watcher_loop` (interval 1 s): drains `/internal/cancellations` from every frontend, populates a module-level `_pending_cancellations: set[str]` that streaming turns sample mid-flight to break early on user Stop.

State: `_pending_cancellations`, `_turn_semaphore`, `_thresholds_pushed` and `_companies_pushed` (per-frontend "have we pushed branding / companies since the frontend came up?" sets).

### `prompt_assembler.py`
Builds the system prompt for one turn. Resolves the three tiers, fills the context template with the survey answers, retrieves prose chunks (`rag_service.query_scopes`) and table cards (`rag_service.query_tables`, Sprint 16), assembles the layers in order: core / guardrails / role / context / glossary / organizations / RAG chunks / Tables. Emits a structured `AssembledPrompt(text, layers, rag_chunks_used, rag_paths, sources)`. The `sources` list is what the frontend's CitationsPanel renders.

### `prompt_store.py`
CRUD for the four prompt files (`core.md`, `guardrails.md`, `cba_advisor.md`, `compare_all.md`, `context_template.md`) at the three tiers.
**UI:** `Admin → General → Prompts` (global), plus `Admin → Frontends → {frontend} → Prompts` and `Admin → Frontends → {frontend} → Company → {company} → Prompts`.

### `rag_service.py`
The big one. Owns:
- The shared Chroma `PersistentClient` + two collections: `cbc_chunks` (prose) and `cbc_tables` (Sprint 16 table cards).
- The lazy-loaded BGE-M3 embedder (`_embed_model`) and bge-reranker-v2-m3 reranker (`_reranker`).
- Per-scope `_indexes` cache of LlamaIndex wrappers.
- `_bm25_cache` per scope (Sprint 15 H — avoid rebuilding the BM25 retriever every query).
- Per-scope `_build_locks: dict[str, threading.RLock]` (Sprint 16 Fase 0.b + #38) — serialises `_build_index` and `get_index` to prevent duplicate ingest under concurrency.

Public entry points: `query_scopes(scope_keys, query, top_k_per_scope)`, `query_tables(scope_keys, query, top_k)`, `reindex(scope_key)`, `reindex_all_scopes()`, `reindex_frontend_cascade(fid)`, `wipe_chroma_and_reindex_all()`, `update_runtime_rag_settings(chunk_size, embedding_model)`, `update_runtime_rag_tuning(**fields)` (Sprint 18 Fase 4 — knobs editables), `compute_dynamic_top_k(scope_keys)` and `compute_dynamic_tables_top_k(scope_keys, is_compare_all)` (Sprint 18 Fase 1 — top-K scales with `num_files_in_scope`). Sprint 9 hybrid pipeline: BM25 + vector → fuse → cross-encoder rerank → top-N. Sprint 15 chunker fix pipes markdown header nodes through `SentenceSplitter` so big sections don't blow past BGE-M3's 8192-token window. Sprint 18 Fase 3 added `_segment_by_clause(text)`: regex-based pre-pass over markdown / pdf / txt that detects `Art. N` / `Article N` / `Cláusula N` / `Section N.N.N` / `ANEXO I` / `Annexe N` headers and feeds each clause as its own pseudo-doc to the SentenceSplitter — clause integrity preserved unless the clause body alone exceeds `chunk_size` (in which case all sub-chunks inherit the same `clause_id` metadata used by the citation panel).

### `rag_settings_store.py`
Per-frontend `rag_settings.json` — currently a single toggle `combine_global_rag`.
**UI:** `Admin → Frontends → {frontend} → RAG documents → Combine global RAG` checkbox.

### `rag_store.py`
Disk-backed CRUD for `documents/` directories at the three tiers. List, save, delete, stats. Re-emits a structured `RAGStats` per scope.
**UI:** `Admin → General → RAG documents` (global), `Admin → Frontends → {frontend} → RAG documents`, `Admin → Frontends → {frontend} → Company → {company} → RAG documents`.

### `rag_watcher.py`
watchdog-based file watcher rooted at `/app/data/`. On any `created/modified/deleted/moved` event inside a known `documents/` folder, schedules a debounced callback that fires `rag_service.reindex(scope_key)` for the affected scope. Filters out `.icloud`, `.DS_Store`, `._*` artefacts (lessons-learned #1).

Sprint 18 Fase 2/4 made the timing knobs admin-editable + dynamic. Three helpers (`_debounce_seconds()`, `_max_hold_seconds()`, `_lock_busy_replan_seconds()`) read from `backend_config` on every call so a tuning change applies on the next watcher tick without restart. `_ScopeDebouncer` now also tracks `_first_event_at[scope]` and forces the fire after `MAX_DEBOUNCE_HOLD_SECONDS` (default 300) so a non-stop slow upload can't park reindex forever. Before firing, it probes `rag_service._build_locks[scope].acquire(blocking=False)`; if the build lock is held by an in-flight reindex, it defers `LOCK_BUSY_REPLAN_SECONDS` (default 30) instead of competing for the lock.

**UI:** none directly — file watcher behaviour is implicit; reflects in the docs list refresh on the affected RAG section. Tuning knobs at `Admin → General → RAG Pipeline → Tuning avanzado`.

### `runtime_overrides_store.py`
Persists admin-editable backend_config fields to `/app/data/runtime_overrides.json`. Loaded by `apply_startup_overrides()` from the FastAPI lifespan BEFORE any service reads `backend_config`. Sprint 15 phase 4 introduced the pattern; Sprint 18 Fase 4 extended `_TRACKED_FIELDS` to cover the 9 retrieval / watcher tuning knobs (`rag_top_k_floor`, `rag_top_k_ceil`, `rag_top_k_per_doc`, `rag_tables_top_k_floor`, `rag_tables_top_k_ceil_single`, `rag_tables_top_k_ceil_compare_all`, `rag_watcher_debounce_seconds`, `rag_watcher_max_hold_seconds`, `rag_watcher_lock_replan_seconds`) plus the original three (`rag_chunk_size`, `rag_embedding_model`, `rag_contextual_enabled`).

### `session_lifecycle.py`
Background scanner (interval 300 s). Per-frontend session settings drive auto-close (move from `active` → `closed` after `auto_close_hours`) and auto-destroy (privacy wipe — delete the session dir + uploads + indices after `auto_destroy_hours`).
**UI:** `Admin → Frontends → {frontend} → Session settings → Auto-close hours / Auto-destroy hours`.

### `session_rag.py`
Per-session RAG resolution: figures out which scopes feed this session (its frontend's, its company's, plus optional combines) and queries `rag_service` accordingly. Also handles session-attached RAG (user-uploaded docs in `sessions/{token}/uploads/`) — chunked at upload time, queried alongside the scope chunks.

### `session_settings_store.py`
Per-frontend session feature toggles: `auth_required`, `auto_close_hours`, `auto_destroy_hours`, `session_resume_hours`, `disclaimer_enabled`, `instructions_enabled`, `compare_all_enabled`, `cba_sidepanel_enabled`, `cba_citations_enabled`.
**UI:** `Admin → Frontends → {frontend} → Session settings`.

### `session_store.py`
The session JSON store. One directory per token: `metadata.json`, `conversation.jsonl`, `system_prompt.md`, `uploads/`. Atomic writes (tmpfile + rename). In-memory cache + per-token `threading.Lock`.

### `smtp_service.py`
SMTP config + send. Triggered on session close to email a user-summary (toggleable) and an admin-summary (toggleable).
**UI:** `Admin → General → SMTP`.

### `table_extractor.py`
Sprint 16. Extracts pipe-tables from `.md` (regex + heading-chain) and tables from vector `.pdf` (pdfplumber). Persists each table as `{scope_root}/tables/{doc_stem}/{table_id}.csv` + `manifest.json`. Card text (`name + description + source_location + columns + row_count`) is what `rag_service` embeds into `cbc_tables`. `extract_markdown_tables` post-processes names to disambiguate when multiple tables share a heading chain (Sprint 16 task #36).

---

## §3 Data flows

### Chat turn

```
User types → React App (ChatShell.tsx)
           → POST /internal/turn  (sidecar)
           → sidecar enqueues {token, message}
       (≤2 s)
Backend polling_loop tick
  → GET /internal/queue                       (per frontend)
  → for each queued message: spawn _process_turn coroutine
       (limited by _turn_semaphore = max_concurrent_turns)
  → _process_turn:
       guardrails.scan_user_input → maybe abort
       prompt_assembler.assemble → AssembledPrompt
       llm_provider.stream_chat (slot=inference)
         → Ollama / LM Studio
         → token chunks streamed back
       per chunk: POST /internal/stream/{token}/chunk
       on done: POST /internal/stream/{token}/chunk {type: "done", sources, ...}
  → frontend SSE → ChatShell renders
```

User Stop button → sidecar `/internal/cancel/{token}` → `cancel_watcher_loop` picks it up within 1 s → `_pending_cancellations` set adds the token → in-flight `_process_turn` checks the set every chunk and breaks early, emits `cancelled` terminal event.

### RAG query (prose)

```
prompt_assembler._resolve_rag(frontend, company, ...)
  → resolvers.resolve_rag_paths    # which scopes this turn reads
  → rag_service.query_scopes(scope_keys, query, top_k_per_scope)
       → for each scope_key:
            embed query (BGE-M3)
            Chroma query on cbc_chunks WHERE scope_key=X, top fetch_k=30
            BM25 retriever (cached) WHERE scope_key=X, top fetch_k=30
            fuse vector + BM25 rankings
            cross-encoder rerank to top_n (default 8)
       → return list[Chunk]
```

Chunks land in the `## Retrieved CBA / policy excerpts` section of the prompt with `### Source: filename (tier=...)` headings; if `cba_citations_enabled` is on, each header also carries the best-available locator hint (`p. 14`, `Art. 12`) and the prompt grows a `## Citation format` instruction telling the LLM to emit `[filename, locator]` inline.

### Table query (Sprint 16)

```
prompt_assembler.assemble (after _resolve_rag)
  → rag_service.query_tables(scope_keys, query, top_k=2 or 4)
       → embed query
       → Chroma query on cbc_tables WHERE scope_key in {...}
       → for each hit: load CSV from disk (tables/{doc_stem}/{table_id}.csv)
  → _render_tables(hits) → "## Relevant tables" section with each CSV fenced as ```csv``` (capped 6000 chars per table)
  → table sources merged into AssembledPrompt.sources (as plain doc rows — Sprint 16 polish: tables are internal to CBC, the chat panel just shows the source document)
```

### Document ingest

Two entry points — admin upload (`POST /admin/api/v1/rag/upload`) and file watcher (`rag_watcher` debounced fire). Both end at:

```
rag_service.reindex(scope_key)
  → rag_service._build_index(scope_key)        [acquires _build_locks[scope_key]]
       → SimpleDirectoryReader(files).load_data()
       → _parse_nodes(documents)
            for .md: MarkdownNodeParser → SentenceSplitter (Sprint 15 fix)
            for .pdf/.txt/.docx: SentenceSplitter directly
       → for each node: tag with scope_key + tier
       → if rag_contextual_enabled: _contextualise_nodes (LLM call per chunk)
       → _delete_scope(scope_key)               [drops chunks AND table cards]
       → wrapper.insert_nodes(nodes)            [Chroma upsert]
       → _extract_and_embed_tables(scope_key, files)
            for each file: table_extractor.extract_tables_for_file
            persist CSVs + manifest to disk
            batch-embed cards into cbc_tables
       → log "Built Chroma chunks for scope ..."
  → _sync_derived_country_tags(scope_key)
       → document_metadata.derive_country_tags(scope_key, filenames)
       → company_registry.update_company(fid, slug, country_tags=...)
```

### Compare All

The compare-all session-type flag triggers a separate role prompt (`compare_all.md`) and a multi-scope retrieval where `resolvers.resolve_rag_paths` returns every active company's company-tier scope plus the frontend tier and (if combined) global. `query_tables` runs with `top_k=4` so each company contributes at least one table. The chat layout in `CompanySelectPage.tsx` exposes a `Compare All` virtual company that triggers this mode.

### Session lifecycle

```
session creation        → session_store.create()      (lifespan: cap at session_resume_hours)
   → write metadata.json + system_prompt.md atomically
turn served             → conversation.jsonl appended atomically
context compression     → context_compressor on_threshold (per-turn check)
session_lifecycle scan  → every 300 s:
   for each session:
     if last_activity_age > auto_close_hours: status = closed
     if last_activity_age > auto_destroy_hours and auto_destroy_hours > 0:
       smtp_service.send_summary (if enabled)
       shutil.rmtree(sessions/{token}/)
       delete from session_rag indices
```

---

## §4 Storage layout

Every directory under `/app/data/`. Writer = which service owns the write path. Reader = who reads it on the hot path.

```
/app/data/
├── prompts/                              W: admin API prompts          R: prompt_assembler
│   ├── core.md
│   ├── guardrails.md
│   ├── cba_advisor.md
│   ├── compare_all.md
│   └── context_template.md
├── documents/                            W: admin API rag, watcher     R: rag_service, rag_watcher
│   └── *.pdf|.md|.txt|.docx              (global-tier RAG corpus)
├── tables/                               W: table_extractor (Sprint 16) R: rag_service.query_tables
│   └── {doc_stem}/
│       ├── manifest.json
│       └── {table_id}.csv
├── knowledge/                            W: admin API knowledge / contacts  R: prompt_assembler, auth.py
│   ├── glossary.json
│   ├── organizations.json
│   └── contacts.json
├── chroma/                               W: rag_service                R: rag_service, session_rag
│   ├── chroma.sqlite3                    (collection metadata)
│   └── {uuid}/                           (per-collection HNSW index dirs)
├── sessions/                             W: session_store              R: session_store, polling, lifecycle
│   └── {token}/
│       ├── metadata.json
│       ├── conversation.jsonl
│       ├── system_prompt.md
│       └── uploads/
├── campaigns/                            W: admin API frontends, registry  R: registry, session_rag, polling
│   └── {frontend_id}/
│       ├── frontend.json                 (display_name, url, enabled, status, last_seen)
│       ├── branding.json                 (optional override)
│       ├── session_settings.json
│       ├── rag_settings.json             (combine_global_rag)
│       ├── notifications.json            (optional per-frontend SMTP override)
│       ├── llm_override.json             (optional)
│       ├── orgs_override.json            (optional)
│       ├── prompts/                      (frontend-tier overrides)
│       ├── documents/                    (frontend-tier RAG corpus)
│       ├── tables/                       (frontend-tier extracted tables)
│       ├── companies.json                (list of {slug, display_name, country_tags, ...})
│       └── companies/
│           └── {slug}/
│               ├── company.json          (combine_frontend_rag, combine_global_rag, country_tags)
│               ├── prompts/              (company-tier overrides)
│               ├── documents/            (company-tier RAG corpus — the CBAs themselves)
│               ├── tables/               (company-tier extracted tables — the salary schedules)
│               └── metadata.json         (per-doc country/language/document_type)
├── llm_config.json                       W: admin API llm              R: llm_provider (lifespan)
├── smtp_config.json                      W: admin API smtp             R: smtp_service, polling on close
├── runtime_overrides.json                W: admin API rag (settings)   R: lifespan, runtime_overrides_store
├── branding_defaults.json                W: admin API branding         R: branding_defaults_store, polling push
├── .admin_hash                           W: admin auth setup           R: auth.py
└── .jwt_secret                           W: admin auth setup           R: auth.py
```

Sessions and chroma directories grow unbounded; lifecycle scan handles sessions, `wipe_chroma_and_reindex_all` (admin button) handles chroma. Documents grow with admin uploads — no automatic GC.

---

## §5 Runtime control reference

Every admin-editable setting that affects runtime behaviour. Changes that need a reindex are flagged.

| Key | UI path | Persisted at | Reader | Default | Cost of flip |
|---|---|---|---|---|---|
| `rag_chunk_size` | `Admin → General → RAG Pipeline → Chunk Size` slider | `runtime_overrides.json` | `rag_service` (via `backend_config`) | `1024` | Requires Wipe & Reindex All — chunks need re-splitting |
| `rag_embedding_model` | `Admin → General → RAG Pipeline → Embedding Model` dropdown | `runtime_overrides.json` | `rag_service` | `BAAI/bge-m3` | Requires Wipe & Reindex All — vectors are dim-incompatible |
| `rag_reranker_enabled` | hardcoded constant (no UI) | code | `rag_service.query_scopes` | `True` | n/a |
| `rag_contextual_enabled` | `Admin → General → RAG Pipeline → Contextual Retrieval` toggle | `runtime_overrides.json` | `rag_service._build_index` per ingest | `False` | Triggers async reindex of every scope; default OFF post-Sprint-16 because tables cover its main use case |
| `rag_similarity_top_k` | hardcoded | code | `rag_service` | `8` | n/a |
| `inference.provider` / `model` / `temperature` / `max_tokens` | `Admin → General → LLM → Inference slot` | `llm_config.json` | `llm_provider.stream_chat` | varies | None — next turn picks up the new slot |
| `compressor.*` | `Admin → General → LLM → Compressor slot` | `llm_config.json` | `context_compressor`, CR LLM (when on) | varies | None |
| `summariser.*` | `Admin → General → LLM → Summariser slot` | `llm_config.json` | `prompt_assembler.user_summary`, `smtp_service` | varies | None |
| `compression.enabled` / `first_threshold` / `step_size` | `Admin → General → LLM → Context compression` | `llm_config.json` | `context_compressor` | `False` / `20000` / `15000` | None — affects next turn |
| `routing.document_summary_slot` / `user_summary_slot` / `contextual_retrieval_slot` | `Admin → General → LLM → Summary routing` (3-column block) | `llm_config.json` | `prompt_assembler`, CR pipeline | `summariser` / `summariser` / `compressor` | None for the first two; CR routing change re-evaluated on next reindex |
| `disable_thinking` | `Admin → General → LLM → Thinking mode` toggle | `llm_config.json` | `llm_provider._build_body`, `_apply_no_think` | `True` | None |
| `max_concurrent_turns` | `Admin → General → LLM → Max concurrent turns` (1/2/4/6) | `llm_config.json` | `polling._turn_semaphore` (resized on save) | `4` | None — semaphore resizes immediately |
| `auth_required` | `Admin → Frontends → {frontend} → Session settings → Auth required` | `campaigns/{fid}/session_settings.json` | `polling` push to sidecar | `True` | None — affects next session init |
| `session_resume_hours` | `... → Session resume hours` | same | `session_store` token validation | `48` | None |
| `auto_close_hours` | `... → Auto-close hours` | same | `session_lifecycle` | `72` | None — applied on next 300 s scan |
| `auto_destroy_hours` | `... → Auto-destroy hours` | same | `session_lifecycle` | `0` (off) | None — irreversible privacy wipe on scan |
| `disclaimer_enabled` / `instructions_enabled` | `... → Session settings` toggles | same | polling push | `True` / `True` | None |
| `compare_all_enabled` | `... → Session settings` | same | polling push, `CompanySelectPage` | `False` | None |
| `cba_sidepanel_enabled` | `... → Session settings → CBA sidepanel` | same | polling push, `ChatShell` | `True` | None |
| `cba_citations_enabled` | `... → Session settings → CBA citations` | same | `prompt_assembler` (cite_inline) | `False` | None — affects next prompt |
| `combine_global_rag` (frontend) | `Admin → Frontends → {frontend} → RAG → Combine global RAG` | `campaigns/{fid}/rag_settings.json` | `resolvers.resolve_rag_paths` | `True` | None |
| `combine_frontend_rag` (company) | `... → Company → {company} → RAG → Combine frontend RAG` | `campaigns/{fid}/companies/{slug}/company.json` | same | `True` | None |
| `combine_global_rag` (company) | same panel | same | same | `True` | None |
| Branding fields (global) | `Admin → General → Branding` | `branding_defaults.json` | polling push to sidecar | empty/defaults | None — next session sees new branding |
| Branding override (per-frontend) | `Admin → Frontends → {frontend} → Branding panel` | `campaigns/{fid}/branding.json` | polling push | none | None |
| Prompts (global / frontend / company) | `Admin → General → Prompts` and the per-tier equivalents | `prompts/`, `campaigns/{fid}/prompts/`, `campaigns/{fid}/companies/{slug}/prompts/` | `prompt_assembler` (per turn) | code-shipped defaults | None |
| Glossary / Organizations | `Admin → General → Glossary`, `Admin → General → Organizations` | `knowledge/glossary.json`, `knowledge/organizations.json` | `prompt_assembler` (per turn) | empty | None |
| Contacts (auth allowlist) | `Admin → Registered Users` tab | `knowledge/contacts.json` | `auth.py` on email-code request | empty | None |
| SMTP (host / port / user / password / tls / from / admin recipients / toggles) | `Admin → General → SMTP` | `smtp_config.json` | `smtp_service` | empty | None |
| Frontend `enabled` | `Admin → Frontends → {frontend}` toggle | `campaigns/{fid}/frontend.json` | `polling.list_enabled` | `True` | None — disabled frontends are skipped on next tick |
| Document metadata (country/language/document_type) | `Admin → Frontends → {frontend} → Company → {company} → RAG → metadata edit per file` | `campaigns/{fid}/companies/{slug}/metadata.json` | `document_metadata.derive_country_tags` (on reindex) | empty | Triggers `Company.country_tags` recompute on next reindex |
| `rag_top_k_floor` | `Admin → General → RAG Pipeline → Tuning avanzado` slider | `runtime_overrides.json` | `rag_service.compute_dynamic_top_k` | `5` | None — applies on next query |
| `rag_top_k_ceil` | same panel | `runtime_overrides.json` | same | `40` | None |
| `rag_top_k_per_doc` | same panel | `runtime_overrides.json` | same | `2` | None — `K = clamp(num_files × this, floor, ceil)` |
| `rag_tables_top_k_floor` | same panel | `runtime_overrides.json` | `rag_service.compute_dynamic_tables_top_k` | `2` | None |
| `rag_tables_top_k_ceil_single` | same panel | `runtime_overrides.json` | same | `6` | None — used outside Compare All |
| `rag_tables_top_k_ceil_compare_all` | same panel | `runtime_overrides.json` | same | `12` | None — used inside Compare All so each company contributes |
| `rag_watcher_debounce_seconds` | same panel | `runtime_overrides.json` | `rag_watcher._debounce_seconds()` | `30` (was `5` pre-Sprint-18) | None — applies on next watcher tick |
| `rag_watcher_max_hold_seconds` | same panel | `runtime_overrides.json` | `rag_watcher._max_hold_seconds()` | `300` | None — Sprint 18 ceiling so a non-stop upload can't park reindex forever |
| `rag_watcher_lock_replan_seconds` | same panel | `runtime_overrides.json` | `rag_watcher._lock_busy_replan_seconds()` | `30` | None — Sprint 18 defer when `_build_locks[scope]` held |
| `<api_slot>.api_key_env` (legacy) | `Admin → General → LLM → Inference/Compressor/Summariser → API key env var` | `llm_config.json` | `llm_provider`, `check_slot_health` | empty | None — pattern A: env var set on container |
| `<api_slot>.api_key` (Sprint 19 Fase 1) | `Admin → General → LLM → Inference/Compressor/Summariser → API key (paste)` | `llm_config.json` (sentinel `••••••••` in GET responses) | `llm_provider`, `check_slot_health` (precedence over `api_key_env`) | empty | None — pattern B: paste once, persist on disk |

---

## §6 Failure modes

### Stop / cancel mid-stream
**Trigger:** user clicks Stop in `ChatShell.tsx` → `POST /internal/chat/cancel/{token}` to the sidecar.
**Recovery:** `cancel_watcher_loop` (1 s cycle) drains `/internal/cancellations` and adds the token to `_pending_cancellations`. The in-flight `_process_turn` samples the set every chunk; on hit it breaks streaming and emits a `cancelled` terminal event. Sprint 14 made the cancel set backend-wide rather than per-turn so parallel turns don't fight over the drain.

### Inactivity timeout
**Trigger:** `INACTIVITY_TIMEOUT = 60 s` between successive chunks from the LLM endpoint (Ollama / LM Studio).
**Recovery:** `llm_provider.stream_chat_one_slot` raises; the surrounding `_process_turn` records a `failed` terminal event with reason. Circuit breaker decrements the slot's reliability score; after 3 failures in 60 s the slot enters a 300 s cooldown. UI surfaces nothing special — the user sees an error message and can retry.

### Circuit breaker open
**Trigger:** 3 stream timeouts within 60 s on the same slot.
**Recovery:** that slot is skipped for 300 s. `llm_provider` falls through to the next slot in the chain (compressor → summariser → inference). If all are open, the turn errors out.

### Wipe & Reindex
**Trigger:** `Admin → General → RAG Pipeline → Wipe & Reindex All` (red button).
**Behaviour:** drops every in-memory cache (`_indexes`, `_bm25_cache`, `_embed_model`, `_reranker`), `client.reset()` on Chroma to atomically clear in-memory + on-disk state, purges every `tables/` directory, then `reindex_all_scopes()` rebuilds. Offloaded to `asyncio.to_thread` so the FastAPI event loop stays free (admin UI + polling keep working). Per-scope `_build_locks` (Sprint 16 #38) prevent a chat query racing the rebuild from triggering a redundant second `_build_index` on the same scope.

**Required after:** changing `rag_embedding_model` (dim shift) or `rag_chunk_size` (split shift). Optional after `rag_contextual_enabled` toggle (admin endpoint already triggers `reindex_all_scopes`).

### Partial reindex detection
**Trigger:** `wipe_chroma_and_reindex_all` raises if any per-scope reindex returned an `error` field. Mixed-state half-indexed Chroma is worse than failing loudly.
**Recovery:** error bubbles up to the admin endpoint as 500 with the failure summary. Admin retries. If the failure is persistent (e.g. an HF token issue blocking BGE-M3 download), the admin must fix the underlying issue before the next attempt.

### Watcher debouncing under bulk copies
**Trigger:** an iCloud sync / bulk copy fires hundreds of `created`/`modified` events into `documents/`.
**Recovery:** `_ScopeDebouncer` collapses events into a single fire per scope after a 30 s quiet window (Sprint 18 raised from 5 s — admin-tunable). The first event starts the timer; every subsequent event in the same scope resets it. `_is_ignored` filters out `.icloud`, `.DS_Store`, `._*` first.

### Watcher amplification (Sprint 18 prevented)
**Trigger:** browser file picker uploads N files with > 5 s gaps between them. Pre-Sprint-18 the 5 s debounce was too short → each file fire after the previous reindex cycle, producing N reindex passes (observed: 3 full passes for a 20-file Amcor upload, ~150 s of redundant work).
**Recovery:** Sprint 18 Fase 2 changes the debouncer in three ways: default debounce 30 s tolerates the typical browser pacing; `MAX_DEBOUNCE_HOLD_SECONDS = 300` ceiling forces the fire even if events keep arriving, so a slow continuous upload still reindexes every 5 min instead of being deferred forever; `_fire(scope)` probes `rag_service._build_locks[scope].acquire(blocking=False)` and reschedules itself 30 s later instead of competing for the lock when a build is already in flight. Effect: 20-file upload = one reindex at the end of the batch, not N.

### Prefix-cache cold spots
Not really a failure mode but a measurable cost. Every `Wipe & Reindex All` invalidates Ollama's prefix cache for that prompt prefix; first chat afterwards has TTFT ~3-4× the warm steady-state. Daniel works around this by waiting a turn or two after a wipe before stress-testing latency.

### Concurrent reindex of the same scope
**Trigger:** an admin double-clicks Wipe / a chat query hits during wipe / the watcher debounce expires during wipe.
**Recovery:** `_build_locks[scope_key]` (`threading.RLock`) serialises. Second comer waits, checks `_scope_chunk_count` after the lock is released, and skips the rebuild if chunks are already present. Sprint 16 #38 is the fix; without it the wipe ran twice and took ~50 s instead of ~25 s.

### Session destroy under privacy mode
**Trigger:** `session_lifecycle` finds a session whose age exceeds `auto_destroy_hours` and `auto_destroy_hours > 0`.
**Recovery:** `smtp_service.send_summary` (if enabled) emails the user-summary, then `shutil.rmtree(sessions/{token}/)` removes everything — conversation, system prompt, uploads, session-RAG index. Irreversible. The UI shows "session expired"; user can start a new one if they want.

---

## §7 Dependencies and integrations

### Ollama (primary LLM provider)
- Configured in `config/deployment_backend.json`: `ollama_endpoint`, `ollama_summariser_model`, `ollama_num_ctx`. Per-slot model override comes from `llm_config.json`.
- Probed at startup via `GET /api/tags`; presence reflected in `Admin → General → LLM → Refresh providers`.
- Graceful degradation: per-request timeout (`STREAM_TIMEOUT = 300 s` total, `INACTIVITY_TIMEOUT = 60 s` per chunk) + circuit breaker. Fallback chain across slots.
- No Dockerfile pre-download; runtime probe is enough. The Mac Studio host runs Ollama on port 11434 (LaunchAgent), see `Ollama_UNI_Tools_Config.md` in repo root.

### LM Studio (alternate LLM provider)
- Configured per-slot in `llm_config.json` with `provider: lm_studio` + a model id. Endpoint defaults to `http://host.docker.internal:1234`.
- Same circuit-breaker + timeout strategy as Ollama.
- No Dockerfile work; LM Studio runs on the host outside the container.

### Chroma (vector store)
- Pinned in `src/backend/requirements.txt`: `chromadb>=0.5,<2.0` and `llama-index-vector-stores-chroma>=0.4`.
- Persistent at `/app/data/chroma/` via `chromadb.PersistentClient(path=..., settings=ChromaSettings(allow_reset=True))`. `allow_reset=True` is required for `wipe_chroma_and_reindex_all` to succeed atomically (Sprint 15 phase 3.1 lesson).
- Graceful degradation: on `_get_chroma_collection` failure, queries return empty results; chat continues without retrieval.

### BAAI/bge-m3 (embedder)
- Configured via `runtime_overrides.json` → `rag_embedding_model` (admin-editable) on top of `deployment_backend.json` default.
- Pre-downloaded in `Dockerfile.backend` at build time (~2.2 GB to `/root/.cache/huggingface/`) so first-use is local-disk load only — no network.
- Graceful degradation: alternative `sentence-transformers/all-MiniLM-L6-v2` is also pre-downloaded and selectable from the admin dropdown. Switching is instant; the cost is the wipe-and-reindex.

### bge-reranker-v2-m3 (cross-encoder)
- Configured via `deployment_backend.json` → `rag_reranker_model`. Read-only from admin (only one reranker pre-downloaded).
- Pre-downloaded in `Dockerfile.backend` (~568 MB).
- Graceful degradation: reranker load failures log a warning and `query_scopes` skips reranking. Retrieval still returns the fused BM25+vector top-K.

### pdfplumber (Sprint 16 table extractor)
- Pinned in `requirements.txt`: `pdfplumber>=0.11`. Pure Python; no Dockerfile pre-download.
- Graceful degradation: missing `pdfplumber` makes `extract_pdf_tables` return `[]` with an error log. Documents still go through prose RAG.
- Scanned (image-only) PDFs return `[]` even with pdfplumber present — accepted low-fidelity behaviour, no OCR fallback.

### watchdog (file watcher)
- Pinned: `watchdog>=4.0`.
- Toggle: `rag_watcher_enabled` in `deployment_backend.json` (default `True`). Set to `False` and the file watcher does not start at lifespan; admins fall back to manual reindex from the admin panel.

### sentence-transformers, llama-index-* (RAG plumbing)
- Pinned in `requirements.txt`: `sentence-transformers>=2.2`, `llama-index-core>=0.13,<0.15`, `llama-index-readers-file>=0.5`, `llama-index-embeddings-huggingface>=0.6`, `llama-index-retrievers-bm25>=0.5`, `llama-index-vector-stores-chroma>=0.4`. Versions track each other (`llama-index-retrievers-bm25 0.5+` requires `core 0.13+`, etc.).

### FastAPI / uvicorn / pydantic
- Pinned: `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `pydantic>=2.11.5`. Entrypoint: `uvicorn src.main:app --host 0.0.0.0 --port 8000`.
- No graceful degradation: container fails to start if these are unavailable.

---

## §8 Architectural invariants

Things that must remain true. If a sprint changes one, the change is an ADR-grade decision.

1. **Backend is the single source of truth.** Frontends are passive relays. No business logic on the frontend, no state on the frontend that isn't downstream of a backend push. Enforced by: `polling.py` push patterns, `frontend_registry.py` opacity to frontend internals.

2. **Three-tier config resolution: company → frontend → global.** Never skip a level. Enforced by: `resolvers.py` → `resolve_prompt`, `resolve_rag_paths`. Adding a fourth tier (e.g. per-user) requires an ADR.

3. **Atomic JSON state.** Every JSON write goes through `_paths.atomic_write_json` (write to `.tmp` then `os.rename`). Enforced by: `_paths.py:atomic_write_json` and grep-discipline — no service writes JSON directly with `open(...).write(...)`.

4. **Polling is fire-and-forget per turn.** `polling._tick` spawns each turn coroutine via `asyncio.create_task`; the tick itself doesn't await turn completion. Enforced by: Sprint 14 ADR-008 + the `_turn_semaphore` cap.

5. **One Chroma collection per data type, scope_key as metadata filter.** Not one collection per scope. Enforced by: `rag_service._get_chroma_collection`, `_get_tables_collection`, `_scope_metadata_filter`. Switching to per-scope collections would simplify cleanup but break Compare All's union queries.

6. **Per-scope reindex is serialised.** No two threads can run `_build_index` on the same `scope_key` simultaneously. Enforced by: `rag_service._build_locks[scope_key]` + `RLock` so callers can re-enter (`get_index` → `_build_index`).

7. **Embedding inputs respect BGE-M3's 8192-token cap.** Enforced by: Sprint 15 chunker fix in `rag_service._parse_nodes` — markdown header nodes are piped through `SentenceSplitter(chunk_size=rag_chunk_size)` so no node exceeds the embedder's input window. Defensive WARN log if `max chunk > 30000 chars`.

8. **Guardrails always inject regardless of tier.** Per CLAUDE.md, core + guardrails are non-negotiable. Enforced by: `prompt_assembler.assemble` — `core` and `guardrails` are unconditionally placed first in the layers list.

9. **Session destroy is irreversible and complete.** When `auto_destroy_hours` fires, the entire session dir (including uploads + indices) is removed. No tombstones. Enforced by: `session_lifecycle._destroy_session`.

10. **Admin reindex endpoints don't block the FastAPI event loop.** Every reindex handler uses `await asyncio.to_thread(...)` to run the sync work in a worker thread. Enforced by: Sprint 16 Fase 0 + the 5 admin endpoints in `api/v1/admin/rag.py`.

11. **Tables are CBC-internal, not user-facing.** The Sprint 16 table pipeline is a retrieval booster; the CitationsPanel shows source documents only, not table cards. Enforced by: `prompt_assembler` emits source rows for table-only docs (so users can still download the CBA), but no `kind: "table"` entries flow to the frontend.

12. **Top-K scales with corpus size, never hardcoded per turn.** Sprint 18 Fase 1 replaced the static `RAG_TOP_K_PER_SCOPE = 5` with `rag_service.compute_dynamic_top_k(scope_keys)` and `compute_dynamic_tables_top_k(...)`. Every retrieval path computes K from `num_files_in_scope × per_doc`, clamped by floor / ceil read live from `backend_config.rag_top_k_*` (Fase 4 — admin-tunable). Enforced by: `prompt_assembler._resolve_rag` and `assemble`. Adding a new retrieval path that hardcodes K is a regression.

13. **Clause integrity in chunks.** Sprint 18 Fase 3 — when a source document uses numbered clause headers (Art. N / Article N / Cláusula N / Section N.N.N / ANEXO I / Annexe N), no chunk crosses a clause boundary unless the clause body alone exceeds `chunk_size`. When it does, all sub-chunks of that clause inherit the same `clause_id` metadata, which `prompt_assembler._citation_label_for` prefers as the citation locator. Enforced by: `rag_service._segment_by_clause` + `_emit_clause_aware` in `_parse_nodes`, plus `Chunk.clause_id` propagation in `query()`.

14. **API keys never leave the container in GET responses.** Sprint 19 Fase 1 introduces inline API key storage (paste-once-persist pattern, Open WebUI style). `llm_config_store.redact_for_response` substitutes the literal key with the sentinel `••••••••` so the admin UI never receives the value back even after Save. PUT logic preserves the existing key when it sees the sentinel as input (admin edited other fields without retyping the key). Enforced by: `redact_for_response` + the PUT handler in `api/v1/admin/llm.py`. Adding a debug endpoint that returns raw config is a regression.

---

## §9 Admin UI map

Walk-through from Daniel's POV. Tabs in the order they appear in the admin shell.

### Tab — General

`CBCopilot/src/admin/src/GeneralTab.tsx`. Sections, top to bottom:

- **Branding** (`sections/BrandingSection.tsx`) — global defaults (app title, owner, logo URL, primary/secondary color, disclaimer, instructions). Auto-translate button calls `branding_translator.py` using the summariser slot. Persisted at `branding_defaults.json`.
- **Prompts** (`sections/PromptsSection.tsx`) — five editors for `core.md`, `guardrails.md`, `cba_advisor.md`, `compare_all.md`, `context_template.md` at the global tier. Persisted at `prompts/*.md`. Read by `prompt_store.py`.
- **RAG documents** (`sections/RAGSection.tsx`) — global-tier upload/list/delete + per-doc metadata (country / language / document_type) + Reindex / Reindex All button (Sprint 15 phase 3 cascade rule: at global tier "Reindex" means reindex-all-scopes). Persisted at `documents/`. Read by `rag_store.py` + `rag_service.py`.
- **RAG pipeline** (`sections/RAGPipelineSection.tsx`) — embedding model dropdown, chunk size slider (512/1024/1536/2048), Save (in-memory + persist), Wipe & Reindex All (red button), Contextual Retrieval toggle. Persisted at `runtime_overrides.json`.
- **Glossary** (`sections/GlossarySection.tsx`) — JSON editor (term → definition). Persisted at `knowledge/glossary.json`. Read by `prompt_assembler` per turn.
- **Organizations** (`sections/OrgsSection.tsx`) — JSON editor for the organizations list. Persisted at `knowledge/organizations.json`.
- **LLM** (`sections/LLMSection.tsx`) — three slot editors (inference / compressor / summariser), thinking-mode toggle, max-concurrent-turns selector, summary-routing block (3 columns: doc summary, user summary, contextual retrieval), context-compression block. Persisted at `llm_config.json`. Read by `llm_provider.py`.
- **SMTP** (`sections/SMTPSection.tsx`) — host / port / user / password / TLS / from address / admin recipients / toggles (send_summary_to_user, send_summary_to_admin, notify_admin_on_upload). Persisted at `smtp_config.json`.
- **Guardrails** (`sections/GuardrailsSection.tsx`) — read-only info card showing thresholds + pattern counts. Pattern tables live in `guardrails.py` and aren't editable from the UI.

### Tab — Frontends

`CBCopilot/src/admin/src/FrontendsTab.tsx`. Lists registered frontends; click one to expand. Selected frontend shows the per-frontend stack:

- **Branding panel** (`panels/BrandingPanel.tsx`) — toggle + form. Persisted at `campaigns/{fid}/branding.json`.
- **Session settings** (`panels/SessionSettingsPanel.tsx`) — auth_required, session_resume_hours, auto_close_hours, auto_destroy_hours, disclaimer/instructions/compare_all/cba_sidepanel/cba_citations toggles. Persisted at `campaigns/{fid}/session_settings.json`.
- **Prompts** (`sections/PromptsSection.tsx` reused with `frontendId`) — per-frontend prompt overrides. Persisted at `campaigns/{fid}/prompts/`.
- **RAG documents** (`sections/RAGSection.tsx` reused) — frontend-tier docs + the "Combine global RAG" toggle. Persisted at `campaigns/{fid}/documents/` + `campaigns/{fid}/rag_settings.json`.
- **Per-frontend organizations** (`panels/PerFrontendOrgsPanel.tsx`) — override list. Persisted at `campaigns/{fid}/orgs_override.json`.
- **Per-frontend LLM** (`panels/PerFrontendLLMPanel.tsx`) — override slot config. Persisted at `campaigns/{fid}/llm_override.json`.
- **Companies** (`panels/CompanyManagementPanel.tsx`) — list of companies under the frontend. Each expands to:
  - Company JSON edit (display_name, slug, country_tags overrides — though `country_tags` are also auto-derived from doc metadata + filenames).
  - **Prompts** at company tier.
  - **RAG documents** at company tier (the CBAs themselves).
  - **Tables** (`sections/TablesSection.tsx`) — Sprint 16. Collapsible. Lists extracted tables per CBA with `name · source_location · N rows · CSV download` link. Re-extract button. Sprint 16 polish: only mounted at company tier; not in General or Frontends tabs.

### Tab — Sessions

`CBCopilot/src/admin/src/SessionsTab.tsx`. Filterable session list (all / active / completed / flagged). Columns: token, frontend, company, country, status, message count, violations, last_activity. Click a session to inspect its conversation, uploads, summary; flag/unflag/destroy actions.

Persisted at `sessions/{token}/`. Reader: `session_store.py`. The destroy action goes through `session_lifecycle._destroy_session`.

### Tab — Registered Users

`CBCopilot/src/admin/src/RegisteredUsersTab.tsx`. Allowlist for `auth_required` frontends. Scope selector (global / per-frontend with replace|append mode). xlsx/csv import + export. Persisted at `knowledge/contacts.json`.

### Top-bar — Language selector

15 languages via the `useT()` hook from `i18n.ts`. Per-component fallback chain: `DICTIONARIES[lang]?.[key] ?? EN[key] ?? key`. Sprint 12 added the auto-translate plumbing for branding text; admin UI strings live in `i18n.ts` and are added per-sprint when new keys appear (Sprint 16 added the Tables section keys).

---

## §10 Pointers

- **`docs/SPEC.md`** — full product specification. §4 covers backend services, §5 admin panel, §6 config schema, §8 security & privacy, §9 deployment.
- **`docs/MILESTONES.md`** — sprint plans + the `Sprint 15 follow-ups` backlog (items A-Q) with closure annotations. Sprint 16 + 17 plans are the current ones.
- **`docs/STATUS.md`** — running sprint state and acceptance results. Updated at sprint start + close.
- **`docs/CHANGELOG.md`** — every shipped sprint + follow-up commit, newest first.
- **`docs/architecture/decisions.md`** — ADRs 001-009. ADR-008 (parallel polling, Sprint 14) and ADR-009 (Structured Table Pipeline, Sprint 16) are the most recent and load-bearing.
- **`docs/knowledge/lessons-learned.md`** — pitfalls from HRDD Helper + CBC. iCloud sync, debounce, atomic writes, prompt assembly order, sidecar memory, OrbStack DNS, Compare All memory pressure, session destroy completeness.
- **`docs/knowledge/hrdd-helper-patterns.md`** — what to copy and what to rewrite when porting from HRDDHelper/.
- **`docs/IDEAS.md`** — captured-but-not-scoped ideas. Useful when something feels familiar — check here before re-debating it.
- **`Ollama_UNI_Tools_Config.md`** (repo root) — the host-side Ollama setup on Daniel's Mac Studio (LaunchAgent, preload, NUM_PARALLEL semantics).
- **`CLAUDE.md`** — project instructions for Claude Code. Read order, deployment topology, git rules, sprint workflow.
