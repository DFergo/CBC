# HRDD Helper — Reusable Patterns for CBC

Reference: `HRDDHelper/` in the project root.

## Services to Reuse (Copy + Adapt)

### 1. Polling Service (`HRDDHelper/src/backend/services/polling.py`)
- Polls registered frontends every N seconds
- Dequeues messages, dispatches to LLM pipeline
- Posts streaming responses back via SSE
- **CBC adaptation:** Same logic, different prompt assembly + RAG resolution

### 2. Session Store (`HRDDHelper/src/backend/services/session_store.py`)
- Disk-backed with in-memory cache
- Atomic JSON writes
- JSONL conversation log
- **CBC adaptation:** Add `company_slug`, `comparison_scope` to session metadata. Add auto-destroy logic. Remove internal case file generation.

### 3. LLM Provider (`HRDDHelper/src/backend/services/llm_provider.py`)
- OpenAI-compatible API client
- Multi-slot (inference, summariser, reporter)
- Circuit breaker per slot
- Health checks
- Per-frontend overrides
- **CBC adaptation:** Remove reporter slot. Keep inference + summariser.

### 4. SMTP Service (`HRDDHelper/src/backend/services/smtp_service.py`)
- Configurable SMTP (host, port, auth, TLS)
- Used for auth codes and summaries
- **CBC adaptation:** Add admin alert for user document uploads.

### 5. Guardrails (`HRDDHelper/src/backend/services/guardrails.py`)
- Keyword/pattern-based safety checks
- Configurable max triggers before warning
- Separate from prompt guardrails (these are runtime checks)
- **CBC adaptation:** Adjust rules for CBA context (no fabrication of terms, no legal advice).

### 6. Frontend Registry (`HRDDHelper/src/backend/services/frontend_registry.py`)
- CRUD for registered frontends
- Health polling (online/offline/degraded)
- Persistent JSON storage
- **CBC adaptation:** Direct reuse.

### 7. Context Compressor (`HRDDHelper/src/backend/services/context_compressor.py`)
- Summarizes older conversation messages when context exceeds threshold
- Uses summariser LLM slot
- **CBC adaptation:** Direct reuse. Important for Compare All mode.

### 8. Evidence Processor (`HRDDHelper/src/backend/services/evidence_processor.py`)
- Handles file uploads during chat
- Extracts text from PDFs, images (OCR)
- **CBC adaptation:** Reuse for document extraction. Add session RAG indexing.

## Services to Rewrite

### 1. Prompt Assembler (`HRDDHelper/src/backend/services/prompt_assembler.py`)
- HRDD: 2-tier (global → frontend), multi-role (worker/organizer/officer), multi-mode (document/interview/advisory)
- **CBC needs:** 3-tier (global → frontend → company), single role (cba_advisor), Compare All mode

### 2. RAG Service (`HRDDHelper/src/backend/services/rag_service.py`)
- HRDD: 2-tier (global + per-frontend), admin upload only
- **CBC needs:** 3-tier, file watcher, session RAG, document metadata (country tags), Compare All filtering

### 3. Session Lifecycle (`HRDDHelper/src/backend/services/session_lifecycle.py`)
- HRDD: auto-close + auto-archive, generates multiple report types
- **CBC needs:** auto-close + auto-archive + auto-destroy, generates user summary only

## New Services

### 1. Company Registry
- No equivalent in HRDD Helper
- Manages company CRUD per frontend
- Stores company config (prompt_mode, rag_mode, country_tags)

### 2. RAG File Watcher
- No equivalent in HRDD Helper
- Uses watchdog library
- Debounced, scope-aware reindexing

## Frontend Components to Reuse

### Direct Reuse
- `LanguageSelector.tsx` — Identical
- `DisclaimerPage.tsx` — Identical (configurable enabled/disabled)
- `SessionPage.tsx` — Identical (token generation)
- `AuthPage.tsx` — Identical (email verification)
- `InstructionsPage.tsx` — Identical
- `ChatShell.tsx` — Adapted (same chat UI, different context)

### Rewrite
- `RoleSelectPage.tsx` → `CompanySelectPage.tsx` — Different layout (wide buttons, vertical), different data source (company list from backend)
- `SurveyPage.tsx` — Different fields (country, region, org, query, comparison scope, document upload)

## Admin Components

### Reuse (with modification)
- `LoginPage.tsx`, `SetupPage.tsx` — Identical
- `SessionsTab.tsx` — Adapted (different session metadata)
- `SMTPTab.tsx` — Identical
- `RegisteredUsersTab.tsx` — Identical
- `LLMTab.tsx` — Adapted (2 slots instead of 3)

### Rewrite
- `Dashboard.tsx` — Two tabs (General + Frontends) instead of multiple tabs
- `FrontendsTab.tsx` — Completely redesigned with company management, 3-tier config
- `PromptsTab.tsx` + `RAGTab.tsx` → Merged into `GeneralTab.tsx` (global config)

## Docker / Config to Reuse

- `Dockerfile.backend` — Same pattern (multi-stage)
- `Dockerfile.frontend` — Same pattern (React + Nginx + sidecar)
- `docker-compose.*.yml` — Same structure, different service names
- `config/nginx/frontend.conf` — Direct reuse
- `config/supervisord.conf` — Direct reuse
