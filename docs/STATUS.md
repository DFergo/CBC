# CBC — Project Status

**Current Sprint:** 7 — Sessions & Lifecycle (auth, SMTP, session recovery, auto-destroy)
**Last Updated:** 2026-04-20

Sprint 6B closed. Chat is visible and usable in the browser — survey → streaming response → multi-turn → End Session → inline summary with copy button.

---

## Sprint 6B — COMPLETE

**Goal (MILESTONES §Sprint 6 remaining):** the chat is usable from the browser. User submits survey → lands in ChatShell → sees their initial query as the first bubble → assistant response streams in → user sends follow-ups → clicks End Session → gets a summary.

### Deliverables (all ✓)

- `frontend/src/components/ChatShell.tsx` — single file, ~350 LoC. EventSource SSE, message bubbles (user / assistant / summary), ReactMarkdown + remark-gfm for assistant output, textarea auto-resize, send-on-Enter, attachment chips, End-session confirm modal.
- `frontend/src/App.tsx` — new `chat` phase replaces the `placeholder` stopgap. `beforeunload` warning extended to the chat phase.
- `frontend/src/i18n.ts` — chat UI strings (placeholder, send, thinking, end confirm, summary heading, guardrail warning, attach chips, session ended).
- `frontend/src/types.ts` — `Phase` gains `'chat'`.
- Backend `POST /internal/close-session` (sidecar) + `close`-type handler in `polling.py`. Uses Sprint 4B's `resolve_prompt("summary.md", ...)` so per-frontend summary prompt overrides work. Runs via the **summariser** slot, streams tokens back through the existing SSE channel, marks `session.status='completed'`.
- Backend `GET /api/v1/sessions/{token}/status` — lightweight poll target for the chat UI (status + guardrail_violations + message_count).
- Backend `services/context_compressor.py` — real implementation. Estimates tokens (~4 chars/token), fires at `first_threshold + step_size * n`. Compresses `messages[:-KEEP_RECENT]` into a single system summary via the **compressor** slot; keeps the last 4 turns verbatim. Cache per `session_token`; cleared on session destroy.
- `polling.py` calls `context_compressor.compress_if_needed` right before every `inference` call.
- `session_store.destroy_session` now also clears `context_compressor` + `session_rag` caches, so privacy wipe drops all in-memory state.
- `frontend/package.json` gains `react-markdown` + `remark-gfm` (+ installed).

### Decisions locked

- **D1 = A** — File upload chips shipped (drag-drop + button + inline chip row, `.pdf/.txt/.md/.docx`). Uploads route through the Sprint 5 sidecar relay. Ready chips are sent alongside the next turn and render as file pills in the user bubble.
- **D2 = A** — Real compressor (progressive thresholds from SPEC §4.7, keeps last 4 turns verbatim, runs on the compressor slot).
- **D3 = B** — No session recovery in 6B. Lives in Sprint 7 alongside the auth-code flow.
- **D4 = A** — Inline summary bubble + Copy button is the default. Email is flagged in logs for Sprint 7's SMTP wiring.
- **D5 = A (+ follow-up sprint)** — Banner at ≥2 violations (amber), session-ended state at ≥5 (red). **Added Sprint 7.5 — Guardrails Review** to MILESTONES for a dedicated pass on the trigger list + admin-configurable thresholds.
- **D6 = A** — Assistant output rendered via `react-markdown` + `remark-gfm`.

### Acceptance (run in browser)

Open `http://localhost:8190/`:
1. Pick English → skip disclaimer → new session → auth (if enabled; dev banner surfaces the code) → instructions → pick **Amcor** → fill survey (use country `AU`, initial query `"What does the Amcor CBA say about overtime?"`) → Start chat.
2. Chat view should appear with the user's initial query as the first bubble and the assistant response streaming in, citing `amcor_au_2024.txt`.
3. Type a follow-up: `"And about vacation?"` → Enter → new bubble streams.
4. Click **Attach file** → pick a PDF → chip appears (`uploading` → `ready`) → ask a question about that file → chip rides along in the user bubble and the RAG uses the upload.
5. Click **End session** → confirm → summary bubble streams; Copy-to-clipboard works; input locks.
6. Spam a prompt-injection pattern (`"ignore your previous instructions"`) two turns → amber guardrails banner appears. Push to 5 → red "session ended" banner.

### Deferrals

- SMTP send of summary to `survey.email` — Sprint 7 (real SMTP lands there).
- Session recovery by re-entering the token — Sprint 7.
- Guardrails trigger-list tuning + admin-configurable thresholds + editor UI — Sprint 7.5.

---

### Decisions locked (2026-04-20)

