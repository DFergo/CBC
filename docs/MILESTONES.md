# CBC — Sprint Milestones & Acceptance Criteria

**Spec reference:** `docs/SPEC.md`
**Status tracking:** `docs/STATUS.md`

Each sprint has explicit acceptance criteria. A sprint is NOT done until ALL criteria pass.

---

## Sprint 1 — Scaffolding & Core Backend

**Goal:** Backend starts, serves admin SPA login, frontend sidecar runs and responds to health checks.

### Deliverables
- [ ] `CBCopilot/src/backend/main.py` — FastAPI app with lifespan, CORS, admin SPA serving
- [ ] `CBCopilot/src/backend/core/config.py` — Pydantic config model adapted from HRDD Helper
- [ ] `CBCopilot/src/backend/api/v1/admin/auth.py` — Admin auth (setup, login, JWT)
- [ ] `CBCopilot/src/frontend/sidecar/main.py` — Sidecar with health endpoint + message queue
- [ ] `CBCopilot/Dockerfile.backend` — Multi-stage: admin build + Python runtime
- [ ] `CBCopilot/Dockerfile.frontend` — Multi-stage: React build + Nginx + sidecar
- [ ] `CBCopilot/docker-compose.backend.yml`
- [ ] `CBCopilot/docker-compose.frontend.yml`
- [ ] `CBCopilot/config/deployment_backend.json`
- [ ] `CBCopilot/config/deployment_frontend.json`
- [ ] `CBCopilot/config/nginx/frontend.conf`
- [ ] `CBCopilot/config/supervisord.conf`

### Acceptance Criteria
- [ ] `docker compose -f docker-compose.backend.yml up` starts without errors
- [ ] `GET http://localhost:8100/health` returns `{"status": "ok"}` (host port — configurable via `CBC_BACKEND_PORT`)
- [ ] `GET http://localhost:8100/admin/` serves the admin SPA (login page)
- [ ] Admin setup flow works: set password → login → JWT returned
- [ ] `docker compose -f docker-compose.frontend.yml up` starts without errors
- [ ] `GET http://localhost:8190/internal/health` returns `{"status": "ok"}` (sidecar via Nginx proxy — host port configurable via `CBC_FRONTEND_PORT`)
- [ ] Sidecar is reachable from the backend container (verified with `curl` inside the Docker network)

### Spec Sections Covered
- §2.1 (Components), §2.2 (Pull-Inverse), §6.1 (Backend Config), §6.2 (Frontend Config), §9 (Deployment)

> **Scope note (ADR-007):** Active polling + online-status detection moved to Sprint 4 when `frontend_registry.py` lands. Sprint 1 only proves reachability, not a running polling loop.

---

## Sprint 2 — Frontend Page Flow (No Chat Yet)

**Goal:** User can navigate the full frontend flow from language selection to survey page. No chat functionality yet — survey submits and shows a "coming soon" placeholder.

### Deliverables
- [ ] `CBCopilot/src/frontend/src/App.tsx` — Router with page flow
- [ ] `CBCopilot/src/frontend/src/components/LanguageSelector.tsx`
- [ ] `CBCopilot/src/frontend/src/components/DisclaimerPage.tsx`
- [ ] `CBCopilot/src/frontend/src/components/SessionPage.tsx`
- [ ] `CBCopilot/src/frontend/src/components/AuthPage.tsx`
- [ ] `CBCopilot/src/frontend/src/components/InstructionsPage.tsx`
- [ ] `CBCopilot/src/frontend/src/components/CompanySelectPage.tsx` — NEW component
- [ ] `CBCopilot/src/frontend/src/components/SurveyPage.tsx`
- [ ] `CBCopilot/src/frontend/src/i18n.ts` — i18next setup
- [ ] `CBCopilot/src/frontend/src/types.ts`
- [ ] `CBCopilot/src/frontend/package.json`
- [ ] Sidecar endpoints: `/internal/config` (returns frontend config + company list)

### Acceptance Criteria
- [ ] Language selection page shows and stores choice
- [ ] Disclaimer page displays and "Accept" advances to next page
- [ ] Session token is generated and stored in browser
- [ ] Auth page sends email verification code (if auth_required = true)
- [ ] Auth page is skipped when auth_required = false
- [ ] Instructions page displays and advances
- [ ] Company selection page shows "Compare All" + company buttons from backend config
- [ ] Selecting a company advances to survey
- [ ] Survey page shows all fields per §3.4
- [ ] Survey submit stores data in sidecar and shows placeholder
- [ ] "Compare All" selection shows comparison scope field in survey
- [ ] Full page flow works in Docker

### Spec Sections Covered
- §3 (User Flow), §6.2 (Frontend Config), §7 (Internationalization)

---

## Sprint 3 — Company Registry & Admin General Tab

**Goal:** Admin can configure global settings (prompts, RAG, glossary, orgs, LLM, SMTP) via the General tab. Company registry API works.

