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

## Sprint 15 follow-ups — backlog (queued 2026-04-24)

Items surfaced during the RAG chunker audit. Each ~1 hour. Pick individually; none blocks anything else. Tracked here rather than in `docs/IDEAS.md` because they're specific code changes with clear scope, not open-ended ideas.

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

## Progress Tracking Rules

1. **Never mark a task `[x]` unless the acceptance criterion actually passes**
2. **If a criterion fails, document WHY in STATUS.md**
3. **If a criterion requires spec change, follow the DEVIATION PROTOCOL in CLAUDE.md**
4. **After each sprint, copy acceptance results to STATUS.md**
5. **CHANGELOG.md gets a new entry for every sprint**
