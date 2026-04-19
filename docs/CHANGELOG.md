# CBC — Changelog

## Global branding defaults — collapsible card with chevron + 7 fields (2026-04-19)

- Phase 2 of the branding overhaul: General-tab `Branding defaults` rebuilt as a collapsible card.
  - Always visible: title (with chevron when defaults are active), short description, `Use custom branding defaults` toggle.
  - Toggle ON → creates the `branding_defaults.json`, expands the form, and pushes the empty defaults to every frontend without its own override (admins fill the fields and Save to push real values).
  - Toggle OFF → confirms, deletes the file, fans out the clear-payload, collapses the card.
  - Chevron in the header lets the admin collapse the open form back without disabling the override (e.g. to clean up the General tab once configured). A `Collapse` button at the bottom of the form does the same. Reload restores the expanded state when defaults exist.
- Same 7 fields as the per-frontend panel (Phase 3): App title, App owner (`org_name`), Logo URL, Primary color, Secondary color, Disclaimer text, Instructions text. Per-field merge already lives in the resolver, so empty fields here inherit the hardcoded sidecar baseline.
- Per-frontend `Branding override` panel (Phase 3) left as-is for now — same chevron/collapse logic will be retrofitted later when we revisit the per-frontend tier.
- Admin bundle hash bumped (`index-BFGkoWIW.js`); served by the rebuilt backend container.

## Per-frontend branding override — collapsible panel + disclaimer/instructions text + per-field merge (2026-04-19)

- Phase 3 of the branding overhaul: per-frontend override panel rebuilt as a collapsible card.
  - **Collapsed** (override OFF): title + description + `Override branding for this frontend` toggle. That's it.
  - **Expanded** (override ON): seven inputs — App title, App owner (`org_name`), Logo URL, Primary color, Secondary color, Disclaimer text (textarea), Instructions text (textarea). Save + push to the sidecar.
- New per-field merge model for branding (replaces winner-takes-all):
  - Backend `resolvers.resolve_branding(fid)` now merges global defaults + per-frontend override per field — deepest non-empty wins. `branding_push_payload` strips empty fields and pushes `{custom: True, ...non_empty_fields}` so that empty per-frontend fields inherit the global default → hardcoded baseline instead of clobbering it.
  - Sidecar `/internal/config` merges pushed non-empty fields onto `_HARDCODED_BRANDING` (was: wholesale replacement). Empty pushed fields are dropped server-side, so they can never blank out the baseline.
- Two new branding fields end-to-end:
  - `disclaimer_text` — when non-empty, replaces the 3-section i18n disclaimer with a single custom block (still rendered via `whitespace-pre-line`, so `\n\n` paragraph breaks work).
  - `instructions_text` — when non-empty, replaces the i18n `instructions_body`.
  - Added to `Branding` Pydantic model, sidecar `_HARDCODED_BRANDING` (empty by default), `BrandingConfig` TS interface, `FrontendBranding` admin TS interface. `DisclaimerPage.tsx` and `InstructionsPage.tsx` prefer `branding.*_text` when present.
- `BrandingSection.tsx` (global defaults panel) updated minimally: `EMPTY` constant carries the new fields so the type still validates. The full collapsible/textarea UI for the global tier is Phase 2 — coming next.
- `localhost:8190/internal/config` now returns all 7 branding fields. Verified after a full backend + frontend Docker rebuild.

## Default branding expanded — header logo + org_name + richer disclaimer/instructions (2026-04-19)

- Phase 1 of the branding overhaul: make the **default** branding feel like a real app, not a placeholder. (Phases 2 + 3 — global override and per-frontend override surfacing the same fields — are next.)
- New branding field `org_name` (e.g. "UNI Global Union"): added to `Branding` Pydantic model (`branding_store.py`), to `_HARDCODED_BRANDING` in the sidecar, and to `BrandingConfig` in `frontend/src/types.ts`. Defaults to "UNI Global Union".
- `App.tsx` header: monochrome logo top-left (HRDD pattern: `h-8 brightness-0 invert`) + `branding.org_name` top-right (was hardcoded "UNI Global Union"). Footer copyright also reads `branding.org_name`.
- `i18n.ts`: disclaimer (`disclaimer_what_body`, `disclaimer_data_body`, `disclaimer_legal_body`) and `instructions_body` rewritten with HRDD-equivalent depth, adapted to CBC's domain — bargaining research and CBA comparison instead of HRDD's labour-violation documentation. Each section now uses `\n\n` paragraph breaks + `-` bulleted lists (rendered via existing `whitespace-pre-line` styling on the page bodies).
- `[DATA_PROTECTION_EMAIL]` placeholder kept in `disclaimer_legal_body` for now; resolution from config is on the backlog (HRDD Helper passes `dataProtectionEmail` as a prop).
- Frontend build clean (`tsc && vite build`).
- Smoke check pending: docker rebuild + visual diff on header/disclaimer/instructions.

