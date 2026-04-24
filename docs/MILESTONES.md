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
- [ ] `CBCopilot/src/backend/api/v1/admin/llm.py` — LLM config (3 slots × 3 provider types: `lm_studio`, `ollama`, `api`; + context-compression settings + two routing toggles; see SPEC §4.7)
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
- [ ] LLM config saves and health check returns status per slot (3 slots × 3 provider types)
- [ ] API provider flavor picker (anthropic / openai / openai_compatible) works; API key env var name is saved (the value itself is never stored)
- [ ] Context compression settings persist (`enabled`, `first_threshold`, `step_size`)
- [ ] Summary routing toggles persist (`document_summary_slot`, `user_summary_slot`), each accepting one of `inference` / `compressor` / `summariser`
- [ ] Endpoint field auto-fills when the admin switches a slot's provider (defaults come from backend config)
- [ ] SMTP config saves and test email sends successfully
- [ ] Company API: POST creates company, PATCH updates, DELETE removes
- [ ] Company list returned via `/admin/api/v1/frontends/{fid}/companies`
- [ ] Default prompts installed on first backend start

### Spec Sections Covered
- §4.1 (Prompt Assembler), §4.4 (Company Registry), §5.1 (Admin Layout - General Tab), §5.2 (Admin Auth)

---

## Sprint 4 — Admin Frontends Tab & 3-Tier Config

**Goal:** Admin can fully configure per-frontend and per-company settings from the Frontends tab. Config inheritance works correctly.

**Scope split:** Sprint 4 is delivered in two halves due to size. **4A** = registry + infrastructure + branding/session-settings/companies UI. **4B** = per-frontend prompts/RAG/orgs/LLM UI + resolvers.

### Deliverables
- [x] `CBCopilot/src/admin/src/FrontendsTab.tsx` — 4A: registry + branding + session settings + companies
- [x] `CBCopilot/src/backend/api/v1/admin/frontends.py` — 4A: Frontend CRUD + per-frontend branding + session settings + sidecar push
- [x] `CBCopilot/src/backend/services/frontend_registry.py` — 4A: adapted from HRDD, keyed by stable `frontend_id`
- [x] `CBCopilot/src/backend/services/polling_loop.py` — 4A: health-only poll (full queue polling stays Sprint 6)
- [x] `CBCopilot/src/backend/services/branding_store.py` — 4A
- [x] `CBCopilot/src/backend/services/session_settings_store.py` — 4A
- [x] Sidecar `/internal/branding` + `/internal/session-settings` push endpoints + `/internal/config` merge — 4A
- [x] Backend prompt resolution logic: company → frontend → global — 4B (winner-takes-all; compare_all.md skips company tier)
- [x] Backend RAG resolution logic: configurable modes per company — 4B (+ frontend `rag_standalone` gate)
- [x] Backend organizations resolution: global / own / combine per frontend — 4B
- [x] `services/resolvers.py` + preview endpoints — 4B
- [x] `services/orgs_override_store.py` + `services/llm_override_store.py` + `rag_standalone` in SessionSettings — 4B
- [x] `PromptsSection` + `RAGSection` refactored tier-aware; per-company content shows inside `CompanyManagementPanel` collapsible rows — 4B
- [x] `panels/PerFrontendOrgsPanel` + `panels/PerFrontendLLMPanel` — 4B

### Acceptance Criteria
- [x] Backend polls sidecar and detects it as online (moved from Sprint 1 per ADR-007) — 4A
- [x] Frontend dropdown shows all registered frontends — 4A
- [x] Selecting a frontend loads its current config — 4A
- [x] Can override branding per frontend — 4A
- [x] Can add/edit prompts per frontend (or toggle "inherit global") — 4B
- [x] Can upload RAG docs per frontend — 4B
- [x] Can manage company list (add, remove, rename, reorder, enable/disable) — 4A
- [x] Expanding a company shows prompt and RAG config — 4B
- [x] Company rag_mode dropdown works (own_only, inherit_frontend, inherit_all, combine_*) — 4A (persist) + 4B (resolver honours it)
- [x] Organizations list per frontend: toggle global / own / combine — 4B
- [x] Session settings configurable per frontend (auth, auto_close, auto_destroy, resume) — 4A
- [x] Feature toggles work (disclaimer, instructions, compare_all) — 4A
- [x] Prompt resolution: company prompt served when exists, falls back to frontend then global — 4B
- [x] RAG resolution: documents combined according to rag_mode setting — 4B (+ frontend standalone gate)

### Spec Sections Covered
- §2.4 (Three-Tier Config), §4.4 (Company Registry), §4.9 (Frontend Registry — expanded in 4A), §5.1 (Admin Layout - Frontends Tab)

---

## Sprint 5 — RAG Engine + File Watcher

**Goal:** RAG indexing works at all three tiers. File watcher detects changes on disk and triggers reindex automatically.

### Deliverables
- [x] `CBCopilot/src/backend/services/rag_service.py` — 3-tier RAG with lazy loading
- [x] `CBCopilot/src/backend/services/rag_watcher.py` — File watcher with debouncing
- [x] Session RAG (temporary per-session index for user uploads)
- [x] Document metadata support (country, language, document_type)
- [x] Compare All mode: load filtered RAGs by comparison scope (company-level country filter using auto-derived `country_tags`)

