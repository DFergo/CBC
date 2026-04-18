# CBC — Changelog

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