## SPEC §5.1 Tab 2 — per-frontend LLM override documented (2026-04-19)

- Tab 2 (Frontend Configuration) was missing the `LLM override` bullet even though `PerFrontendLLMPanel.tsx` shipped with Sprint 4B. Added — describes the snapshot-on-enable toggle and the three provider types (`lm_studio` | `ollama` | `api`) inherited from the global tab.
- Fixed §5.1 header self-contradiction ("two main tabs" / "Three tabs") → "three tabs".
- IDEAS.md entry for "LLM provider options" updated to point at §5.1 Tab 2 + §4.9 + the existing `llm_config_store.py` / `PerFrontendLLMPanel.tsx` code that already lands the idea — no duplicate idea created.

## Branding baseline moved from deployment_frontend.json to hardcoded sidecar constant (2026-04-19)

- HRDD pattern: app branding lives in code, with the admin able to override globally or per-frontend.
- Sidecar gains `_HARDCODED_BRANDING` constant (UNI Global logo, "Collective Bargaining Copilot" title, UNI palette `#003087` / `#E31837`).
- New precedence (highest first): per-frontend override → global default → hardcoded constant.
- `branding` block removed from `deployment_frontend.json` — that file no longer carries branding at all in CBC's model. Sidecar `/internal/config` falls back to the hardcoded constant when no overrides exist.
- SPEC §4.9 updated with the new precedence + the "branding lives in code" rule.
- Smoke-tested 4 cases: no overrides → hardcoded; cache wiped → still hardcoded (no JSON fallback); admin saves global default → override wins; admin deletes global default → falls back to hardcoded.

## UNI Global logos shipped as frontend assets (2026-04-19)

- New `CBCopilot/src/frontend/public/assets/` (Vite copies it verbatim into `dist/`):
  - `uni-global-logo.png` — UNI Global landscape (10.5 KB), set as the default `logo_url` in `deployment_frontend.json`
  - `uni-global-gp-logo.png` — Graphical & Packaging variant (42 KB), available for sectoral deployments
- `deployment_frontend.json` baseline branding updated to use the UNI Global logo (no G&P) per Daniel's instruction for development. Title set to "Collective Bargaining Copilot", colors reset to UNI palette (`#003087` blue, `#E31837` red).
- File-permissions fix: source PNGs came from iCloud with `0600`; chmod to `0644` so Nginx (running as `nginx` user) can serve them. Without this Nginx returned `403`.
- Verified end-to-end: both logos return HTTP 200 from `localhost:8190/assets/...` after rebuild; sidecar `/internal/config` reports the new branding baseline.

## Branding defaults — global tier + fan-out push (2026-04-19)

- **Bug fix**: General tab's BrandingSection was a Sprint 1 placeholder that Sprint 4 never replaced. Now a real editor.
- New `services/branding_defaults_store.py` storing `/app/data/branding_defaults.json`.
- New `resolvers.resolve_branding(fid)` and `branding_push_payload(fid)`: per-frontend override > global defaults > None (sidecar falls back to its `deployment_frontend.json` baseline).
- New `api/v1/admin/branding.py` router: `GET/PUT/DELETE /admin/api/v1/branding/defaults`. PUT/DELETE trigger a fan-out push to every registered frontend that does NOT have a per-frontend override; frontends with their own override are untouched.
- Refactored per-frontend branding routes (`PUT/DELETE /admin/api/v1/frontends/{fid}/branding`) to use `resolvers.branding_push_payload(fid)` so the push always reflects the resolved tier (e.g. deleting a per-frontend override now sends the global default if one exists, instead of `{custom: False}`).
- Admin UI: `BrandingSection.tsx` rewritten as a real editor with "Save + push to frontends" button reporting how many frontends were updated. `api.ts` adds `getBrandingDefaults / saveBrandingDefaults / deleteBrandingDefaults`.
- Smoke-tested 3-tier flow: save defaults → 1 frontend pushed; create per-frontend override → wins; change defaults → 0 pushes (override unaffected); delete override → falls back to global; delete global defaults → falls back to baseline. All steps reflected immediately in `localhost:8190/internal/config`.

