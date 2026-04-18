# CBC — Project Status

**Current Sprint:** 3 — Company Registry & Admin General Tab
**Last Updated:** 2026-04-18

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

- **2026-04-18 — SPEC §4.7 + §5.1 + §8.3:** Added `api` as a third LLM provider type alongside `lm_studio` and `ollama`. Admin picks a flavor (anthropic / openai / openai_compatible). API keys referenced by env var name only — never stored in plaintext. Slots can mix providers. MILESTONES Sprint 3 `llm.py` deliverable updated to require all three providers, plus two new acceptance criteria. IDEAS entry promoted to `planned → Sprint 3 + 6`.

## Blocked / Questions
(none)
