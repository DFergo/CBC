# CBC — Project Status

**Current Sprint:** 4 — Admin Frontends Tab & 3-Tier Config
**Last Updated:** 2026-04-18

---

## Sprint 3 — COMPLETE

**Decisions locked at sprint start (all confirmed by Daniel):**
- D1=A — RAG stub (files on disk + count/size stats). Real indexing lands Sprint 5.
- D2=A — LLM health check real: `lm_studio` / `ollama` hit `/v1/models` or `/api/tags`; `api` verifies env var + pings endpoint with auth header.
- D3=A — SMTP test send real via `aiosmtplib`.
- D4=A — Sidecar untouched. Backend owns companies internally. Sprint 4 adds backend→sidecar push.
- D5 — Claude wrote default prompts; Daniel refines later via admin.

### Deliverables
- [x] `services/_paths.py` (layout + atomic write helper)
- [x] `services/company_registry.py`
- [x] `services/prompt_store.py` (3-tier aware)
- [x] `services/knowledge_store.py`
- [x] `services/rag_store.py` (stub)
- [x] `services/llm_config_store.py` (2 slots × 3 providers, real health)
- [x] `services/smtp_service.py` (with `send_test`)
- [x] `api/v1/admin/companies.py`
- [x] `api/v1/admin/prompts.py` (global + per-frontend + per-company routes; UI wires global only)
- [x] `api/v1/admin/rag.py`
- [x] `api/v1/admin/knowledge.py`
- [x] `api/v1/admin/llm.py`
- [x] `api/v1/admin/smtp.py`
- [x] Default prompts: core / guardrails / cba_advisor / compare_all / context_template (CBC-specific)
- [x] Default knowledge: glossary (10 terms, EN+ES+FR+DE+PT translations) + orgs (7 entries)
- [x] `main.py` wires 6 routers + `ensure_defaults()` lifespan
- [x] `requirements.txt` adds `aiosmtplib`
- [x] Admin `Dashboard.tsx` (tab nav)
- [x] Admin `GeneralTab.tsx` + 7 sub-sections
- [x] Admin `FrontendsTab.tsx` (placeholder for Sprint 4)
- [x] Admin `api.ts` extended

### Acceptance (verified via curl on `localhost:8100`)
- [x] Admin General tab loads
- [x] Prompts list/read/save works (5 defaults installed)
- [x] RAG upload + delete + stats + reindex-stub works
- [x] Glossary + Organizations CRUD works (10 + 7 defaults)
- [x] LLM config saves; health per slot for all 3 provider types
- [x] API provider: flavor picker persists; `api_key_env` stored as name, health reports when env var missing
- [x] SMTP config saves with password redaction
- [x] Company API: CRUD + duplicate-slug validation
- [x] Defaults installed on first backend start (container logs + file listing)

### Deviations from milestone
- Branding defaults is a placeholder — Sprint 4 builds it alongside per-frontend override UI
- Admin UI for per-frontend/per-company prompts/RAG lives in Sprint 4 (backend routes already present)
- "Registered users" skipped — no users yet (auth is a Sprint 2 stub); lands in Sprint 7
- SMTP outgoing send not verified end-to-end (no SMTP creds provided in smoke test)

---

## Sprint 2 — COMPLETE

### Deliverables
- [x] `CBCopilot/src/frontend/src/App.tsx` (router rewrite)
- [x] `CBCopilot/src/frontend/src/types.ts` (Phase, LangCode, Company, SurveyData, ComparisonScope)
- [x] `CBCopilot/src/frontend/src/token.ts` (XXXX-NNNN generator — adapted from HRDD)
- [x] `CBCopilot/src/frontend/src/i18n.ts` (EN only for Sprint 2; Sprint 8 adds ES/FR/DE/PT)
- [x] `CBCopilot/src/frontend/src/index.css` (+ tailwind directives)
- [x] `CBCopilot/src/frontend/src/components/LanguageSelector.tsx`
- [x] `CBCopilot/src/frontend/src/components/DisclaimerPage.tsx`
- [x] `CBCopilot/src/frontend/src/components/SessionPage.tsx`
- [x] `CBCopilot/src/frontend/src/components/AuthPage.tsx` (with dev banner showing 6-digit code)
- [x] `CBCopilot/src/frontend/src/components/InstructionsPage.tsx`
- [x] `CBCopilot/src/frontend/src/components/CompanySelectPage.tsx` (NEW)
- [x] `CBCopilot/src/frontend/src/components/SurveyPage.tsx` (CBC fields + comparison_scope for Compare All)
- [x] `CBCopilot/src/frontend/package.json`, `tailwind.config.js`, `postcss.config.js`
- [x] `CBCopilot/src/frontend/sidecar/main.py` — added /internal/companies, auth stubs, /internal/queue
- [x] `CBCopilot/src/frontend/sidecar/companies.json` (stub; Sprint 3 moves it to backend)
- [x] `CBCopilot/Dockerfile.frontend` — copies companies.json into container
- [x] CompanySelectPage: country tags removed from buttons (data stays in model for Sprint 5 filtering)
- [x] `docs/IDEAS.md` — backlog of captured-but-not-scoped feature ideas
- [x] `.claude/commands/idea.md` — `/idea` slash command for logging into IDEAS.md

