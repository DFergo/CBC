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

## ADR-008: Parallel Polling Loop (Sprint 14)

**Decision:** Replace the Sprint 6A serial polling model (`for frontend: for message: await _process_message`) with parallel processing via `asyncio.gather`, bounded by a global `_turn_semaphore` whose cap is read from a new `LLMConfig.max_concurrent_turns` field (options 1 / 2 / 4 / 6, default 4). Two levels of parallelism land together: across frontends (outer gather in `_tick`) and across messages within a frontend (inner gather in `_process_frontend`). Recovery / auth / document-download handlers stay sequential per frontend — they're cheap and the parallelism win was in LLM-bound work.

**Context:** Sprint 13 made the queued state visible (`GET /internal/queue/position`, "en cola — N ahead" indicator). First real usage exposed that the ceiling was 1 conversation at a time across the entire deployment — not because of Ollama or LM Studio limits (Ollama NUM_PARALLEL was set to 2, LM Studio Parallel to 4), but because CBC's polling loop itself serialised every turn. With two users on the same frontend the second waited for the first to fully finish; with two users on different frontends the second still waited, because even the outer `for fe in registry.list_enabled()` was sequential. The runtime-level parallelism was being wasted.

At the same time, this Mac Studio serves two apps (CBC + HRDD) running on the same Ollama instance. Parallelising CBC (and later HRDD) puts the Ollama NP=4 slots to actual use. The Mac's 512 GB unified memory has comfortable headroom: at NP=4 with Qwen3.6:35B (CBC inference) + Gemma4:26B (HRDD inference) + Qwen3.5:9B (shared compressor) all loaded + LM Studio's Qwen3.5:122B summariser in parallel, peak use is ~306 GB — ~200 GB free.

**Concurrency audit (Sprint 14 implementation time):**
- `session_store` — disk-backed with in-memory cache, per-session files; different sessions never collide. Same session can't have two live turns because the UI locks input while `isStreaming`. Fine.
- Guardrails counter, context compressor, session_rag, smtp — all per-session or stateless. Fine.
- `llm_provider._fail_state` (circuit breaker) — module-level dict, simple add/clear ops that are GIL-atomic. Potential for benign miscounts under heavy contention. Accept.
- `httpx.AsyncClient` — the shared client passed around `_tick` is task-safe; httpx is built for concurrent use.
- `_pending_cancellations` (Sprint 14's other deliverable) — module-level `set[str]`; add/discard/`in` are GIL-atomic for str keys.

**The cancel watcher restructure (same ADR because it's load-bearing for this):** Sprint 13 spawned a `_watch_cancel` task per turn that polled `/internal/cancellations`, each drain clearing the sidecar's cancel set. With serial turns that was fine (only one watcher ever active). With N parallel watchers, drains race — one watcher gets the cancel tokens, siblings get empty, specific users' cancels get lost. Fix: one backend-level `cancel_watcher_loop` (sibling of `polling_loop`, running on its own 1 s cycle), populates a module-level `_pending_cancellations` set, every `_process_turn` reads that set via `cancel_check=lambda: session_token in _pending_cancellations`. Discarded on turn completion so stale signals can't bleed across turns.

**Alternatives considered:**
- Leave serial, rely on "horizontal scale" (more frontend containers per app) — Doesn't help same-frontend concurrency, and the Mac's memory is abundant.
- Per-frontend thread pool — Python async is cheaper than threads for I/O-bound streaming; threading adds GIL-contention concern without buying anything.
- Process-per-turn — Way overbuilt, breaks the shared session_store cache.
- No cap (unbounded parallelism) — Floods the downstream LLM runtime. OLLAMA_NUM_PARALLEL becomes a silent bottleneck users can't see (turns queue inside Ollama with no indicator). Explicit cap with warning text is the right UX contract.

**Consequences:**
- Up to `max_concurrent_turns` conversations stream in parallel per backend (configurable from admin: 1 / 2 / 4 / 6).
- Admin MUST align this value with `OLLAMA_NUM_PARALLEL` (and LM Studio's Parallel). Warning text in the admin UI states this explicitly. If CBC cap > runtime cap, excess queues inside the runtime WITHOUT a visible indicator (the existing Sprint 13 "en cola" indicator covers only the sidecar queue, not the runtime's internal queue).
- Cancel is now backend-global rather than per-turn — cleaner and race-free.
- Per-frontend isolation preserved via `_process_message_safe`: a crash in one message doesn't abort its siblings.
- HRDD Helper has the same serial-polling pattern and will benefit from an identical port (Sprint 14's closing deliverable is a handoff prompt for a Claude-in-HRDD session).

**Revisit if:** usage patterns shift to many simultaneous document-heavy Compare All queries (memory may become the cap before NUM_PARALLEL does), or if Ollama's concurrency model changes upstream (e.g., per-request num_ctx instead of model-load-time).
