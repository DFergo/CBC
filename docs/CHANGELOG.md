# CBC — Changelog

## Registered Users tab + SMTP notifications overhaul (2026-04-18)

- **New Registered Users tab (SPEC §4.11):** dedicated directory of authorized end-user emails, adapted from HRDD. Seven fields (email / first_name / last_name / organization / country / sector / registered_by), global list + per-frontend replace/append overrides, sortable filterable inline-editable table, xlsx/csv import (additive merge — never destructive), xlsx export (single scope or multi-sheet `all`), copy-from-another-frontend helper.
- **Backend:** `services/contacts_store.py` (load/save, scope resolution, sanitisation, dedupe-by-email), `api/v1/admin/contacts.py` (CRUD + import/export with `openpyxl`), `services/frontends.py` (minimal scanner of `/app/data/campaigns/*` — Sprint 4 replaces with real registry). `requirements.txt` adds `openpyxl>=3.1`.
- **SMTP rewrite:** dropped legacy `authorized_emails` (migrated silently on load — moved to Contacts conceptually). Added global `admin_notification_emails: list[str]` and three toggles: `send_summary_to_user`, `send_summary_to_admin`, `send_new_document_to_admin`. Per-frontend notification override lives at `/app/data/campaigns/{fid}/notifications.json` — replaces or appends to the global admin list for that frontend's notifications only (toggles stay global). `resolve_admin_emails(fid)` returns the effective recipient list. New admin routes: `GET/PUT/DELETE /admin/api/v1/smtp/frontend/{fid}` + `GET /admin/api/v1/smtp/frontends` (frontends-list helper for UI dropdowns).
- **Admin UI:** Dashboard now has three tabs (General / Frontends / Registered Users). `RegisteredUsersTab.tsx` full HRDD-style UX. `SMTPSection.tsx` rewritten: admin-emails textarea + three notification checkboxes + per-frontend override subsection (frontend picker, mode, textarea, resolved-preview, save/remove).
- **Smoke-tested end-to-end via curl:** SMTP GET returns new shape (authorized_emails gone, admin_notification_emails + 3 toggles present); contacts global CRUD, per-frontend append override, xlsx export produces a real .xlsx (5 KB Microsoft Excel 2007+), re-import produces `{added:0, updated:0, ignored:0}` (idempotent); notification override resolution works with `append` mode (`["global-admin@uni.org","sector-lead@packaging.org"]`).

## Default prompts trimmed — drop architecture chatter + framework section (2026-04-18)

- `cba_advisor.md` opening paragraph rewritten: no longer describes the app's RAG architecture (which the LLM doesn't need to know). Now describes the user's goal in this mode (examining / comparing / preparing negotiations around a single company's CBAs).
- `compare_all.md` opening paragraph same treatment: removes architecture description, replaces with the user's intent (sector-wide comparison, pattern finding, benchmarking).
- `core.md` "Frameworks You Can Reference" section removed — ILO / OECD / UN Guiding Principles / EU sectoral refs were irrelevant for this tool. Tightened the "What CBC Is Not" line that referenced ILO/OECD escalation.
- Runtime-effective prompts synced to the data volume so the changes are live; shipped image defaults updated so fresh installs pick them up via `ensure_defaults()`.

## LLM polish — endpoint auto-detection (host.docker.internal → localhost) (2026-04-18)

- `endpoint_defaults()` now probes candidates in order: `deployment_backend.json` override (if set) → `host.docker.internal:<port>` → `localhost:<port>`. First to answer wins. Returns the auto-detected URL for admin-UI auto-fill.
- `fetch_provider_status()` (top indicator) uses the same auto-detect when no slot is currently configured for that provider type; when a slot is, its endpoint is probed directly.
- Admin can still override: setting an explicit URL in the slot's Endpoint field (Tailscale / VPN / remote box) is preserved and probed as-is.
- Smoke-tested: `/defaults` returns `host.docker.internal:1234/v1` + `host.docker.internal:11434`; top indicator shows LM Studio online (18 models) and Ollama offline at `host.docker.internal:11434` (rather than the previous unreachable `localhost:11434`).