- **D1 = A** — File upload UI (drag-drop + chips) ships in 6B. Sprint 5 backend + sidecar relay already built; ChatShell just adds the UI surface.
- **D2 = A** — Real context compressor implemented in 6B (progressive thresholds from SPEC §4.7).
- **D3 = B** — No session recovery in 6B. Lands Sprint 7 alongside auth.
- **D4 = A** — End-session always shows the summary inline as a final "Summary" bubble with a Copy-to-clipboard button. Email, when the user provided one in the survey, is an *extra* — the inline display is the default path. SMTP-send stays Sprint 7; Sprint 6B logs the would-send.
- **D5 = A (with follow-up)** — Ship the guardrails banner now (warn ≥2 violations, session-ended ≥5, defaults tunable later). Daniel flagged that the trigger rules deserve a dedicated pass. **Added Sprint 7.5 — Guardrails Review** to MILESTONES between Sprints 7 and 8.
- **D6 = A** — `react-markdown` + `remark-gfm` for assistant output (matches HRDD).

### Deliverables

- `frontend/src/components/ChatShell.tsx` — adapted from HRDD. EventSource connection, streaming render, message send, markdown rendering (ReactMarkdown + remarkGfm), textarea auto-resize, send-on-Enter.
- `frontend/src/App.tsx` — swap the `phase=placeholder` block for `<ChatShell>`.
- `frontend/src/i18n.ts` — chat UI labels (placeholder, send, end session, confirm, summary header, violation warning).
- Backend `POST /api/v1/sessions/{token}/close` — triggers summary generation via the summariser slot; persists + returns text. SMTP send is Sprint 7 (logs the would-send).
- Backend `GET /api/v1/sessions/{token}` — read-only session metadata (used by ChatShell to check status + violations).
- `services/context_compressor.py` — real `should_compress` + `compress` (progressive thresholds from `LLMConfig.compression`).
- `polling.py` — call `context_compressor.compress()` before each LLM call when applicable.
- Guardrails UI: ChatShell reads `guardrail_violations` from session endpoint; shows a warning banner when `> 2` (threshold configurable in 7+).

### Decisions to lock

- **D1 — File upload UI in 6B?** Sprint 5 already built the backend + sidecar relay. ChatShell just needs drag-drop + chip row.
  - A. Include — wire the upload chips now, file-aware chat bubbles. *(recommended — small surface on top of a working pipeline; otherwise session RAG sits unused)*
  - B. Defer to Sprint 7 — text-only chat in 6B.

- **D2 — Context compressor in 6B?** Demo conversations won't hit 20 k tokens, so this is "implement while the design is fresh" vs "defer until needed".
  - A. Implement now. ~80 LoC, tested by setting a low threshold (e.g. 500 tokens) for one manual smoke. *(recommended — closes the SPEC §4.7 compression story in one sprint)*
  - B. Defer. Stub stays in place; real impl lands when someone actually hits the context wall.

- **D3 — Session recovery.** User closes the browser mid-session; can they return with their token and continue?
  - A. Full recovery: on mount, if `session_token` already has conversation on disk, fetch it and replay.
  - B. No recovery in 6B. New session only. Recovery is a Sprint 7 deliverable alongside auth. *(recommended — scope discipline)*

- **D4 — End-session flow without email.** SPEC says email is optional in the survey.
  - A. Display summary inline in the chat as a final "session summary" bubble. Provide a "Copy to clipboard" button. If email was provided, log a TODO ("SMTP send arrives Sprint 7"). *(recommended)*
  - B. Require email before End Session.

- **D5 — Guardrails UI.** Sprint 6A counts violations; 6B surfaces them.
  - A. Banner above the chat box when `violations >= 2`; banner text in the session's language from the `guardrails.py` localised table. Session-ended flow at `violations >= 5` (configurable later).
  - B. No UI. Silent logging only.
  - *Recommended A with the thresholds above; we can tune later.*

- **D6 — Markdown rendering.** HRDD renders assistant output as markdown via `react-markdown` + `remark-gfm`.
  - A. Copy HRDD. Chat looks good out of the box (code blocks, lists, bold). *(recommended)*
  - B. Raw text only. Simpler but uglier.

### Implementation order

1. **Phase A — ChatShell skeleton + SSE streaming**. Bubble list, textarea, send button, EventSource connected. Smoke: submit a survey from the real UI, see the response stream in.
2. **Phase B — End-session + user summary** (backend `/close` endpoint + frontend button + summary bubble).
3. **Phase C — Real context compressor** (backend `should_compress`/`compress`; hook in polling).
4. **Phase D — File upload chips** (if D1=A).
5. **Phase E — Guardrails banner** (if D5=A).
6. **Phase F — Docs + smoke tests** (5-step checklist Daniel can run through).

### Risks

- **EventSource reconnect jitter**: browsers auto-reconnect every few seconds on disconnect. If the backend is still streaming, the client should pick up mid-response. Use a `last-event-id` only if we find it's needed.
- **Concurrent polling + SSE**: backend polls sidecar every 2 s; sidecar's SSE queue has a 30 s keepalive. In practice tokens arrive faster than the keepalive; no stall expected.
- **Compressor silently truncating context**: if enabled but misconfigured, could eat real content. Add a log line on every compression with before/after token counts so behaviour is observable.

---

## Sprint 6A — COMPLETE