### Acceptance Criteria
- [x] Upload document to global RAG → indexed and queryable
- [x] Upload document to frontend RAG → indexed and queryable
- [x] Upload document to company RAG → indexed and queryable
- [x] Combine RAG both ticked (new model, replaces legacy "combine_all"): query returns chunks from company + frontend + global
- [x] Combine RAG all unticked (new model, replaces legacy "own_only"): query returns only company chunks
- [x] Place a file in a documents folder on disk → file watcher triggers reindex within 10 seconds
- [x] Delete a document from disk → file watcher triggers reindex
- [x] Bulk copy multiple files → single reindex after debounce period (5s, per-scope)
- [x] `.icloud` / `.DS_Store` / `._*` / `*.tmp` / `*.swp` / `~$*` ignored by watcher
- [x] Session RAG: user uploads document via sidecar `POST /internal/upload` → queryable via `session_rag.query(token, ...)`
- [x] Session RAG: `session_rag.destroy_session(token)` rmtrees the entire `/app/data/sessions/{token}/` tree
- [x] Compare All national mode: only returns scopes whose companies have the user's country in their derived `country_tags`
- [x] Compare All global mode: returns chunks from all enabled companies

### Spec Sections Covered
- §4.2 (RAG Service), §4.3 (RAG File Watcher), §3.3 (Compare All Mode)

---

## Sprint 6 — Chat Engine & Prompt Assembly

**Scope split:** Sprint 6 is delivered in two halves. **6A** = backend chat loop + sidecar SSE (curl-testable end-to-end). **6B** = React ChatShell + end-session user summary + real context compressor.

**Goal:** Full chat works: user sends message, backend processes with assembled prompt + RAG, streams response.