### Acceptance Criteria
- [x] Language selection page shows and stores choice (EN only for now)
- [x] Disclaimer page displays and "Accept" advances
- [x] Session token generated and stored in browser state
- [x] Auth page sends email verification code (dev banner shows it)
- [x] Auth is skipped when auth_required = false (verified by toggling config)
- [x] Instructions page displays and advances
- [x] Company selection page shows Compare All + 3 sample companies
- [x] Selecting a company advances to survey
- [x] Survey page shows all fields per §3.4
- [x] Survey submit stores data in sidecar (`/internal/queue` + `dequeue_messages` smoke-tested)
- [x] Placeholder page shows after submit
- [x] Compare All selection shows comparison scope field in survey
- [x] Full page flow works in Docker (`localhost:8190`)

### Deviations from milestone
- Auth is a sidecar-only stub returning `dev_code` inline (per user decision D1 = A). Real backend-mediated SMTP lands Sprint 7.
- Document upload shows a file input but does not send the file (per user decision D2 = A). Wiring lands with session RAG in Sprint 5.
- Only EN translated; ES/FR/DE/PT fall back to EN (per user decision D3 = C). Sprint 8 fills translations.
- Session recovery path omitted (no "Recover existing session" button). Arrives in Sprint 7 alongside backend session store.

---

## Sprint 1 — COMPLETE (condensed)

- Backend FastAPI + admin auth + admin SPA shell (`/admin/`)
- Minimal sidecar (`/internal/health`, `/internal/config`)
- Docker: multi-stage backend & frontend images, shared `cbc-net`
- Host ports editable via `CBC_BACKEND_PORT` (8100) / `CBC_FRONTEND_PORT` (8190)
- ADR-007 (polling moved to Sprint 4)

---

## Spec Updates (between sprints)

- **2026-04-18 — SPEC §4.8 + §4.11 (new) + §5.1:** Contacts directory (authorized users) split from SMTP into its own tab. Global + per-frontend replace/append overrides. Seven HRDD-compatible fields (email / first_name / last_name / organization / country / sector / registered_by). xlsx + csv import/export, additive merge. SMTP loses `authorized_emails` (legacy field silently dropped on load); gains `admin_notification_emails: list[str]` and three toggles (`send_summary_to_user`, `send_summary_to_admin`, `send_new_document_to_admin`). Per-frontend SMTP override: only the admin recipients list (replace | append) — toggles stay global. Admin auth allowlist (Sprint 7) reads Contacts, not SMTP.
- **2026-04-18 — SPEC §4.7 + §5.1 (3 LLM slots + compression settings + routing toggles):** Third slot added — now `inference` / `compressor` / `summariser`. Top-level `compression` block (`enabled`, `first_threshold`, `step_size`) supports progressive context compression (HRDD pattern). Two summary-routing toggles (`document_summary_slot`, `user_summary_slot`) each accept any of the three slots so the admin can mix heavy/light models per task. Endpoint auto-fill via new `/admin/api/v1/llm/defaults` endpoint. Backend defaults changed from `host.docker.internal` to `localhost` (override per deployment). Admin RAG upload restricted to `.pdf` / `.txt` / `.md` (no `.docx`); session RAG in Sprint 5+ keeps `.docx` support. Multimodal dropped from scope (SPEC §4.7 "Not supported in v1.0"). Legacy 2-slot config in `/app/data/llm_config.json` auto-migrates on load (old `summariser` → new `compressor`, new `summariser` seeded from `inference`).
- **2026-04-18 — SPEC §4.7 + §5.1 + §8.3:** Added `api` as a third LLM provider type alongside `lm_studio` and `ollama`. Admin picks a flavor (anthropic / openai / openai_compatible). API keys referenced by env var name only — never stored in plaintext. Slots can mix providers. MILESTONES Sprint 3 `llm.py` deliverable updated to require all three providers, plus two new acceptance criteria. IDEAS entry promoted to `planned → Sprint 3 + 6`.

## Blocked / Questions
(none)
