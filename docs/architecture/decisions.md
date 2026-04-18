# Architecture Decision Records

## ADR-001: Reuse HRDD Helper Architecture (Pull-Inverse)

**Decision:** CBC reuses the pull-inverse polling architecture from HRDD Helper rather than switching to WebSockets or a push-based model.

**Context:** CBC needs the same distributed frontend capability — frontends may be behind firewalls or NATs. The pull-inverse pattern is proven in HRDD Helper and handles this well.

**Alternatives Considered:**
- WebSockets — Lower latency but requires inbound connections to frontends, complicates firewall traversal
- Direct API (frontend calls backend) — Simpler but exposes backend URL to end users, harder to scale

**Consequences:**
- 2-second polling delay is acceptable for chat (not real-time critical)
- Frontend containers remain stateless and portable
- Backend is the single orchestrator — simplifies debugging

---

## ADR-002: Three-Tier Config Hierarchy (Global → Frontend → Company)

**Decision:** Add a third config tier (Company) below the existing Global → Frontend model from HRDD Helper.

**Context:** CBC is organized around companies. Each company may have different CBAs, negotiation contexts, and even different prompt strategies. Frontends group companies by sector/region but individual companies need their own configuration.

**Alternatives Considered:**
- Two tiers only (Global → Frontend, company is just RAG data) — Too rigid, can't customize prompts per company
- Flat config (everything per company, no inheritance) — Too much duplication, maintenance nightmare
- Database-backed config — Adds complexity, HRDD Helper proves filesystem works

**Consequences:**
- Config resolution requires cascading lookups (3 levels) — must be well-cached
- Admin UI is more complex (nested config per company within frontend)
- File watcher must understand the directory hierarchy to scope reindexing correctly
- Enables very flexible deployment: one backend serving multiple sectors, each with company-specific behavior

---

## ADR-003: File Watcher for RAG Sync

**Decision:** Use Python `watchdog` library to automatically detect changes in the RAG documents folder and trigger reindexing.

**Context:** Admins want to manage CBAs both via the admin panel AND by dropping files into folders on disk. This is especially useful when many documents need to be batch-loaded.

**Alternatives Considered:**
- Admin panel only — Simpler but forces one-by-one uploads for large document sets
- Manual reindex button only — Requires remembering to click after file changes
- inotify directly — Linux-only, doesn't work on macOS (where Daniel develops via OrbStack)

**Consequences:**
- watchdog works cross-platform (macOS, Linux) — important for dev vs. production
- Must handle debouncing to avoid reindex storms during bulk copies
- Must filter iCloud artifacts (.icloud, ._* files) since Daniel uses iCloud-synced folders
- Adds a background task to the backend — must be thread-safe with RAG service

---

## ADR-004: No Final Report Generation

**Decision:** CBC does not generate formal violation reports or internal case files. Only a user summary is produced.

**Context:** HRDD Helper generates bilingual violation reports and internal UNI assessments. CBC's purpose is different — it's a research/comparison tool, not a documentation pipeline. Users want conversation summaries, not formal documents.

**Alternatives Considered:**
- Keep report generation — Unnecessary complexity for a different use case
- Generate comparison reports — Potentially useful but out of scope for v1.0

**Consequences:**
- LLM provider simplified to 2 slots (inference + summariser) instead of 3
- Prompt system simplified (no report-specific prompts)
- Session lifecycle simplified (no report generation step)
- Future: comparison reports could be added as a new feature if needed

---

## ADR-005: Session Auto-Destruction for Privacy

**Decision:** Add configurable session auto-destruction that completely deletes session files (not just archives them).

**Context:** Some deployments may handle sensitive negotiation data. The option to automatically destroy sessions after a configurable period provides privacy guarantees.

**Alternatives Considered:**
- Archive only (HRDD Helper approach) — Files remain on disk indefinitely
- Encryption at rest — More complex, doesn't reduce storage, still requires key management

**Consequences:**
- New session state: `destroyed` (files physically deleted)
- Must also destroy: session RAG index, uploaded documents, conversation logs
- Default: disabled (auto_destroy_hours = 0)
- Admin can configure per frontend

---

## ADR-006: Single User Profile

**Decision:** CBC has a single user profile (trade unionist) instead of HRDD Helper's multi-role system (worker, organizer, officer).

**Context:** All CBC users are union professionals using the tool for CBA research and comparison. Role-based differentiation is unnecessary.

**Alternatives Considered:**
- Keep multi-role — Adds UI complexity without value
- Add roles later — v1.0 doesn't need them; can be added if needed

**Consequences:**
- Frontend simplification: no RoleSelectPage, replaced by CompanySelectPage
- Prompt simplification: one role prompt (cba_advisor.md) instead of role-specific prompts
- Compare All gets its own prompt (compare_all.md) but it's not a role — it's a mode

---

## ADR-007: Sprint 1 Scope — Reachability, Not Polling

**Decision:** Sprint 1's acceptance criterion "backend polls sidecar and detects it as online" is moved to Sprint 4, when `frontend_registry.py` lands. Sprint 1 only verifies that the sidecar is reachable from inside the Docker network.

**Context:** The original Sprint 1 acceptance criterion required a live polling loop, but `polling.py` is a Sprint 6 deliverable and `frontend_registry.py` a Sprint 4 deliverable. Implementing a one-shot or stub polling loop in Sprint 1 would duplicate work and couple scaffolding to services that haven't been designed yet.

**Alternatives Considered:**
- Add minimal `frontend_registry.py` + polling loop in Sprint 1 — Leaks scope from two later sprints, forces premature API design
- One-shot boot-time probe — Throwaway code, deleted the moment real polling arrives

**Consequences:**
- Sprint 1 stays tight: scaffolding + admin login only
- Sprint 4 absorbs the online-detection check alongside the frontend registry
- A reachability smoke test (curl from backend container to sidecar) still proves the Docker network is wired correctly

---

<!-- Append new ADRs below. Never modify or delete existing ADRs. -->