### Deliverables
- [x] `CBCopilot/src/backend/services/prompt_assembler.py` — 3-tier prompt assembly — 6A
- [x] `CBCopilot/src/backend/services/llm_provider.py` — 3 slots + fallback cascade (Daniel's D3 order) — 6A
- [x] `CBCopilot/src/backend/services/polling.py` — replaces Sprint 4A health-only loop — 6A
- [x] `CBCopilot/src/backend/services/guardrails.py` — HRDD patterns copied, CBC-themed responses — 6A
- [x] `CBCopilot/src/backend/services/context_compressor.py` — stub (real compression lands 6B) — 6A
- [x] `CBCopilot/src/backend/services/session_store.py` — disk-backed + cache, destroy_session rmtree — 6A
- [x] Sidecar `POST /internal/chat` + `POST /internal/stream/{token}/chunk` + `GET /internal/stream/{token}` — 6A
- [x] Initial query injection (survey query → first chat message) — 6A
- [x] `CBCopilot/src/frontend/src/components/ChatShell.tsx` — Chat UI with streaming — 6B
- [x] End-session UI + user summary via summariser slot — 6B
- [x] Real context compressor with progressive thresholds — 6B
- [x] Guardrails UI banner (warn ≥2, end-session at ≥5) — 6B
- [x] File upload chips in chat (uses Sprint 5 /internal/upload) — 6B

### Acceptance Criteria
- [x] User submits survey → backend polling picks it up → initial query injected as first user message — 6A (curl-verified end-to-end)
- [x] AI responds to initial query with streamed response — 6A (SSE tokens observed via `curl -N`)
- [x] Response uses appropriate RAG context (company-specific or Compare All) — 6A (amcor docs cited in the response: `amcor_au_2024.txt`)
- [x] Prompt assembly includes: core + guardrails + role prompt + context + knowledge + RAG — 6A (all 7 layers present in session.json, 12.5k chars)
- [x] React ChatShell renders streamed tokens end-to-end — 6B
- [x] End-session flow: user summary generated and displayed inline (with Copy button); SMTP send deferred to Sprint 7 — 6B
- [x] Guardrails fire on out-of-scope queries — verified with Sprint 7.5 test corpus (`docs/knowledge/guardrails-test-corpus.md`)
- [x] Context compression kicks in when conversation exceeds threshold — real compressor with progressive thresholds shipped 6B
- [x] Streaming works (tokens appear incrementally, not all at once) — verified in real deployment (Daniel, Sprint 9)
- [x] Chat history is preserved across messages in the session — `session_store` disk-backed + cache
- [x] Document upload during chat: file indexed into session RAG, available for subsequent queries — refactored to pull-inverse in Sprint 9

### Spec Sections Covered
- §4.1 (Prompt Assembler), §4.7 (LLM Provider), §4.10 (Guardrails), §3.5 (Document Upload)

---

## Sprint 7 — Sessions & Lifecycle

**Goal:** Session management works: creation, recovery, auto-close, auto-destroy, user summary.

### Deliverables
- [x] `CBCopilot/src/backend/services/session_store.py` — shipped in Sprint 6A; Sprint 7 adds `completed_at` field + attachments-aware messages.
- [x] `CBCopilot/src/backend/services/session_lifecycle.py` — 5-min scanner (auto-close + auto-destroy).
- [x] `CBCopilot/src/backend/api/v1/admin/sessions.py` — list + detail + flag + destroy.
- [x] `CBCopilot/src/backend/api/v1/auth.py` — real auth flow: Contacts allowlist + SMTP + dev_code fallback.
- [x] `CBCopilot/src/backend/api/v1/sessions/uploads.py` — `/recover` endpoint + admin-alert email on upload.
- [x] `CBCopilot/src/admin/src/SessionsTab.tsx` — list + detail drawer (HRDD columns adapted; role/mode/report indicators dropped per ADR-004/006).
- [x] `CBCopilot/src/backend/services/smtp_service.py` — pre-existing; wired into summary + admin alert + auth code paths.
- [x] User summary prompt — pre-existing `summary.md`; Sprint 6B wired the inline delivery; Sprint 7 adds the SMTP email on close.
- [x] Admin alert on user document upload — fires when `send_new_document_to_admin` is on + SMTP configured.
- [x] Registered users tab — pre-existing Contacts UI.

### Acceptance Criteria
- [x] Session created on survey submit, stored on disk (Sprint 6A).
- [x] Session recovery works via token within `session_resume_hours` (`GET /api/v1/sessions/{token}/recover` + SessionPage button).
- [x] Auto-close: session flips to `completed` after `auto_close_hours` idle.
- [x] Auto-destroy: rm-rf session tree after `auto_destroy_hours` post-close (when > 0).
- [x] Auto-destroy `= 0` keeps sessions indefinitely.
- [x] User summary generated at session close (Sprint 6B) + emailed when `survey.email` is set AND SMTP configured (Sprint 7).
- [x] Admin alert: email sent when user uploads document (fire-and-forget; gated by SMTP config + toggle).
- [x] Admin sessions tab: list + detail drawer with conversation, uploads, flag/destroy.
- [x] Registered Users tab: directory of authorized end-user emails (Contacts); the email-code auth flow now reads this as the allowlist.

### Spec Sections Covered
- §4.5 (Session Store), §4.6 (Session Lifecycle), §4.8 (SMTP), §8.2 (Session Privacy)

---

## Sprint 7.5 — Guardrails Review (between 7 and 8)

**Goal:** Dedicated pass on the runtime guardrails behaviour. Sprint 6A copied HRDD's hate-speech + prompt-injection regex tables verbatim; Sprint 6B surfaces them in the chat UI. This sprint reviews whether they fire correctly for CBC's domain (CBA research, not HRDD's labour-violation docs) and tunes thresholds.

### Deliverables
- [x] Trigger list reviewed — HRDD patterns kept; one CBC tweak: `fired` dropped from the "workers from X are [verb]" discriminatory pattern (false-positive risk in legitimate CBA discussions); `deported|removed|eliminated` kept where the intent signal is clearer.
- [x] Threshold review — `guardrail_warn_at=2` + `guardrail_max_triggers=5` exposed via `core/config.BackendConfig` and `deployment_backend.json`. Global only (D2).
- [x] Test corpus — `docs/knowledge/guardrails-test-corpus.md` (paste-ready triggering + non-triggering samples + recovery check + tuning notes).
- [x] Admin UI — read-only `GuardrailsSection` at the bottom of General tab shows patterns per category, current thresholds, and the localised responses.
- [x] SPEC §4.10 rewritten with the final rule set (two-layer model: prompt + runtime; enforcement pattern; thresholds).

### Acceptance Criteria
- [x] Every HRDD-inherited pattern reviewed (kept/modified); the one discriminatory-framing pattern was narrowed.
- [x] No new `fabrication` category (D1=B). Rationale: authenticated user population + prompt-layer `guardrails.md` already covers it.
- [x] Thresholds tested end-to-end: smoke with 5 triggered turns → `status=completed, flagged=true, violations=5, message_count=12` (1 survey + 5 user + 5 fixed responses + session-ended). UI banner fires at 2 via live-threshold fetch (fallback 2/5 when sidecar proxy fails).
- [x] Admin can inspect the active trigger list at General tab → Runtime guardrails (or `GET /admin/api/v1/guardrails`).

### Spec Sections Covered
- §4.10 (Guardrails)

---

## Sprint 8 — Polish, Testing & Deployment

**Goal:** Everything works end-to-end in Docker. UI is polished. Edge cases handled.

### Deliverables
- [x] End-to-end Docker Compose deployment tested — verified on real 2-host deployment (Mac Studio backend + M4 frontend over Tailscale) in Sprint 9
- [x] Frontend responsive design verification — core layouts work; RTL rendering wired via `RTL_LANGS` + `<html dir>`
- [x] i18n complete for EN, ES, FR — **exceeded**: all 31 HRDD-parity languages shipped in Sprint 8
- [x] Error handling: network failures, LLM timeouts, RAG errors — circuit breaker in `llm_provider`, SSE error events, RAG empty-scope fallback
- [x] Admin panel UX polish — SessionsTab redesign + guardrails viewer + branding translations UI
- [x] Documentation: `docs/INSTALL.md` (deployment guide) — rewritten in Sprint 9 with pull-inverse architecture + Portainer flows
- [ ] Performance check: Compare All mode with 10+ companies — **not measured yet** (Daniel's env QA when he loads the full corpus)

### Acceptance Criteria
- [x] Full flow works in Docker: backend + frontend + LLM (LM Studio or Ollama) — Daniel running live on Ollama
- [x] Language switch works correctly for EN, ES, FR — plus 28 more languages
- [x] Chat handles LLM timeout gracefully (error message, not crash) — circuit breaker + SSE error event
- [x] File watcher handles rapid file changes without crashing — 5s debounce per-scope
- [ ] Compare All with 10 companies responds within 30 seconds — **not measured**
- [x] Admin can configure a new frontend from scratch and it works — Daniel did exactly this with Amcor-Lezo in Sprint 9
- [ ] Session auto-destroy verified: files gone after configured hours — **not measured in live deployment** (code path verified in Sprint 7)
- [x] INSTALL.md covers: Docker setup, OrbStack, LLM provider, first-time config — plus Portainer Repository + Web-editor modes + cross-host deployment

### Spec Sections Covered
- All sections (integration testing)

---

## Sprint 9 — RAG Overhaul + HRDD-parity Architecture Hardening

**Goal (reactive):** First real deployment across two hosts exposed both (a) an over-coupling to a shared Docker network that broke cross-host, and (b) retrieval quality gaps on real CBA content. This sprint wasn't in the original plan — it's the response to measured findings from early real use.

### Deliverables
- [x] Drop `cbc-net` from both compose files; each stack self-contained on its Docker host
- [x] `CBC_BACKEND_URL` env var on frontend compose for the single remaining sidecar→backend call (auth)
- [x] Pull-inverse refactor: guardrails thresholds (push per poll)
- [x] Pull-inverse refactor: session recovery (queue → poll → push-back)
- [x] Pull-inverse refactor: user uploads (local stash + polled ingest)
- [x] Pull-inverse refactor: company list (push per poll, invalidate on admin CRUD)
- [x] Compare All separated from company_registry — sidecar synthesises at list time
- [x] CompanySelectPage: branded blue buttons with Compare All accented
- [x] RAG: markdown-aware chunker for `.md`, 1024-token chunks, hybrid BM25+dense retrieval
- [x] RAG: swap embedder `all-MiniLM-L6-v2` → `BAAI/bge-m3` (multilingual, 1024-dim)
- [x] RAG: cross-encoder reranker `BAAI/bge-reranker-v2-m3` (fetch-30 → rerank-to-8)
- [x] RAG: Contextual Retrieval (Anthropic Sept-2024) as runtime toggle, off by default
- [x] Admin UI: new `RAGPipelineSection` on General tab — read-only embedder/reranker info + CR toggle with reindex warning
- [x] Dockerfile.backend: pre-download BGE-M3 + bge-reranker-v2-m3 + MiniLM fallback; add `build-essential` for C-extension deps
- [x] `docs/INSTALL.md` rewrite for pull-inverse + Portainer + cross-host
- [x] `docs/IDEAS.md`: capture ChromaDB migration as the next vector-store upgrade

### Acceptance Criteria
- [x] Cross-host deployment works (Mac Studio backend + M4 frontend over Tailscale) — Daniel's live setup
- [x] Frontend stacks deploy from Portainer Repository mode with no pre-existing Docker network
- [x] Multiple frontend stacks on one host don't collide (stack-name prefix handles container + volume names)
- [x] Salary tables surface on queries against Amcor-Lezo CBA — "funciona mucho mejor" (Daniel, 2026-04-21)
- [x] Backend build succeeds on fresh `python:3.11-slim` host without Docker build cache
- [x] Contextual Retrieval toggle flips runtime config + reindexes every scope; rolls back on reindex failure
- [ ] Real-use recall metrics measured — **deferred** pending larger corpus

### Spec Sections Covered
- §2.1 (pull-inverse restored), §2.2 (Pull-Inverse), §4.2 (RAG Service), §4.3 (RAG File Watcher), §4.4 (Company Registry), §9 (Deployment)

---

## V1 Completion Status (as of 2026-04-21)

All originally-planned Sprints 1–8 plus the reactive Sprint 9 are closed. Feature development for CBC v1 is **effectively complete**. Three items remain as operational QA / measurement gates rather than feature work:

1. **Compare All 10+ companies perf check** (MILESTONES §Sprint 8) — needs a full corpus loaded.
2. **Session auto-destroy verified in live deployment** (MILESTONES §Sprint 8) — needs a 24-72h run with `auto_destroy_hours > 0` and a timestamp check.
3. **Native-speaker translation QA** for the 31-language bundle (Sprint 8) — flagged in SPEC §7.1 as post-v1 polish.

Post-v1 enhancements captured in `docs/IDEAS.md` (ChromaDB migration, etc.) are decision-gated on measurement, not required for v1 shipping.

---

## Sprint 15 follow-ups — backlog (queued 2026-04-24, reviewed after Sprint 16 planning 2026-04-24)

Items surfaced during the RAG chunker audit. Each ~1 hour. Pick individually; none blocks anything else. Tracked here rather than in `docs/IDEAS.md` because they're specific code changes with clear scope, not open-ended ideas.

**Review note (2026-04-24):** with Sprint 16 (Structured Table Pipeline) replacing CR's primary role for tabular data, CR-specific optimisations (M, N) drop in priority. They stay useful **if** CR remains active for prose-chunk enrichment after Sprint 16; if CR gets deactivated entirely, they become moot. Mark ⚠︎ = re-evaluate after Sprint 16 ships.

### A — Startup scan for oversized legacy chunks (diagnostic WARNING)
On backend startup, walk each Chroma scope and emit `WARNING: Scope X has pre-Sprint-15 oversized chunks, reindex recommended` if any chunk exceeds 30 000 chars. Non-intrusive, no auto-action. ~15 lines in `rag_service.py`, hooked from `main.py` lifespan.

### B — Admin-panel "reindex needed" banner
When admin opens General → RAG, surface a red banner per scope that has any oversized chunk, with a one-click Reindex button next to it. ~30 lines frontend + ~10 backend (reuses A's detection). Lives alongside the existing Sprint 5 reindex UX.

### C — `GET /admin/api/v1/rag/diagnostics` endpoint
New admin read-only endpoint returning per-scope chunk count, mean/max chunk chars, embedding-truncation risk flag. Drives diagnostic views or external monitoring. ~20 lines.

### D — Session RAG force-injection size cap
`session_rag.get_chunks_for_files` currently injects EVERY chunk of user-attached files (intended: "the model can't miss the file"). With correct chunking a 500-page PDF upload produces ~500 chunks all force-injected. Add a `max_forced_chars` cap (≈20 000) with a "truncated" note to the model. ~15 lines.

### E — BGE-M3 truncation config guard
If admin bumps `rag_chunk_size` above 8 192 tokens in `deployment_backend.json`, BGE-M3 silently truncates embeddings. Add a startup validation: WARN if `rag_chunk_size × 4` (chars-per-token heuristic) > 32 768. ~5 lines in `core/config.py`.

### F — Prompt stability across turns (architectural)
Every turn re-runs `prompt_assembler.assemble()` which re-runs RAG retrieval. If related questions retrieve different chunks, the system prompt differs turn-to-turn and Ollama's prefix cache gets partial miss. Pre-existing, not introduced by Sprint 11-15. Post-Sprint-15 the impact is much smaller (chunks are small). Investigate only if re-question TTFT remains >15 s in production.

### G — Preload CBC's inference model in Ollama
Cold-load of qwen3.6:35b at NP=4 costs ~30-45 s per first request. Preloading via `~/.ollama/preload.conf` on the Mac Studio eliminates it at ~45 GB always-resident RAM. Ops-only change (modify the plist Daniel set up in Sprint 14 A). No code changes.

### H — BM25 retriever cache per scope
Currently `_hybrid_retrieve` rebuilt the BM25 index from scratch on every query. Empirically validated to be only ~20 ms per rebuild on the 111-chunk Amcor scope — much smaller win than the 6-7 s the log-progress-bar first suggested (those turned out to be sentence-transformer encodings, not BM25). Still worth caching for code cleanliness and to scale cleanly with 200 CBAs. Fix: cache the BM25 retriever keyed by scope_key, invalidate on reindex. **Landed as part of Sprint 15's Phase 2 commit alongside the glossary name fix.**

### K — ✅ Persist admin-editable backend_config fields across container restart — CLOSED in Sprint 15 phase 4 (2026-04-24)

Resolved. New `runtime_overrides_store.py` + `/app/data/runtime_overrides.json` sibling of `llm_config.json`. Main.py lifespan calls `apply_startup_overrides()` before any service reads backend_config. Three tracked fields: `rag_chunk_size`, `rag_embedding_model`, `rag_contextual_enabled`. Admin endpoints that flip them now `save_override(...)` so the next restart reads the persisted value instead of the deployment JSON default. Extensible via `_TRACKED_FIELDS` — add a new entry there when surfacing a new admin-editable backend_config setting.

### L — ✅ Route Contextual Retrieval to a smaller slot — CLOSED in Sprint 15 phase 5 (2026-04-24)

Resolved. Added `contextual_retrieval_slot: SlotName = "compressor"` to `RoutingToggles` alongside the existing `document_summary_slot` / `user_summary_slot`. `_generate_chunk_context` now reads the toggle on every call (flip takes effect without restart). Admin UI extended the Summary routing block from a 2-column grid to 3, with EN+ES copy explaining the 10× cost difference. Default = compressor (e.g. qwen3.5-9b on Ollama), ~2-4 s/chunk; admin can switch to summariser (qwen3.5-122b) if the smaller model produces noticeably worse context sentences. For a 100-CBA reindex this cuts CR from ~35 h to ~3-4 h. Future work on the table-extraction pipeline (Sprint 16 plan) will reuse the same slot.

### M — ⚠︎ Content-hash cache for Contextual Retrieval (re-evaluate after Sprint 16)
When re-ingesting an already-enriched scope whose chunks are mostly unchanged, don't re-call the LLM for chunks whose content hash matches. Cache keyed on `sha256(chunk.text)` → stored context sentence. First ingest pays the full CR cost; subsequent ingests only pay for chunks whose text actually changed. For a deployment that curates 100 CBAs with occasional edits, this turns a 35-hour reindex into ~minutes. ~30 lines, new JSON file at `/app/data/cr_cache.json` or similar.

**Post-Sprint-16 relevance:** only if CR stays on after Sprint 16's Table Pipeline handles tabular data. If CR becomes optional/off, this item is moot.

### N — ⚠︎ Parallelise Contextual Retrieval calls (re-evaluate after Sprint 16)
`_generate_chunk_context` runs through a single-worker ThreadPoolExecutor (from the Sprint 15 phase 4 asyncio fix). If the summariser runtime has parallel slots available (Ollama NUM_PARALLEL=4, LM Studio Parallel=4), bumping the ThreadPool to 4 workers gives ~4× speedup on the CR pass. Requires care that the summariser slot's runtime actually has the parallel capacity. 1 line change + a config knob.

**Post-Sprint-16 relevance:** only if CR stays on after Sprint 16.

### Q — Metadata prepending to chunks (CR-lite, no LLM)
Prepend `file_name` + `header_path` + tier info to each chunk's text BEFORE embedding, so BGE-M3 captures document context in the vector itself. For example a chunk from `CBA—Amcor—Lezo.md` inside section "Art. 23 Retribuciones" embeds as `[doc: CBA—Amcor—Lezo; section: Art. 23 Retribuciones]\n\n<chunk text>` instead of just the raw chunk. Zero LLM calls, ~15 lines. Complements Sprint 16 tables for prose-chunk queries like "what does Amcor say about vacations?" where the section name is a strong semantic signal. Still valuable after Sprint 16.

### O — UX polish for slow reindex operations
Progress feedback during long-running reindexes (CR=on on big corpora can be 30+ min) is limited to OrbStack logs. Surface progress to the admin UI via a server-sent-events or polling endpoint (e.g. `GET /admin/api/v1/rag/reindex-status`) so the UI shows "12/44 chunks processed" instead of a blank spinner. Not urgent but noticeable on large deployments.

### J — Unify save-feedback pattern across admin sections
Daniel flagged (2026-04-24): across CBC's admin panel, Save buttons don't give consistent feedback. LLMSection / GuardrailsSection / BrandingSection / SMTPSection / RAGSection etc. variously put `saveStatus` as tiny gray text in the header, or no feedback at all. HRDD's pattern (`HRDDHelper/src/admin/src/LLMTab.tsx`) is better: inline next to the button, button label switches to `Saving…`, green `✓ Saved` pill appears for ~3 s post-success.

Sprint 15 phase 3 ported this pattern into **`RAGPipelineSection.tsx` only** because that was the section being built. Backlog J: extend the same pattern to every other CBC admin section. ~5 lines per section (`saving` state, `saveSuccess` state, button label ternary, green pill JSX). Low-risk; pure UX polish. ~30 mins total work across all sections.

### I — Embedding model drift + admin-editable RAG settings — CLOSED in Sprint 15 phase 3 (2026-04-24)

**Resolved.** Commit path:
- `deployment_backend.json` updated: `rag_embedding_model` → `BAAI/bge-m3`, `rag_chunk_size` → `1024` (aligns the JSON with Sprint 9's code defaults).
- `chunk_size` (slider: 512 / 1024 / 1536 / 2048) and `embedding_model` (dropdown: BGE-M3 / MiniLM-L6-v2) are now editable from the admin RAG Pipeline section.
- New admin endpoints: `PATCH /admin/api/v1/rag/settings` (in-memory update), `POST /admin/api/v1/rag/wipe-and-reindex-all` (nuke Chroma + every cache + re-ingest every scope).
- Destacado red "Wipe & Reindex All" button inside the RAG Pipeline section with confirm modal.
- `RAGSection.onReindex` at global tier now cascades across every scope (was single-scope; cascading makes sense because global-tier settings — embedder, chunk size, CR — apply to all scopes).
- EN + ES i18n keys; other 13 languages fall back to EN per the Sprint 12 Phase B partial-translation pattern.

**Operational note for any future deployment:** after applying these settings changes, the admin MUST click "Wipe & Reindex All" once to rebuild indices against the new embedder + chunk size. Without the wipe, existing chunks remain at the old dimensions and live queries will fail or degrade.

---

---

## Sprint 16 — Structured Table Pipeline (planned 2026-04-24, not started)

**Goal:** Tabular data (salary schedules, shift tables, etc.) becomes a first-class citizen in CBC's retrieval. Extracted to CSV at ingest, indexed as semantic "cards", and injected verbatim into the prompt when queries are table-relevant. CR becomes optional — tables replace its primary use case (numeric retrieval blindspot).

### Rationale

CR pays an LLM cost per chunk (~35 h for 100 CBAs on a 122B summariser, ~3-4 h on a 9B compressor after Sprint 15 phase 5). It enriches chunk embeddings with a context sentence but chunks containing tables still embed as "numbers + table structure" — inherently weak for semantic search on tabular queries. The actual solution is to treat tables as structured data: extract them, store them as CSV, retrieve them via a separate card-based index, and inject them intact. Compare All mode is especially improved — cross-company salary comparisons land as two CSVs side-by-side instead of scattered chunks.

Accepted trade-off: **scanned PDFs** (image-only) will extract nothing or garbage. That's the reality of OCR-less pipelines. Those documents still ingest as unstructured RAG (the .md/.pdf text passes through the regular chunker) so the chat works, just without table benefits.

### Deliverables

**Backend — new service `services/table_extractor.py`:**
- `extract_markdown_tables(md_text, doc_name) → list[TableSpec]` — regex-based, detects `|...|...|` pipe-table blocks, groups contiguous rows, captures the nearest preceding `#`/`##`/`###` heading as source_location. No LLM, fast.
- `extract_pdf_tables(pdf_path, doc_name) → list[TableSpec]` — `pdfplumber.open().pages[].extract_tables()`. Works for vector PDFs. Logs WARN and returns `[]` for image-only PDFs. `pdfplumber` added to `requirements.txt` and pre-downloaded in `Dockerfile.backend`.
- `TableSpec` dataclass: `id` (sha1 of content), `name` (auto from heading), `description` (auto from heading + nearby prose), `csv_text`, `source_location` (heading or page#), `columns` (list), `row_count`, `doc_name`.
- `save_tables_for_doc(scope_key, doc_name, tables)` — writes `/app/data/campaigns/{fid}/companies/{slug}/tables/{doc_stem}/{table_id}.csv` + `manifest.json` (list of TableCard).
- `load_manifest(scope_key, doc_name) → list[TableCard]` — reads the manifest, returns card metadata for query-time use.
- `load_csv(scope_key, doc_name, table_id) → str` — reads the CSV file content (for injection into the prompt).

**Backend — `services/rag_service.py` extensions:**
- New module-level `_tables_collection: Any | None` (separate Chroma collection `cbc_tables` for card embeddings — distinct from `cbc_chunks`).
- `_get_tables_collection()` with same `allow_reset=True` pattern as `_get_chroma_collection()`.
- `_build_index(scope_key)` extended: for each ingested document, call `table_extractor.extract_*`, save CSVs + manifest, optionally call compressor LLM to enrich each card's `name`/`description` (one call per table, reuses `_generate_chunk_context` plumbing and the `contextual_retrieval_slot` toggle). Embed card text (`name + description + source_location`) into `cbc_tables`.
- `query_tables(scope_keys, query_text, top_k=2) → list[TableHit]` — parallel to `query_scopes`. Queries `cbc_tables` with scope filter, returns top-K cards with their CSV content loaded from disk.
- `wipe_chroma_and_reindex_all()` extended to also wipe `cbc_tables` (via the shared Chroma client reset).
- `_delete_scope(scope_key)` extended to also delete table cards for that scope.

**Backend — `services/prompt_assembler.py` integration:**
- In `_resolve_rag`, after retrieving prose chunks, also call `rag_service.query_tables(scope_keys, query_text, top_k=2)`.
- New section in the assembled prompt: `## Relevant tables` containing each matched table's `name`, `description`, `source_location`, and full CSV content.
- Token budget: per-table cap of ~6 000 chars (roughly 1 500 tokens); if CSV exceeds, clip with a `[... table truncated — see source document ...]` note.
- New layer key `"tables"` in the existing `AssembledPrompt.layers` dict; per-section size breakdown log already covers it automatically.
- `sources` SSE event extended: each hit includes a `table_id` field so the sidepanel can cite the table specifically.

**Backend — `services/rag_watcher.py`:**
- On detected change to a document file, re-run table extraction for that doc + embed new cards into `cbc_tables` alongside the existing chunk reindex.

**Admin API — `api/v1/admin/tables.py` (new router):**
- `GET /admin/api/v1/tables` (query params `frontend_id`, `company_slug`) → returns per-scope list of extracted tables (name, description, row_count, source_location, doc_name) as JSON for the admin UI.
- `POST /admin/api/v1/tables/reextract` (query params `frontend_id`, `company_slug`) → force re-extraction for all docs in that scope. Useful when the extractor code changes.
- `GET /admin/api/v1/tables/{scope}/{doc}/{table_id}.csv` → returns the CSV file for download/preview.

**Admin UI — `src/admin/src/sections/TablesSection.tsx` (new section):**
- Per-scope list of extracted tables.
- Preview first 5 rows of each table (inline).
- "Re-extract tables" button per scope.
- Inline indicator of extraction quality for PDFs (e.g. "0 tables extracted — document may be scanned").

**Frontend — `src/frontend/src/components/ChatShell.tsx`:**
- Render the new `table_id` citations inside the existing `CitationsPanel` alongside prose sources. Clickable chip that previews the table CSV.

**Docs:**
- `docs/SPEC.md` §4.12 new section: Table Extraction Pipeline (contract, formats, limits).
- `docs/architecture/decisions.md` ADR-009: "Structured Table Pipeline as complement to vector RAG" — rationale, trade-offs, scanned-PDF acceptance.
- `docs/CHANGELOG.md`: sprint entry.
- `docs/architecture/ARCHITECTURE.md`: if Sprint 17 has shipped before 16, update it alongside this sprint. If 16 ships first, the changes queue for whenever 17 lands. Entries to add: new `table_extractor` service, new `cbc_tables` Chroma collection, new storage layout `tables/{doc_stem}/`, new admin UI location `Admin → General → Tables`, new data flow "table query".

### Acceptance Criteria

- [ ] Ingesting `CBA—Amcor—Lezo.md` produces at least 2 CSVs under `/app/data/campaigns/g-p1/companies/amcor/tables/CBA—Amcor—Lezo/` (daily + monthly salary tables from ANEXO I).
- [ ] `manifest.json` lists those tables with non-empty `name` / `description`.
- [ ] Card embeddings present in `cbc_tables` Chroma collection (verified via `sqlite3` query).
- [ ] Query "salario medio en el convenio" → `prompt_assembler` includes the daily-salary CSV verbatim under `## Relevant tables`.
- [ ] The chat response correctly calculates an average from the injected numbers (or explicitly states the weighting limitation from a simple mean).
- [ ] PDF CBA upload → tables extracted via pdfplumber when the PDF is vector; `[]` with WARN log when scanned.
- [ ] File watcher re-extracts tables when a document file changes on disk.
- [ ] Compare All mode with two companies → both companies' top tables appear in prompt when the query is tabular.
- [ ] Admin UI `TablesSection` shows per-scope tables with row preview and re-extract button.
- [ ] CR toggle OFF + table pipeline active → salary-table queries succeed (validates tables replace CR for tabular cases).
- [ ] `_build_index` log gains a `tables_extracted: N` counter per document.

### Open questions (decide before execution)

- **LLM-enriched cards vs raw heading:** default to NO LLM enrichment (use the heading literal as card name + nearby prose as description). Admin can flip to LLM-enriched via a new `table_card_enrichment` toggle. Saves the ~1 call per table cost for deployments that don't need semantic polish.
- **Per-table size cap in prompt:** 6 000 chars per table feels right for CBAs (salary tables of 30 rows × 4 cols fit). Tune based on real tables.
- **Scanned-PDF detection:** should the backend try OCR fallback via Tesseract? **Decision: NO** for this sprint. Scanned CBAs are accepted as low-fidelity. Admin can convert externally.

### Estimated scope

- ~500 lines backend Python (extractor, service wiring, admin API)
- ~250 lines admin TSX (TablesSection + API client + i18n)
- ~100 lines frontend (citation integration)
- 1 new dependency (`pdfplumber`)
- Dockerfile change (pre-download `pdfplumber` + `pdfminer.six`)
- 2-3 days of focused work

---

## Sprint 17 — Living Architecture Documentation (planned 2026-04-24, not started)

**Goal:** One document — `docs/architecture/ARCHITECTURE.md` — describes CBC's current architecture in-place: services, data flows, storage layout, failure modes, runtime controls. Read by every Claude Code session at sprint start. Maintained automatically via the `/sprint` skill workflow so it never drifts.

### Rationale

Every multi-turn Claude session currently rediscovers the architecture by reading source code. That's thousands of tokens per session spent recovering state that was known last time. A single living document — authored at Sprint 17 and maintained after every architectural change — keeps the context window efficient and the architecture legible.

Alternative considered: dedicated drift-detection sub-agent. Rejected for now as overkill for a 1-developer repo with high Claude-Code involvement. If drift accumulates despite the sprint-workflow discipline, add the sub-agent in a future sprint.

### Deliverables

**New file — `docs/architecture/ARCHITECTURE.md`:**

Authored from the current post-Sprint-15 state. Suggested sections:

**Format requirement (Daniel, 2026-04-24):** the doc is dual-use — read by Claude AND by Daniel himself without Claude. Every section that describes a behaviour controlled from the admin panel MUST cite the exact UI location (tab + section name, e.g. "Admin → General → LLM → Summary routing → Contextual Retrieval dropdown"). Every section that describes code MUST cite the file path. This lets the doc serve as the single source of truth: an operator wanting to change behaviour reads the "where is this UI control" link, a developer wanting to trace logic reads the "where is this code" link. No need to guess either end.

1. **System overview** — 2-paragraph description of what CBC is, + a textual architecture diagram (services + storage + external dependencies).
2. **Services layer** — one entry per `src/backend/services/*.py` file: responsibility, who calls it, what it exports, what state it owns. Cite file path: `CBCopilot/src/backend/services/{name}.py`.
3. **Data flows** — sequence descriptions for:
   - Chat turn: user → sidecar queue → backend polling → prompt_assembler → llm_provider → SSE stream → browser
   - RAG query: query text → embedder → hybrid (vector + BM25) → reranker → chunks
   - Table query (post-Sprint 16): query → card lookup → CSV injection
   - Document ingest: file on disk → chunker → (optional CR) → table extractor → Chroma (chunks + cards)
   - Compare All: multi-scope retrieval + combined tables
   - Session lifecycle: create → store → compress if needed → close → destroy
4. **Storage layout** — every directory under `/app/data/`, what lives there, read/write patterns. Format: absolute path + "written by: {service}" + "read by: {services}".
5. **Runtime control** — table mapping each admin-editable knob to (a) its admin UI location, (b) the persistence file, (c) the backend service that reads it. Example row:
   - `rag_contextual_enabled`
   - UI: **Admin → General → RAG Pipeline → Contextual Retrieval toggle**
   - Persisted at: `/app/data/runtime_overrides.json`
   - Read by: `rag_service._build_index` on every ingest
   - Default: `false`
   - Cost of flipping: triggers full reindex of every scope.
6. **Failure modes** — circuit breaker, inactivity timeout, cancel flow, wipe recovery, partial-reindex detection. Each: trigger condition + recovery path + related admin UI (e.g. "Wipe & Reindex All" button location).
7. **Dependencies and integrations** — Ollama, LM Studio, Chroma, BGE-M3, cross-encoder reranker, pdfplumber (post-Sprint-16). For each: where it's configured (deployment_backend.json, admin UI, or Dockerfile), version pinned, graceful-degradation behaviour if unavailable.
8. **Architectural invariants** — things that MUST be true (e.g. "every chunk embedding is <8192 tokens", "session_store writes are atomic", "polling is fire-and-forget, not blocking"). Cite the code location where each invariant is enforced.
9. **Admin UI map** — inverse of §5: a walk-through of the admin panel from Daniel's POV. For each tab → section, describe what it controls and which backend service / config file / service method is wired to it. Allows Daniel to open the admin, see a toggle, and immediately know "clicking this changes X in file Y which affects service Z". Frontend paths for the curious: `CBCopilot/src/admin/src/sections/*.tsx`, `CBCopilot/src/admin/src/panels/*.tsx`.
10. **Pointers** — one-line pointers to SPEC.md, MILESTONES.md, ADRs, hrdd-helper-patterns.md for specific deep-dives.

**Update — `CLAUDE.md`:**

Add `docs/architecture/ARCHITECTURE.md` to the "Key Documents — READ ORDER" block as the FIRST read after MILESTONES/STATUS. Rationale: before any sprint work, know the system as it stands.

**Update — `.claude/commands/sprint.md` (the `/sprint` skill):**

In the Finalizing phase, add:
> **Update `docs/architecture/ARCHITECTURE.md`** if this sprint changed any of:
> - Service responsibilities or cross-service contracts
> - Data flow paths (new stages, removed stages, reordered)
> - Storage layout (new files/directories, schema changes)
> - Admin-editable runtime controls (added, removed, defaults changed)
> - External dependencies (added/removed/version-major-bumped)
> - Architectural invariants (new constraints, relaxed constraints)
>
> If none of the above changed, skip. Document the decision either way in the sprint's CHANGELOG entry.

**Optional — `docs/knowledge/architecture-drift-audit.md`:**

Brief note describing the drift-detection approach we're deferring: after N sprints, if ARCHITECTURE.md accuracy degrades, add a sub-agent that diffs the doc against the current code state and surfaces gaps. This file captures the decision so future me doesn't re-debate it.

### Acceptance Criteria

- [ ] `docs/architecture/ARCHITECTURE.md` exists and covers all 10 sections above.
- [ ] Every section that describes admin-controlled behaviour cites the exact UI path (`Admin → tab → section → control name`).
- [ ] Every section that describes code cites the file path.
- [ ] Section 9 (Admin UI map) walks the admin panel tab-by-tab and links each control to backend file + service + persistence file.
- [ ] `CLAUDE.md` lists it in "Key Documents — READ ORDER" as required pre-sprint reading.
- [ ] `/sprint` skill's Finalizing phase explicitly calls out the ARCHITECTURE.md update step.
- [ ] The next sprint after 17 (whichever it is) follows the new flow: arch doc is updated (or a "no arch changes this sprint" note lands in CHANGELOG).
- [ ] A fresh Claude session reading only CLAUDE.md + ARCHITECTURE.md can answer questions like "where is the compressor LLM slot used?" or "what triggers a Chroma wipe?" without reading source.
- [ ] Daniel can use the same document as his operator manual — finding a UI toggle and reading what it does without opening VS Code.

### Estimated scope

- 1 authoring session for ARCHITECTURE.md (~600-800 lines, one sitting, mostly writing)
- 3 lines in CLAUDE.md
- ~10 lines in the `/sprint` skill
- Half a day total

---

## Progress Tracking Rules

1. **Never mark a task `[x]` unless the acceptance criterion actually passes**
2. **If a criterion fails, document WHY in STATUS.md**
3. **If a criterion requires spec change, follow the DEVIATION PROTOCOL in CLAUDE.md**
4. **After each sprint, copy acceptance results to STATUS.md**
5. **CHANGELOG.md gets a new entry for every sprint**