**Goal (MILESTONES §Sprint 6):** Full chat works end-to-end — user submits survey → chat starts with initial query → AI streams response grounded in RAG + knowledge + survey context.

### Deliverables (all ✓)

- [x] `services/session_store.py` — disk-backed (`session.json` + `conversation.jsonl`), in-memory cache, atomic writes, `destroy_session` rmtrees the whole session tree (ADR-005).
- [x] `services/llm_provider.py` — OpenAI-compatible streaming for lm_studio / ollama / api (anthropic | openai | openai_compatible). Per-slot circuit breaker (3 fails in 60 s → 300 s cooldown). Fallback cascade per Daniel's rule: `[own, summariser, inference, compressor]` deduplicated → inference falls back `inference → summariser → compressor`.
- [x] `services/prompt_assembler.py` — 7-layer assembly using Sprint 4B resolvers + Sprint 5 RAG queries. Layers: core → guardrails → role (cba_advisor.md or compare_all.md) → context_template (survey vars incl. derived `comparison_scope_line` and `identity_block`) → glossary → organizations → RAG chunks. Session RAG is queried alongside permanent scopes when `session_token` is provided.
- [x] `services/polling.py` — replaces Sprint 4A's health-only loop. Every 2 s: per-frontend health check + queue drain. Dispatches by message `type`: `survey` → init session + inject initial_query; `chat` → dispatch turn. Turn handler: guardrails check → persist user msg → assemble prompt → persist system_prompt → stream LLM → relay tokens to sidecar → persist assistant msg → push `done`.
- [x] `services/guardrails.py` — HRDD hate-speech + prompt-injection regex patterns, CBC-themed localised responses (en/es/fr/de/pt). Log-only in 6A; violations counter in session metadata. Daniel flagged the rules for post-smoke tuning.
- [x] `services/context_compressor.py` — stub with `should_compress` + `compress` signatures so the import graph is stable. Real implementation is 6B.
- [x] Sidecar: `POST /internal/chat` (chat turn enqueue), `POST /internal/stream/{token}/chunk` (backend pushes SSE events), `GET /internal/stream/{token}` (React EventSource endpoint with 30 s keepalive comments). One asyncio.Queue per session token (D1=A serial; second message queues behind first).
- [x] `main.py` swaps `polling_loop` → `polling`; old `polling_loop.py` deleted.

### Acceptance tested end-to-end

- Submitted a survey via `POST http://localhost:8190/internal/queue` for session `SPRINT6A-SMOKE` with `company=amcor, country=AU, initial_query="What does the Amcor Australia CBA say about overtime?"`.
- Opened SSE reader: `curl -N http://localhost:8190/internal/stream/SPRINT6A-SMOKE`. **60+ `token` events streamed in real time** from LM Studio's `google/gemma-4-26b-a4b` via the backend.
- Response grounds in the company RAG — **cites `amcor_au_2024.txt`** as the source (the metadata-tagged AU doc uploaded in Sprint 5).
- `session.json` dumped: 12 588-char `system_prompt` with all 7 layers present; conversation.jsonl has both turns (`user` + `assistant`); survey + frontend_id persisted; `initial_query_injected: true` so polling won't re-inject.
- Fixed a template bug mid-smoke: `context_template.md` uses `{comparison_scope_line}` and `{identity_block}` as optional blocks; renderer now computes these from survey fields (empty when anonymous / not Compare All) and collapses blank lines.

### Deviations from plan

- `context_template.md` template vars (`comparison_scope_line`, `identity_block`) weren't originally in my flat-substitution list — caught during smoke test, fixed. Template still uses naive `{var}` replacement (no Jinja).
- Circuit breaker + fallback cascade are implemented but the happy-path smoke doesn't exercise them (LM Studio was online throughout). A deliberate fault-injection test is future work.

---

**Why split:** Sprint 6 touches 7+ services + sidecar + React UI (~3400 LoC of HRDD source to adapt). Keeping the backend/SSE loop in one sprint (6A) lets us verify the engine via curl before layering the chat UI (6B). Sprint 4 followed the same split-for-verifiability pattern.

### Decisions locked (2026-04-20)

- **D1 = A** — SSE keyed by `session_token` (serial: one response at a time per session; parallel messages queue).
- **D2 = A** — Send full conversation history to the LLM. Context compressor lands in 6B; demo conversations won't hit 20 k tokens.
- **D3 = Modified A** — Fallback cascade by slot. Daniel's rule: for the `inference` slot, fallback is `inference → summariser → compressor` (summariser is more capable and handles chat better; in prod everything runs on Ollama). Generalised: every slot's chain is `[own, summariser, inference, compressor]` deduplicated → so `summariser` falls back `summariser → inference → compressor`, `compressor` falls back `compressor → summariser → inference`.
- **D4 = A** — HRDD asyncio.Queue per session + POST chunk + GET stream. (Only pull-inverse-safe option — dropped as "decision" in future planning.)
- **D5 = A** — Backend auto-injects the survey's `initial_query` as the first user message when it first polls a new session (HRDD pattern).
- **D6 = A** — 6A skips end-session entirely. Sessions stay `active`; 6B adds End-session button + user summary generation.
- **D7 = C** — Full HRDD-style runtime guardrails (`services/guardrails.py`): regex rules copied from HRDD as the starting point, Daniel will review + tune the trigger list after smoke tests. Reasoning: CBC is lower-risk than HRDD (research tool, not public-facing), but keeping the runtime belt-and-suspenders layer is cheap and already-proven code.