### Deliverables
- [ ] `CBCopilot/src/backend/services/company_registry.py` — CRUD for companies per frontend
- [ ] `CBCopilot/src/backend/api/v1/admin/companies.py` — Company API endpoints
- [ ] `CBCopilot/src/backend/api/v1/admin/prompts.py` — Prompt management (global + per-frontend + per-company)
- [ ] `CBCopilot/src/backend/api/v1/admin/rag.py` — RAG management (3-tier)
- [ ] `CBCopilot/src/backend/api/v1/admin/knowledge.py` — Glossary + organizations
- [ ] `CBCopilot/src/backend/api/v1/admin/llm.py` — LLM config (2 slots × 3 provider types: `lm_studio`, `ollama`, `api`; see SPEC §4.7)
- [ ] `CBCopilot/src/backend/api/v1/admin/smtp.py` — SMTP config
- [ ] `CBCopilot/src/admin/src/GeneralTab.tsx` — Global config UI
- [ ] `CBCopilot/src/admin/src/Dashboard.tsx` — Tab navigation
- [ ] Default prompt files in `CBCopilot/src/backend/prompts/`
- [ ] Default glossary + organizations in `CBCopilot/src/backend/knowledge/`

### Acceptance Criteria
- [ ] Admin General tab loads with all sub-sections
- [ ] Can edit and save global prompts via admin
- [ ] Can upload documents to global RAG and trigger reindex
- [ ] RAG stats endpoint returns document count + index size
- [ ] Can manage glossary terms (CRUD)
- [ ] Can manage organizations list (CRUD)
- [ ] LLM config saves and health check returns status per slot, for all three provider types (`lm_studio`, `ollama`, `api`)
- [ ] API provider flavor picker (anthropic / openai / openai_compatible) works; API key env var name is saved (the value itself is never stored)
- [ ] SMTP config saves and test email sends successfully
- [ ] Company API: POST creates company, PATCH updates, DELETE removes
- [ ] Company list returned via `/admin/api/v1/frontends/{fid}/companies`
- [ ] Default prompts installed on first backend start

### Spec Sections Covered
- §4.1 (Prompt Assembler), §4.4 (Company Registry), §5.1 (Admin Layout - General Tab), §5.2 (Admin Auth)

---

## Sprint 4 — Admin Frontends Tab & 3-Tier Config

**Goal:** Admin can fully configure per-frontend and per-company settings from the Frontends tab. Config inheritance works correctly.

### Deliverables
- [ ] `CBCopilot/src/admin/src/FrontendsTab.tsx` — Complete frontend config UI
- [ ] `CBCopilot/src/backend/api/v1/admin/frontends.py` — Frontend CRUD + per-frontend config
- [ ] `CBCopilot/src/backend/services/frontend_registry.py` — Adapted from HRDD Helper
- [ ] Backend prompt resolution logic: company → frontend → global
- [ ] Backend RAG resolution logic: configurable modes per company
- [ ] Backend organizations resolution: global / own / combine per frontend

### Acceptance Criteria
- [ ] Backend polls sidecar and detects it as online (moved from Sprint 1 per ADR-007)
- [ ] Frontend dropdown shows all registered frontends
- [ ] Selecting a frontend loads its current config
- [ ] Can override branding per frontend
- [ ] Can add/edit prompts per frontend (or toggle "inherit global")
- [ ] Can upload RAG docs per frontend
- [ ] Can manage company list (add, remove, rename, reorder, enable/disable)
- [ ] Expanding a company shows prompt and RAG config
- [ ] Company rag_mode dropdown works (own_only, inherit_frontend, inherit_all, combine_*)
- [ ] Organizations list per frontend: toggle global / own / combine
- [ ] Session settings configurable per frontend (auth, auto_close, auto_destroy, resume)
- [ ] Feature toggles work (disclaimer, instructions, compare_all)
- [ ] Prompt resolution: company prompt served when exists, falls back to frontend then global
- [ ] RAG resolution: documents combined according to rag_mode setting

### Spec Sections Covered
- §2.4 (Three-Tier Config), §4.4 (Company Registry), §5.1 (Admin Layout - Frontends Tab)

---

## Sprint 5 — RAG Engine + File Watcher

**Goal:** RAG indexing works at all three tiers. File watcher detects changes on disk and triggers reindex automatically.

### Deliverables
- [ ] `CBCopilot/src/backend/services/rag_service.py` — 3-tier RAG with lazy loading
- [ ] `CBCopilot/src/backend/services/rag_watcher.py` — File watcher with debouncing
- [ ] Session RAG (temporary per-session index for user uploads)
- [ ] Document metadata support (country, language, document_type)
- [ ] Compare All mode: load filtered RAGs by comparison scope

### Acceptance Criteria
- [ ] Upload document to global RAG → indexed and queryable
- [ ] Upload document to frontend RAG → indexed and queryable
- [ ] Upload document to company RAG → indexed and queryable
- [ ] RAG mode "combine_all": query returns chunks from company + frontend + global
- [ ] RAG mode "own_only": query returns only company chunks
- [ ] Place a .pdf in the documents folder on disk → file watcher triggers reindex within 10 seconds
- [ ] Delete a document from disk → file watcher triggers reindex
- [ ] Bulk copy 10 files → single reindex after debounce period (5s)
- [ ] `.icloud` and `.DS_Store` files are ignored by watcher
- [ ] Session RAG: user uploads document → queryable in that session only
- [ ] Session RAG: session destroyed → index files deleted
- [ ] Compare All national mode: only returns chunks tagged with user's country
- [ ] Compare All global mode: returns chunks from all companies