## LLM polish — indicator probes saved endpoints + proper model select (2026-04-18)

- Bug fix: `/providers` was probing the hardcoded defaults (`localhost:*`) instead of the endpoints the admin had actually saved, so the indicator showed offline even when LM Studio was running at `host.docker.internal`. Fixed by scanning saved slots and using the first endpoint for each provider type (inference → compressor → summariser order), falling back to `deployment_backend.json` defaults only when no slot uses that provider. Verified locally: LM Studio reported online with 18 models fetched.
- Model field: `<datalist>` (free-text with autocomplete) replaced with a proper HRDD-style `<select>` when models are available. Auto-corrects to the first available when the saved model isn't in the fetched list. Falls back to text `<input>` when the list is empty (e.g. API slot before "Check health" is clicked).

## LLM polish — provider status indicator + model dropdown (2026-04-18)

- Backend: new endpoint `GET /admin/api/v1/llm/providers` probes the default `lm_studio` + `ollama` endpoints from `deployment_backend.json` and returns `{endpoint, status, models, error}` per provider (HRDD pattern). Per-slot `check_slot_health()` extended to parse `/models` or `/api/tags` responses and return a `models` list; this covers all three provider types including `api` (Anthropic + OpenAI + OpenAI-compatible all expose `/v1/models`, fetched with the slot's env-var key).
- Admin UI: top indicator panel in the LLM section with LM Studio + Ollama status dots (green/red) + model count + endpoint shown. Polls `/providers` every 15s so the dots stay fresh.
- Admin UI: slot Model field now uses a native HTML `<datalist>` — the admin can pick from the fetched models (autocomplete as they type) or type a custom name freely. When the list is empty the field behaves as a plain text input. For `api` slots the list populates after "Check health" once the env var is set; an inline hint explains this.
- Smoke-tested: `/providers` returns per-endpoint status with models; `/health` returned 18 LM Studio models for a live endpoint in the local dev host.

## Spec bump — 3 LLM slots + context compression + summary routing (2026-04-18)

- SPEC §4.7 rewrite: 3 slots (`inference` / `compressor` / `summariser`) replacing the 2-slot shape. `compressor` is lightweight, periodic context-window compression; `summariser` does document summaries on injection + final conversation summary. Fallback cascade preserved: `compressor → summariser → inference`.
- SPEC §4.7: top-level `compression` block (`enabled`, `first_threshold`, `step_size` — progressive HRDD pattern). Two routing toggles (`document_summary_slot`, `user_summary_slot`), each accepting any of the 3 slots so admins can mix heavy/light models per task.
- SPEC §4.7 + §5.1: endpoint auto-fill via new `/admin/api/v1/llm/defaults` endpoint. Backend-configured URLs are the source of truth, auto-filled on provider change in the admin UI.
- SPEC §4.7: backend defaults changed from `host.docker.internal` to `localhost`. Deployments on Docker need to override via admin UI or `deployment_backend.json` (documented in SPEC).
- SPEC §4.7: admin RAG upload restricted to `.pdf` / `.txt` / `.md`; session RAG in Sprint 5+ still accepts `.docx`. Multimodal explicitly out of scope for v1.0.
- Backend: `llm_config_store.py` rewritten — 3 `SlotConfig`, `CompressionSettings`, `RoutingToggles`, auto-migration of legacy 2-slot `llm_config.json`, new `endpoint_defaults()` exposing backend URLs, `check_slot_health` covers all 3 slots. `admin/llm.py` adds `GET /defaults`. `rag_store.ALLOWED_EXTENSIONS` drops `.docx`. `core/config.py` + `deployment_backend.json` defaults flipped to `localhost`.
- Admin UI: `LLMSection.tsx` rewritten. Three slot editors in a grid, each with provider picker that auto-fills the endpoint from `/defaults` on change. Context compression block with enable checkbox + first-threshold + step-size inputs (disabled when compression is off). Summary routing block with two 3-position selects. Multimodal field removed. `RAGSection` file input accept attribute updated to `.pdf,.txt,.md`.
- `api.ts` expanded with `SlotName`, `CompressionSettings`, `RoutingToggles`, `LLMHealth`, `getLLMDefaults()`.
- MILESTONES Sprint 3: `llm.py` deliverable bumped to 3 slots; three new acceptance criteria for compression settings, routing toggles, endpoint auto-fill.
- Smoke-tested: existing 2-slot config auto-migrated on GET (old summariser → compressor preserved, new summariser seeded from inference); PUT persists new shape; `/defaults` returns `{lm_studio: "http://localhost:1234/v1", ollama: "http://localhost:11434"}`; health check covers 3 slots; admin RAG rejects `.docx` (`"File type '.docx' not allowed. Accepted: ['.md', '.pdf', '.txt']"`).

## Sprint 3 polish — Glossary & Organizations UI switched to JSON upload/download (2026-04-18)

- `GlossarySection.tsx` and `OrgsSection.tsx` rewritten to match the HRDD admin pattern: header with count + "Download JSON" / "Upload JSON" buttons, help text, collapsible read-only table
- Client-side validation on upload: rejects JSON without the expected wrapper (`{terms: [...]}` / `{organizations: [...]}`), surfaces a helpful error pointing to the download template
- Backend API unchanged (`PUT /admin/api/v1/knowledge/{glossary|organizations}` already accepted the payload)
- New `admin/src/utils.ts` with a shared `downloadJSON()` helper
- Inline add/edit UI removed — authoritative source is the JSON file the admin downloads, edits, and re-uploads

## Sprint 3 — Company Registry & Admin General Tab (2026-04-18)

- Backend services (7): `_paths` (storage layout + atomic JSON writes), `company_registry` (per-frontend CRUD, slug validation), `prompt_store` (3-tier aware), `knowledge_store` (glossary + orgs), `rag_store` (Sprint 3 stub — file storage + count/size stats), `llm_config_store` (2 slots × 3 provider types with real HTTP health probe), `smtp_service` (adapted from HRDD, real `send_test` via `aiosmtplib`)
- Admin API (6 routers): `companies.py`, `prompts.py` (global + per-frontend + per-company routes), `rag.py`, `knowledge.py`, `llm.py`, `smtp.py` — all under `/admin/api/v1/...`, all guarded by `require_admin`
- Default content shipped with the image (installed idempotently on first boot via `ensure_defaults()`): 5 CBC-specific prompts (core / guardrails / cba_advisor / compare_all / context_template) + glossary (10 terms, EN+ES+FR+DE+PT translations) + organizations (7 entries: UNI, UNI G&P, ILO, ITUC, IndustriALL, BWI, ETUC)
- `requirements.txt` adds `aiosmtplib`
- Admin SPA: `Dashboard.tsx` with tab navigation (General + Frontends), `GeneralTab.tsx` orchestrates 7 sub-sections (Branding placeholder, Prompts editor, RAG upload/list/reindex, Glossary CRUD, Orgs CRUD, LLM per-slot provider picker with `api` flavor fields, SMTP with `send_test` button). `FrontendsTab.tsx` placeholder for Sprint 4
- Admin `api.ts` extended with ~20 new client functions
- Smoke-tested end-to-end via curl on `localhost:8100`: company CRUD + duplicate-slug validation, RAG upload/delete/reindex-stub, prompts read/save, glossary + orgs CRUD, LLM config save with `api`-provider slot (anthropic flavor + `api_key_env`), health check reports slot status (LM Studio reachable on host, Ollama unreachable, `api` correctly reports missing env var), SMTP config save with password redaction

## Spec bump — API as third LLM provider (2026-04-18, between Sprint 2 and Sprint 3)

- SPEC §4.7: `lm_studio` / `ollama` / `api` as first-class provider types; `api` flavors (`anthropic` / `openai` / `openai_compatible`); slots can mix providers independently; per-frontend overrides preserved
- SPEC §5.1: admin LLM config UI enumerates the three provider types + `api`-specific fields (flavor, endpoint, key-env-var name)
- SPEC §8.3: chat content leaves the deployment only when `api` is selected (documented exception to "no third-party services"); API keys referenced by env var name, never plaintext, never committed
- MILESTONES Sprint 3: `llm.py` deliverable expanded to 2 slots × 3 providers; two new acceptance criteria for `api` flavor + env-var-name persistence
- IDEAS entry promoted to `planned → Sprint 3 + 6`
- STATUS gains a "Spec Updates (between sprints)" section

## Sprint 2 — Frontend Page Flow (2026-04-18)

- Full page flow: language → disclaimer → session → auth → instructions → company select → survey → placeholder
- 7 page components: LanguageSelector, DisclaimerPage, SessionPage, AuthPage, InstructionsPage, CompanySelectPage (new), SurveyPage
- TypeScript core: `types.ts` (Phase, LangCode, Company, SurveyData, ComparisonScope), `token.ts` (XXXX-NNNN), `i18n.ts` (EN only — fallback structure ready for ES/FR/DE/PT in Sprint 8)
- Tailwind + PostCSS wired into frontend Vite build
- Sidecar extended: `/internal/companies` (sidecar-local stub, moves to backend in Sprint 3), `/internal/auth/request-code` + `/internal/auth/verify-code` (dev stub — returns 6-digit code inline), `/internal/queue` POST/GET for survey submit
- `companies.json` stub: Compare All + Amcor + DS Smith + Mondi
- Decisions logged: auth is sidecar stub (D1=A, real SMTP Sprint 7), upload UI visible but not wired (D2=A, Sprint 5), EN only (D3=C, Sprint 8)
- Session recovery path deferred to Sprint 7 (needs backend session store)
- Post-sprint polish: country tags removed from CompanySelectPage buttons (data retained in Company model for Sprint 5 filtering; idea for CBA sidepanel during chat logged in `docs/IDEAS.md`)
- New tooling: `docs/IDEAS.md` backlog file + `/idea` slash command (`.claude/commands/idea.md`) that appends captured ideas to the backlog with sprint/date context

## Sprint 1 — Scaffolding & Core Backend (2026-04-18)

- FastAPI backend: `main.py`, `core/config.py` (CBC-tuned: `rag_watcher_enabled`, `rag_watcher_debounce_seconds`, `campaigns_path`; no `letta_compression_threshold`, no reporter slot)
- Admin auth adapted from HRDD (`/admin/status`, `/admin/setup`, `/admin/login`, `/admin/verify`). Env var renamed to `CBC_DATA_DIR`; admin localStorage key to `cbc_admin_token`
- Admin SPA shell: App/SetupPage/LoginPage/Dashboard-placeholder, Vite + Tailwind. Dashboard is a placeholder until Sprint 3
- Frontend sidecar: minimal `/internal/health` + `/internal/config` (full message queue / SSE / auth / uploads land alongside the pages that use them)
- Frontend React stub so Nginx has something to serve pre-Sprint-2
- Docker: `Dockerfile.backend` (multi-stage admin+python), `Dockerfile.frontend` (multi-stage react+nginx+sidecar), compose files, nginx config, supervisord config — shared `cbc-net` network so backend can reach frontend sidecars
- ADR-007: moved "backend polls sidecar and detects online" from Sprint 1 to Sprint 4 (polling loop lands in Sprint 6)

## Sprint 0 — Project Setup (2026-04-18)

- SpecForge output generated: CLAUDE.md, SPEC.md, MILESTONES.md, architecture docs, knowledge docs
- HRDDHelper/ reference code available in project root
- Claude Code environment (.claude/) configured with commands and settings