### Decision options (for reference)

### 6A deliverables

**Backend (adapted from HRDDHelper/src/backend/services/):**
- `services/session_store.py` — per-token session metadata + conversation.jsonl append log. Atomic writes. Integrates with `session_rag.destroy_session` on auto-destroy.
- `services/llm_provider.py` — 3-slot (inference/compressor/summariser) OpenAI-compatible streaming. Circuit breaker per slot. Fallback cascade (inference → compressor → summariser) on health failures. Reads per-frontend override via Sprint 4B `llm_override_store.resolve_llm_config(fid)`.
- `services/prompt_assembler.py` — rewrite from HRDD's 2-tier → 3-tier using Sprint 4B `resolvers.resolve_prompt`. Assembles: `core + guardrails + role_prompt + context_template(survey vars) + glossary + orgs + RAG_chunks`. Compare All uses `compare_all.md` at role slot and stacks company RAG queries.
- `services/polling.py` — replace Sprint 4A health-only loop. Adds: dequeue messages per registered frontend, dispatch to LLM pipeline, push SSE tokens back. Initial-query injection on first poll (D5=A).
- `services/guardrails.py` — keyword/pattern checks (no legal advice, no CBA-term fabrication). Count triggers per session; surface via session metadata for 6B UI warning.
- `services/context_compressor.py` — stub in 6A (import + hook). Real compression lands alongside summariser in 6B or Sprint 7.

**Sidecar (adapted from HRDDHelper/src/frontend/sidecar/main.py):**
- `POST /internal/stream/{session_token}/chunk` — backend pushes a token chunk to the session's SSE queue.
- `GET /internal/stream/{session_token}` — React EventSource connects here; sidecar streams queued tokens with `text/event-stream` media type. One open stream per token.
- `POST /internal/queue` extension — accepts `{session_token, message, language}` for chat turns (not just surveys).

**Curl-testable smoke (6A acceptance):**
- `curl POST /internal/queue` (survey) → backend polls → session_store creates session → initial_query enqueued → prompt assembled with RAG → LLM streams → sidecar SSE endpoint emits tokens observable with `curl -N`.

### 6B deliverables (follow-up sprint)

- `frontend/src/components/ChatShell.tsx` — adapted from HRDD. EventSource connection, streaming render, message send, "End session" button.
- End-session flow — summariser slot generates user summary; stored in session + (stubbed) emailed. Real SMTP lands Sprint 7.
- Context compressor real implementation (progressive thresholds from LLM settings).
- Guardrails UI: warning banner when trigger count exceeds threshold.

### Decisions to lock before 6A kickoff

- **D1 — SSE keying.** `session_token` (one stream per session at a time; second message from same session queues behind first) vs client-generated `message_id` (parallel streams). *Recommend A = session_token; matches HRDD, chat is serial by nature.*

- **D2 — Conversation history window.** Send ALL history to LLM + rely on context compression (A), fixed N-turn window (B), token-count estimate (C). *Recommend A; compressor already budgeted for 6B. Demo conversations won't exceed 20k tokens.*

- **D3 — LLM fallback cascade.** Copy HRDD's `inference → compressor → summariser` cascade on health failures (A) vs error-out when configured slot fails (B). *Recommend A; proven pattern, handles "local LLM died mid-chat" gracefully.*

- **D4 — SSE relay pattern.** Copy HRDD's asyncio.Queue per session + POST chunk + GET stream (A). No alternatives worth considering; WebSockets / direct-server-stream break the pull-inverse rule. *Default A.*

- **D5 — Initial query handling.** Backend auto-injects survey's `initial_query` as the first user message when it first polls a new session (A) vs React submits survey AND separately sends the message (B). *Recommend A; matches SPEC "initial query injection", one network round-trip, cleaner UX.*

- **D6 — End-session flow scope for 6A.** Skip entirely — session stays `active`, 6B adds End-session button + summary generation (A). Or stub: add `POST /api/v1/sessions/{token}/close` that just marks state='completed' without summary (B). *Recommend A; keeps 6A tight. User summary lands with 6B where it's visible in the UI.*

- **D7 — Guardrails rules source.** Hardcode rules in `guardrails.py` (A, HRDD pattern) vs JSON-configurable rules (B). *Recommend A; v1 rules are stable. Admin-configurable rules are Sprint 8+ if needed.*

### Implementation order (6A)