## Sprint 4B — Per-frontend content overrides + 3-tier resolvers (2026-04-18)

- **Resolvers** (`services/resolvers.py`): the functions the chat engine (Sprint 6) will call to pick the effective prompt / RAG / orgs for a given session. Preview endpoints under `/admin/api/v1/resolvers/*` let admins inspect resolution without running a chat.
  - **Prompts = winner-takes-all** (NOT stacked). Normal role prompts: company → frontend → global. `compare_all.md` skips the company tier (cross-company by definition): frontend → global.
  - **RAG = stackable** per `company.rag_mode` + `frontend.rag_standalone` (new backend-only session-settings field). Single-company chat stacks `company + frontend? + global?` with the `+ global` gated by `rag_standalone`. Compare All stacks all company docs (filtered by `comparison_scope` — `national` filters by user country tag, `regional` is a Sprint 5 placeholder) + frontend + (global unless `standalone`).
  - **Orgs = mode-based** per frontend: `inherit` (default, uses global), `own` (replace global), `combine` (global + per-frontend deduped by name).
  - **LLM = all-or-nothing** per frontend (new `services/llm_override_store.py`). When an override file exists, it fully replaces the global LLM config for that frontend; when absent, frontend inherits.
- **Per-frontend stores**: `services/orgs_override_store.py` (mode + org list), `services/llm_override_store.py` (full LLMConfig snapshot). Both live under `/app/data/campaigns/{frontend_id}/`. `session_settings_store` gets a new `rag_standalone` field; sidecar push excludes it (backend-only).
- **Admin routes**: `api/v1/admin/resolvers.py` (preview GET endpoints for prompts/RAG/orgs). `api/v1/admin/frontends.py` extended with `/{fid}/orgs` and `/{fid}/llm` CRUD.
- **Admin UI refactor**: `PromptsSection` + `RAGSection` now accept optional `{frontendId, companySlug}`. Same component renders global (General tab), per-frontend (FrontendsTab), and per-company (expanded company row). Per-tier heading + description, plus "Preview resolution" button and "Delete this override" button (non-global only).
- **New panels**: `PerFrontendOrgsPanel` (mode selector + JSON download/upload + preview), `PerFrontendLLMPanel` (override-global checkbox that snapshots from global on enable + JSON download/upload for editing).
- **CompanyManagementPanel** expanded: each company row gets a "Show content" toggle that renders PromptsSection + RAGSection for that company (skipped for `is_compare_all=true` because compare_all doesn't have per-company content).
- **SessionSettingsPanel** gains a `rag_standalone` toggle with per-field inherit dropdown.
- **api.ts** refactor: `listPrompts/readPrompt/savePrompt/deletePrompt` accept `(frontendId?, companySlug?)` and route to the correct tier URL. `listRAG/uploadRAG/deleteRAG/getRAGStats/reindexRAG` accept the same and pass as query params. New clients for `getFrontendOrgsOverride/saveFrontendOrgsOverride/deleteFrontendOrgsOverride`, `getFrontendLLMOverride/saveFrontendLLMOverride/deleteFrontendLLMOverride`, `previewPromptResolution/previewRAGResolution/previewOrgsResolution`.
- **Smoke-tested end-to-end**: no-override chat queries resolve to global; creating frontend-level `core.md` override flips all company queries for that frontend to `tier=frontend`; adding a company-level override for `amcor` flips only amcor to `tier=company`; `compare_all.md` with `compare_all=true` skips company tier as designed; RAG resolver stacks `[company, frontend, global]` by default and drops `global` when `rag_standalone=true` is pushed; orgs resolver returns `mode=inherit, count=7` by default.
- **SPEC §2.4 rewritten** with exact resolution rules (prompts / RAG / orgs / LLM all documented). **§4.9** notes `rag_standalone`. **MILESTONES Sprint 4** all acceptance criteria green.

## CompanyManagementPanel polish — country_tags as read-only chips (2026-04-18)

- `country_tags` is meant to be auto-derived from per-document RAG metadata (SPEC §4.2) once Sprint 5 lands. Instead of shipping a manual editor in Sprint 4A that Sprint 5 will replace with a computed field, the UI now shows the tags as read-only chips with a "auto-derived from document metadata (Sprint 5)" hint. Existing values (seeded from the Sprint 2 sidecar stub) are preserved. Backend PATCH still accepts the field so Sprint 5 can write to it programmatically when indexing documents.

## Sprint 4A — Frontend registry + polling + per-frontend branding/session-settings/companies (2026-04-18)

- **Frontend registry** (`services/frontend_registry.py`): CBC variant of HRDD's registry, keyed by the stable `frontend_id` each frontend already carries in its `deployment_frontend.json` (same key that names `/app/data/campaigns/{frontend_id}/`). No random hex ID. Admin registers each frontend manually with `{frontend_id, url, name}` — auto-registration rejected because it would force the frontend to know the backend URL (violates "frontend doesn't know backend" rule; breaks NAT/firewall/Tailscale portability).
- **Health polling** (`services/polling_loop.py`): every 5s, `GET {url}/internal/health` on each enabled frontend; updates runtime `status` (online / offline / unknown) and writes `last_seen` on success. Not persisted — recomputed each loop. Lifespan wires + cancels cleanly. **Resolves ADR-007** (the acceptance criterion from Sprint 1).
- **Per-frontend branding + session settings** (`branding_store.py`, `session_settings_store.py`): overrides live under `/app/data/campaigns/{frontend_id}/`. Session-settings fields are individually nullable so admins can inherit from `deployment_frontend.json` for some while overriding others.
- **Sidecar push pattern** (HRDD): `POST /internal/branding` + `POST /internal/session-settings`. Sidecar caches pushed payloads in its own `/app/data/` and merges into `/internal/config` so the React app sees effective config without knowing which layer each field came from. Baseline `deployment_frontend.json` continues to drive fields that have no override.
- **Admin routes** (`api/v1/admin/frontends.py`): registry CRUD + per-frontend branding + session-settings + push on save. DELETE clears override and pushes empty body to restore baseline.
- **Admin UI**: `FrontendsTab.tsx` rewritten from placeholder — registered-list with status dots + last-seen, register form, per-frontend panels. `panels/BrandingPanel.tsx`, `panels/SessionSettingsPanel.tsx`, `panels/CompanyManagementPanel.tsx`. New types in `api.ts` (`FrontendInfo`, `FrontendBranding`, `FrontendSessionSettings`) + register/update/delete/branding/session-settings client functions. `FrontendInfo` shape migrated from `{id,name}` to `{frontend_id, url, name, status, last_seen, enabled, ...}` — callers (RegisteredUsersTab, SMTPSection override block) updated.
- **Cleanups**: deleted obsolete `services/frontends.py` scanner + provisional `/admin/api/v1/smtp/frontends` endpoint (replaced by the real registry). Dropped `backend_url` from `deployment_frontend.json` + sidecar — it was unused and violated the architectural rule.
- **Smoke-tested end-to-end**: registered `packaging-eu` → polling flipped to `online` within 6s → branding push → sidecar `/internal/config` shows custom → session-settings push with mixed overrides/nulls → sidecar merges correctly (e.g. `auth_required=false` override, `disclaimer_enabled=true` inherited from baseline) → branding DELETE → sidecar falls back to baseline.

Sprint 4B (per-frontend prompts/RAG/orgs/LLM + 3-tier resolvers) is next.

## SMTP admin emails — input+chips UX (fix Enter swallowing new line) (2026-04-18)

- Bug: the admin emails textarea used `split('\n').filter(Boolean)` which deleted empty lines as soon as you typed Enter, swallowing the cursor before you could type the next address.
- Replaced both admin-email editors (global + per-frontend override) with HRDD's pattern: `<input type="email">` + "Add" button + chip per email with × to remove. Enter key adds. Duplicates rejected silently (case-insensitive).
- New reusable `admin/src/EmailChipsInput.tsx` component.

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