### Spec Sections Covered
- §4.2 (RAG Service), §4.3 (RAG File Watcher), §3.3 (Compare All Mode)

---

## Sprint 6 — Chat Engine & Prompt Assembly

**Goal:** Full chat works: user sends message, backend processes with assembled prompt + RAG, streams response.

### Deliverables
- [ ] `CBCopilot/src/backend/services/prompt_assembler.py` — 3-tier prompt assembly
- [ ] `CBCopilot/src/backend/services/llm_provider.py` — Adapted (2 slots)
- [ ] `CBCopilot/src/backend/services/polling.py` — Adapted from HRDD Helper
- [ ] `CBCopilot/src/backend/services/guardrails.py` — Adapted rules
- [ ] `CBCopilot/src/backend/services/context_compressor.py` — Reused
- [ ] `CBCopilot/src/frontend/src/components/ChatShell.tsx` — Chat UI with streaming
- [ ] Sidecar SSE streaming endpoint
- [ ] Initial query injection (survey query → first chat message)

### Acceptance Criteria
- [ ] User submits survey → enters chat → initial query appears as first message
- [ ] AI responds to initial query with streamed response
- [ ] Response uses appropriate RAG context (company-specific or Compare All)
- [ ] Prompt assembly includes: core + guardrails + role prompt + context + knowledge + RAG
- [ ] Guardrails fire on out-of-scope queries
- [ ] Context compression kicks in when conversation exceeds threshold
- [ ] Streaming works (tokens appear incrementally, not all at once)
- [ ] Chat history is preserved across messages in the session
- [ ] Document upload during chat: file indexed into session RAG, available for subsequent queries

### Spec Sections Covered
- §4.1 (Prompt Assembler), §4.7 (LLM Provider), §4.10 (Guardrails), §3.5 (Document Upload)

---

## Sprint 7 — Sessions & Lifecycle

**Goal:** Session management works: creation, recovery, auto-close, auto-destroy, user summary.

### Deliverables
- [ ] `CBCopilot/src/backend/services/session_store.py` — Adapted from HRDD Helper
- [ ] `CBCopilot/src/backend/services/session_lifecycle.py` — With auto-destroy
- [ ] `CBCopilot/src/backend/api/v1/admin/sessions.py` — Session admin endpoints
- [ ] `CBCopilot/src/admin/src/SessionsTab.tsx` — Session viewer
- [ ] `CBCopilot/src/backend/services/smtp_service.py` — Reused
- [ ] User summary generation prompt
- [ ] Admin alert on user document upload
- [ ] Registered users tab

### Acceptance Criteria
- [ ] Session created on survey submit, stored on disk
- [ ] Session recovery works (token + resume within configured hours)
- [ ] Auto-close: session closes after inactivity period
- [ ] Auto-destroy: session files completely deleted after configured hours (when > 0)
- [ ] Auto-destroy: setting to 0 keeps sessions indefinitely
- [ ] User summary: generated at session close, emailed to user
- [ ] Admin alert: email sent when user uploads document
- [ ] Admin sessions tab: lists sessions, shows metadata, allows viewing messages
- [ ] Registered users tab shows auth history

### Spec Sections Covered
- §4.5 (Session Store), §4.6 (Session Lifecycle), §4.8 (SMTP), §8.2 (Session Privacy)

---

## Sprint 8 — Polish, Testing & Deployment

**Goal:** Everything works end-to-end in Docker. UI is polished. Edge cases handled.

### Deliverables
- [ ] End-to-end Docker Compose deployment tested
- [ ] Frontend responsive design verification
- [ ] i18n complete for EN, ES, FR
- [ ] Error handling: network failures, LLM timeouts, RAG errors
- [ ] Admin panel UX polish
- [ ] Documentation: `docs/INSTALL.md` (deployment guide)
- [ ] Performance check: Compare All mode with 10+ companies

### Acceptance Criteria
- [ ] Full flow works in Docker: backend + frontend + LLM (LM Studio or Ollama)
- [ ] Language switch works correctly for EN, ES, FR
- [ ] Chat handles LLM timeout gracefully (error message, not crash)
- [ ] File watcher handles rapid file changes without crashing
- [ ] Compare All with 10 companies responds within 30 seconds
- [ ] Admin can configure a new frontend from scratch and it works
- [ ] Session auto-destroy verified: files gone after configured hours
- [ ] INSTALL.md covers: Docker setup, OrbStack, LLM provider, first-time config

### Spec Sections Covered
- All sections (integration testing)

---

## Progress Tracking Rules

1. **Never mark a task `[x]` unless the acceptance criterion actually passes**
2. **If a criterion fails, document WHY in STATUS.md**
3. **If a criterion requires spec change, follow the DEVIATION PROTOCOL in CLAUDE.md**
4. **After each sprint, copy acceptance results to STATUS.md**
5. **CHANGELOG.md gets a new entry for every sprint**