1. **Phase A — session_store** (adapt HRDD). Smoke: create session, append messages, destroy.
2. **Phase B — llm_provider** (adapt HRDD streaming). Smoke: `await provider.stream_chat(messages, slot)` against LM Studio returns tokens.
3. **Phase C — prompt_assembler** (3-tier rewrite). Smoke: render for a fake session → inspect assembled prompt text.
4. **Phase D — sidecar SSE endpoints**. Smoke: `curl -N` on `/internal/stream/{token}` stays open; `curl -X POST /internal/stream/{token}/chunk` delivers.
5. **Phase E — polling.py** (rewrite). Smoke: queue a survey → backend processes → SSE observable from sidecar.
6. **Phase F — guardrails + context_compressor stub**. Add hooks; real rule-firing UI in 6B.
7. **Phase G — docs** (SPEC confirm, CHANGELOG, STATUS).

### Risks / open questions
- **Pitfall 2** (message TTL): default 300s; if LLM is slow + polling interval 2s we have headroom. Monitor.
- **Pitfall 4** (circuit breaker): adapt HRDD's cleanly; 3 fails in 60s → 300s cooldown.
- **Pitfall 5** (prompt order): core + guardrails ALWAYS first, even when company-tier overrides role_prompt. Enforce in `prompt_assembler.assemble()`.
- **Pitfall 10** (Compare All context blowup): deferred — Sprint 6A's RAG top-k is 5 per scope; Compare All with 5 companies = 25 chunks + history. Well within 20k-token window for v1. Revisit if chat blows up.
- SSE connection resilience: browser reconnect on network blip. HRDD handles this via EventSource's automatic reconnect; we inherit it. Sidecar cleans up queues when GET stream exits.

---

## Sprint 5 — COMPLETE

**Goal (MILESTONES §Sprint 5):** RAG indexing works at all 3 tiers; file watcher detects disk changes and triggers debounced reindex; session RAG; document metadata; Compare All filtering by country.

### Deliverables (all ✓)
- [x] `services/rag_service.py` — LlamaIndex 3-tier, in-memory cache per `scope_key`, lazy load
- [x] `services/rag_watcher.py` — watchdog + per-scope 5s debounce + iCloud/Office/vim/DS_Store filter + write-event-only filter (fixes self-triggering rebuild loop)
- [x] `services/session_rag.py` — per-session index + destroy_session rmtree
- [x] `services/document_metadata.py` — per-directory `metadata.json` + `derive_country_tags`
- [x] `api/v1/sessions/uploads.py` — `POST /api/v1/sessions/{token}/upload` + list + destroy
- [x] Sidecar `POST /internal/upload` — relays multipart to backend via `cbc-backend:8000`
- [x] Admin `api/v1/admin/rag.py` — metadata GET/PUT/DELETE routes; stats + reindex return `indexed` + `node_count`
- [x] `rag_store.py` bridged to real indexer: upload/delete invalidate cache, reindex rebuilds
- [x] `requirements.txt` + `Dockerfile.backend`: torch CPU-only first, LlamaIndex + sentence-transformers + watchdog + pypdf + docx2txt, embedding model pre-downloaded in build step
- [x] Admin UI: per-document metadata editor in `RAGSection` (company tier only); `CompanyManagementPanel` country chips now live (placeholder note removed)

### Acceptance tested end-to-end
- Global tier: 3 docs → 39 nodes; query returns ranked chunks with scope tagging.
- Frontend + company tiers: empty scope handled cleanly; query returns [].
- File watcher: single file create → 1 debounced reindex; delete → reindex; bulk 3-file drop → 1 reindex; `.icloud`/`.DS_Store`/`._*` filtered (no log entries).
- Write-event-only filter stops the feedback loop where the indexer's own file reads were re-scheduling rebuilds.
- Document metadata: write `country=AU` for one amcor doc → `amcor.country_tags` becomes `['AU']`; add `country=US` doc → `['AU', 'US']` (correctly replaces stale hardcoded chips).
- Session RAG: `POST /internal/upload?session_token=TEST-1234` with a text file → returns `{upload: {...}}`; `GET /api/v1/sessions/TEST-1234/uploads` lists it; `session_rag.query('TEST-1234', 'vacation weeks?')` returns the chunk with score 0.306.
- Compare All: `national` mode with user_country=DE (no matching company) returns frontend + global only; `AU` matches amcor; `global` mode returns every enabled company.

### Deviations from milestone
- None. All 13 acceptance criteria hit. One re-phrasing: the criteria were worded in terms of the old `rag_mode=combine_all`/`own_only`; post-Sprint-4 polish renamed these to two booleans (`combine_frontend_rag` + `combine_global_rag`). Behaviour identical — both ticked ≡ combine_all; both unticked ≡ own_only. Acceptance text updated in MILESTONES.

---

### Decisions locked (2026-04-19)

- **D1 = A** — Per-directory `metadata.json` mapping `filename → {country, language, document_type}`.
- **D2 = A** — `country_tags` auto-derived on reindex and persisted back to the Company record. Live chips in admin (placeholder note disappears).
- **D3 = A** — Session RAG under `/app/data/sessions/{token}/{uploads,rag_index}/` — one tree per session so auto-destroy is a single rmtree.
- **D4 = A** — Per-scope 5s debounce in the file watcher.
- **D5 = A** — Pre-download `all-MiniLM-L6-v2` in `Dockerfile.backend` build step. Keep HRDD's `torch` CPU-only install BEFORE `sentence-transformers` to avoid the 5 GB CUDA bloat.
- **D6 = A** — Full session upload pipeline this sprint (sidecar → backend → ingest), curl-tested. Chat UI upload button is Sprint 6.

### Decision options (for reference)

- **D1 — Document metadata format.**
  - A. Per-directory `metadata.json` mapping `filename → {country, language, document_type}`. One file per documents/ folder. *(my recommendation — single source per scope, easy to edit by hand)*
  - B. Companion `.meta.json` per file (one alongside each PDF).
  - C. Read PDF embedded metadata (more complex, less reliable).

- **D2 — `country_tags` auto-derivation.**
  - A. On reindex, aggregate unique `country` values from metadata.json and persist back to the Company record. The chip list in CompanyManagementPanel becomes live (the Sprint 4B "Sprint 5" placeholder note disappears). *(recommended)*
  - B. Compute on-the-fly when the resolver needs it (no persistence).
  - C. Drop auto-derive — keep `country_tags` admin-edited manually.

- **D3 — Session RAG storage layout.**
  - A. `/app/data/sessions/{token}/{uploads,rag_index}/` — everything per session under one tree (cleaner auto-destroy). *(recommended)*
  - B. `/app/data/session_rag/{token}/...` separate from the session's metadata folder.

- **D4 — File watcher debouncing.**
  - A. **Per-scope** 5s debounce — bulk-copying to one company doesn't trigger reindex on unrelated scopes. *(recommended)*
  - B. Global single 5s debounce, then rebuild every affected scope at once.

- **D5 — Embedding model packaging.**
  - A. Pre-download `all-MiniLM-L6-v2` in `Dockerfile.backend` build step (no cold start; image grows ~90 MB). *(recommended)*
  - B. Download on first use (smaller image, slower first query, needs internet at runtime).

- **D6 — Session upload endpoint scope.**
  - A. Build the full pipeline now: sidecar `POST /internal/upload` → backend `POST /api/v1/sessions/{token}/upload` → session RAG ingest. Smoke-test with curl. Sprint 6 wires the UI. *(recommended — closes Sprint 5 acceptance "Session RAG: user uploads document → queryable in that session only")*
  - B. Defer to Sprint 6; Sprint 5 only ships the session RAG service callable from Python.

### Deliverables (assuming default A on every D)

**Backend new:**
- `services/rag_service.py` — LlamaIndex-based, scope-aware (uses Sprint 4B `resolvers.resolve_rag_paths`), in-memory cache keyed by `scope_key`.
- `services/rag_watcher.py` — watchdog observer over `/app/data/`, scope detection from path, per-scope 5s debounce, iCloud filter (`*.icloud`, `.DS_Store`, `._*`, `*.tmp`, `*.swp`, `~$*`).
- `services/session_rag.py` — per-session indexing + queryable + destroy.
- `services/document_metadata.py` — read/write `metadata.json`, derive country tags.
- `api/v1/sessions/uploads.py` — session upload endpoint.

**Backend modified:**
- Replace `services/rag_store.py` reindex stub with calls into the real `rag_service`.
- `api/v1/admin/rag.py` — metadata GET/PUT routes, real reindex returns real stats.
- `main.py` — start file watcher in lifespan, ensure clean shutdown.
- `services/company_registry.py` — accept country_tags writes from rag_service (auto-derive path).
- Sidecar `POST /internal/upload` (multipart) → forwards to backend.
- `requirements.txt`: add `llama-index-core`, `llama-index-embeddings-huggingface`, `sentence-transformers`, `watchdog`, `pypdf`, `python-docx`.
- `Dockerfile.backend`: pre-download embedding model in a separate layer.

**Admin UI:**
- `RAGSection`: per-document metadata editor (country / language / document_type) — only meaningful at company tier.
- `CompanyManagementPanel`: country_tags chips become live (no more placeholder note); read-only display showing what was auto-derived.

**Frontend (sidecar smoke only — no UI):**
- Sidecar `POST /internal/upload` and a curl recipe in CHANGELOG. Chat UI upload button is Sprint 6.

### Implementation order

1. **Phase A — Indexing core**: deps + `rag_service.py` + replace `rag_store.py` reindex + admin route → smoke: upload PDF, reindex, query.
2. **Phase B — File watcher**: `rag_watcher.py` + main.py lifespan + iCloud filter test.
3. **Phase C — Document metadata + country auto-derive**: `document_metadata.py` + admin UI editor + Company.country_tags update on reindex.
4. **Phase D — Session RAG**: `session_rag.py` + sidecar upload + backend ingest + curl smoke.
5. **Phase E — Compare All filtering**: already in Sprint 4B resolver (company-level); verify chunks for `national` mode only come from country-matched companies.
6. **Phase F — Docs**: SPEC §4.2/§4.3 confirmation, CHANGELOG, STATUS close.

### Risks / open questions
- **Pitfall 7** (lessons-learned): RAG rebuild storms — debouncer + scope-rebuild only.
- **Pitfall 8**: iCloud filter must be in the watcher.
- **Pitfall 10**: Compare All can balloon token usage — Sprint 6's prompt assembler + context compressor handle that, not Sprint 5. Sprint 5 just exposes the chunks.
- LlamaIndex API surface area — version pin in requirements, mirror HRDD's known-good imports (`llama_index.core.VectorStoreIndex`, `llama_index.embeddings.huggingface.HuggingFaceEmbedding`).

---

## Sprint 4 — Post-sprint polish (2026-04-19, commit `74cdb01`)

Round of UX cleanup driven by Daniel walking through the admin panel after the Sprint 4B build. Backend semantics didn't change — same resolver behaviour, same data flows, just the admin UX simplified.

- **Auto-IDs everywhere.** Frontend registration: URL + display name only (`frontend_id` slug auto-derived in backend, `-2`/`-3` on collision). Company creation: display name only (slug auto-derived the same way). Admin never types or sees an internal ID. Frontend containers are now anonymous — no `CBC_FRONTEND_ID` baked in or required.
- **Prompts: same canonical menu at every tier.** Sidebar always shows the 6 canonical prompts (now including `summary.md`). Tier badge per row indicates where it currently resolves. Save commits at the current tier; "Remove this-tier override" appears only when the current tier owns the file. Company tier hides `compare_all`/`summary` and only allows `cba_advisor` edits (backend enforces).
- **Session settings: dropped null/inherit.** Concrete defaults (48/72/0 hours, all toggles ON). Plain checkboxes for bools, plain numeric inputs with inline help on time fields.
- **RAG: unified "Combine RAG" subsection.** Replaced the 5-value `rag_mode` enum + `global_rag_mode` dropdown with checkboxes — `Global` at frontend tier, `Frontend` + `Global` at company tier. Both default true. Per-field merge with backwards-compat migration.
- **Companies: alphabetical order**, Compare All first. Dropped `sort_order` field.
- **Per-frontend LLM: per-slot override.** Mirrors the global LLM editor with one Override checkbox per slot (Inference / Compressor / Summariser). Unchecked → greyed inheriting display, checked → editable. Compression + routing always inherit from global at frontend tier. Backend `LLMOverride` model is per-slot optional. `SlotEditor` + `ProviderCard` extracted to `components/llm/` shared.
- **Branding: per-field merge** (empty fields inherit instead of clobbering); collapsible cards with chevron at both global and per-frontend; `org_name`/`disclaimer_text`/`instructions_text` fields added end-to-end. Default branding header now uses the UNI Global monochrome logo + i18n disclaimer/instructions adapted from HRDD to CBC's bargaining-research domain.
- **Migrations**: legacy data on disk (`prompt_mode` field, full-config LLM overrides, 5-value `rag_mode`, `global_rag_mode`, `sort_order`, etc.) loads without error — all dropped or translated on read.
- **SPEC** §4.9 + §9.1 + §5.1 (Tab 2) updated for the auto-ID model, multi-frontend deploys, per-frontend LLM override.

---

## Sprint 4B — COMPLETE

**Decisions locked at start:**
- D1 = A — `PromptsSection` + `RAGSection` refactored to accept optional `{frontendId, companySlug}`. Same UX across tiers.
- D2 = B — Per-frontend LLM override = single "Override global config" checkbox that snapshots the global config into an editable JSON.
- D3 = A — Per-company content lives in a collapsible row inside `CompanyManagementPanel`.
- D4 = A — Preview endpoints + buttons in every tier-aware panel.
- `rag_standalone: bool` added to `SessionSettings` (backend-only — not pushed to sidecar).

**Resolver semantics (SPEC §2.4):**
- Prompts = winner-takes-all (company → frontend → global). `compare_all.md` skips company tier.
- RAG = stackable per `company.rag_mode` + `frontend.rag_standalone`.
- Orgs = mode-based per frontend: inherit / own / combine.
- LLM = all-or-nothing per frontend (snapshot of global when admin enables override).

### Deliverables
- [x] `services/resolvers.py` — `resolve_prompt`, `resolve_rag_paths`, `resolve_orgs`
- [x] `services/orgs_override_store.py`
- [x] `services/llm_override_store.py` (+ `resolve_llm_config(frontend_id)`)
- [x] `SessionSettings.rag_standalone` field (backend-only; excluded from sidecar push)
- [x] `api/v1/admin/resolvers.py` — preview endpoints for prompt / RAG / orgs
- [x] `api/v1/admin/frontends.py` extended with orgs + LLM override CRUD
- [x] `main.py` wires resolvers router
- [x] Admin `api.ts` refactored: polymorphic `listPrompts/readPrompt/savePrompt/deletePrompt` + `listRAG/uploadRAG/deleteRAG/getRAGStats/reindexRAG` accept `(frontendId?, companySlug?)`. New clients for orgs override, LLM override, and previews
- [x] `PromptsSection.tsx` + `RAGSection.tsx` accept tier props; heading/description/buttons per tier; "Preview resolution" button; "Delete override" button on non-global tiers
- [x] `panels/PerFrontendOrgsPanel.tsx` (mode selector, JSON download/upload, preview resolution)
- [x] `panels/PerFrontendLLMPanel.tsx` (override checkbox snapshots global; JSON download/upload for edits)
- [x] `CompanyManagementPanel.tsx`: "Show content" row toggle renders PromptsSection + RAGSection with `{frontendId, companySlug}`
- [x] `SessionSettingsPanel.tsx` gains `rag_standalone` toggle
- [x] SPEC §2.4 rewritten; §4.9 notes `rag_standalone`; §6.2 unchanged
- [x] MILESTONES Sprint 4 fully green

### Acceptance tested (curl + admin UI build)
- Prompt: no override → `tier=global`; create frontend-level override → `tier=frontend` for both frontend and company queries; add company-level override for amcor → `tier=company` for amcor, other companies still `tier=frontend`; `compare_all.md` with `compare_all=true` skips company tier
- RAG: single-company amcor (default `combine_all`) → `[company, frontend, global]` stack; Compare All → `[company×N, frontend, global]`; toggle `rag_standalone=true` → `global` dropped from stack
- Orgs: no override → `mode=inherit, count=7` (global list size)

---

## Sprint 4A — COMPLETE

---

## Sprint 4A — COMPLETE

**Decisions locked at sprint start:**
- D1 = A — HRDD-style: admin registers each frontend manually (URL + name + stable `frontend_id`). Auto-registration was rejected because it would require the frontend to know the backend URL, violating the "frontend doesn't know backend" rule.
- D2 = A — Push immediately on save. Backend POSTs branding / session-settings to sidecar; sidecar caches and merges into `/internal/config`. HRDD pattern.
- D3 = health-only polling. Full message-queue polling stays Sprint 6.
- Side-effect: `backend_url` removed from `deployment_frontend.json` and sidecar — it was unused and violated the architectural rule.

### Deliverables
- [x] `services/frontend_registry.py` (keyed by stable `frontend_id`, not a random hex ID)
- [x] `services/polling_loop.py` (health-check every 5s)
- [x] `services/branding_store.py`
- [x] `services/session_settings_store.py`
- [x] `api/v1/admin/frontends.py` (registry CRUD + per-frontend branding + session-settings, with POST push to sidecar on save)
- [x] Sidecar `POST /internal/branding`, `POST /internal/session-settings`, `/internal/config` merges pushed overrides with baseline JSON
- [x] Deleted `services/frontends.py` scanner + `/admin/api/v1/smtp/frontends` endpoint
- [x] Removed `backend_url` from `deployment_frontend.json` + sidecar
- [x] `main.py` wires polling loop in lifespan with clean cancellation
- [x] Admin `FrontendsTab.tsx` rewrite: registered-list with status dots + register form + selected-frontend panels
- [x] `panels/BrandingPanel.tsx`
- [x] `panels/SessionSettingsPanel.tsx` (session hours + feature toggles, per-field inherit)
- [x] `panels/CompanyManagementPanel.tsx` (UI for Sprint 3 companies CRUD — inline rag_mode/prompt_mode + country tags + enable flag)
- [x] `api.ts` extensions (`FrontendInfo`, register/update/delete, branding + session-settings CRUD)
- [x] SPEC §4.9 rewritten with push pattern; MILESTONES Sprint 4 acceptance split by 4A/4B
- [x] ADR-007 criterion resolved: smoke-tested — registered frontend `packaging-eu` detected online by polling in <6s

### Acceptance tested (curl end-to-end on `localhost:8100` + `localhost:8190`)
- [x] `POST /admin/api/v1/frontends` registers; `GET` lists; polling flips status → `online` within 5s
- [x] `PUT /admin/api/v1/frontends/{fid}/branding` persists + pushes → sidecar `/internal/config` shows the custom branding
- [x] `PUT /admin/api/v1/frontends/{fid}/session-settings` with some overrides + some `null` → sidecar merges: overridden fields use override, null fields inherit from `deployment_frontend.json`
- [x] `DELETE /admin/api/v1/frontends/{fid}/branding` → sidecar falls back to baseline branding

---

## Sprint 4B — PLANNED

**Scope:** per-frontend content overrides + 3-tier resolvers
- Per-frontend prompts UI (wrap Sprint 3 backend routes)
- Per-frontend RAG docs UI (wrap Sprint 3 backend routes)
- Per-frontend organizations override (global / own / combine)
- Per-frontend LLM override (HRDD per-frontend pattern, 3 slots + compression + routing)
- Per-company prompts + RAG documents (expand CompanyManagementPanel)
- Backend resolvers: `resolve_prompt(name, fid, slug)` + `resolve_rag(fid, slug)` + preview endpoints

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
