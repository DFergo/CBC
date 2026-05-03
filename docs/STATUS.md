# CBC — Project Status

**Current Sprint:** 18 — **Fases 1+2+3 PUSHED 2026-05-01; Fase 4 CODE DONE 2026-05-03** (Top-K + watcher knobs admin-editables vía sliders en `Admin → General → RAG Pipeline → Tuning avanzado`). Pendiente push + Daniel valida. Pipeline:
1. Top-K dinámico (5→40 cap, scaling por num_files_in_scope).
2. Watcher debounce robusto (5 s→30 s default, 5-min hold ceiling, lock-aware re-plan).
3. **Chunking legal-aware** — `_segment_by_clause` pre-pass detecta Art. N / Artículo N / Article N / Cláusula N / Clause N / Section N.N.N / ANEXO I / Annexe N. Cada clause queda en su propio pseudo-doc al SentenceSplitter → no se parte mid-clause. `clause_id` propagado a metadata + `Chunk.clause_id` + citation panel lo usa como locator prioritario sobre el regex previo.

Probado en vivo: CBA Lezo → 75 clause segments (Art. 1 a 72 + ANEXO II + III). FR docs con numeración → detectados; FR docs sin numeración → fall-through OK. AU sample SECTION 13.4.1 → detectado.

Antiguas fases 4-5 (modo catálogo, query rewriting cross-lingüe, glossary técnico-legal, MVCC chat protection) parked en IDEAS.md — decidiremos tras validar 1+2+3. Sprint 17 CLOSED 2026-04-24.
**Last Updated:** 2026-05-01

## Sprint 16 — Structured Table Pipeline + concurrency fixes

### Fase 0 — Admin reindex no longer blocks the event loop (code done 2026-04-24)

5 reindex endpoints in `api/v1/admin/rag.py` wrap their sync work in `asyncio.to_thread(...)`: `reindex`, `reindex-all`, `reindex-frontend-cascade/{fid}`, `wipe-and-reindex-all` (already in Sprint 15 phase 6, tidied), `settings/contextual` (happy + rollback). Admin UI + `polling_loop` stay responsive during long reindex jobs.

### Fase 0.b — Duplicate-chunks fix + CR off by default (code done 2026-04-24)

**Duplicate chunks:** `_build_index` now serialised per-scope via a new `_build_locks` dict. Without this, two concurrent callers (e.g. a wipe-and-reindex thread + a chat `get_index()` query) both entered, both cleared the scope (no-op on empty), and both inserted 44 nodes → 88. Every subsequent wipe compounded. Verified in live container (88 → 44 × 2 duplicates).

**CR default:** `rag_contextual_enabled` was already `False` in code; the comment now reflects that Sprint 16's table pipeline covers CR's painful use case. Runtime override may still have it `True` on existing deploys — Daniel toggles OFF once from the admin UI to clear it.

### Fases 1-9 — Structured Table Pipeline (code done 2026-04-24)

Tables extracted from `.md` (regex pipe-table + heading chain) and `.pdf` (pdfplumber) at ingest. Each persists as `{scope}/tables/{doc_stem}/{table_id}.csv` + `manifest.json`. Metadata cards embed into a new `cbc_tables` Chroma collection on the same client as `cbc_chunks`. Prompt assembler calls `rag_service.query_tables(scope_keys, q, top_k=2 or 4)` alongside the prose query and emits a `## Relevant tables` section with each CSV fenced (6 000 chars cap per table). Table hits flow to the `sources` SSE event with `kind: "table"` + `table_id` + `source_location`; the `CitationsPanel` renders them with an amber "Table" badge. Admin router `api/v1/admin/tables.py` exposes GET-list (with 5-row previews), POST-reextract (via `asyncio.to_thread`), and GET-csv at all three tiers. Admin UI `TablesSection` mounted in `GeneralTab` / `FrontendsTab` / `CompanyManagementPanel`, with 12 new i18n keys in EN + ES.

CR stays off by default; the admin toggle remains for users who want to experiment on prose-heavy corpora.

**Scope delivered:**
- Backend: ~520 lines (table_extractor, rag_service extensions, tables admin router)
- Admin UI: ~250 lines (TablesSection + api.ts + i18n)
- Frontend: ~60 lines (CitationsPanel + types + i18n)
- 1 new dep: `pdfplumber>=0.11` (pure Python, no Dockerfile change)

**Validation pending Daniel after Portainer repull:** full checklist in the latest CHANGELOG entry.

## Upcoming sprints (planned, not started — see MILESTONES.md for full scope)

- **Sprint 17 — Living ARCHITECTURE.md.** Dual-use doc (Claude + Daniel as operator) referenced in CLAUDE.md, maintained via extended `/sprint` workflow. Ten sections including an Admin UI map that maps every admin toggle to backend file + persistence + service. Half a day.

## Sprint 15 — RAG chunker fix + observability

### Why this sprint exists

Daniel's QA after Sprint 14 deploy showed persistent +60-90 s TTFT even on a single-user single-CBA test. Backend log said `prompt assembled: 133232 chars, 1 RAG chunks`. I pulled the live `session.json` from OrbStack: 94 % of those 133 232 chars (125 204 to be exact) is a single section `## Retrieved CBA / policy excerpts`. The CBA.md file on disk is 127 196 chars. **The "retrieved" section is basically the entire CBA, not excerpts.**

Confirmed empirically via `docker exec` + SQLite queries on Chroma:
- `cbc_chunks` Chroma collection contains **one single embedding of 125 095 chars** for the CBA (not 120+ chunks as the 1024-token chunking would imply).
- `BGE-M3` has `max_seq_length=8192` tokens; our stored chunk is ~30 000 tokens → the embedding has been **silently truncated to the first 8 k tokens** at ingest time. Semantically, retrieval only "sees" the first ~30 % of the document. At 200 CBAs this will be catastrophic — each document reduced to a lossy first-30 % embedding.
- The "1 RAG chunks" log is accurate: retrieval returns top-k from a collection that only has 1 chunk to give.

### Root cause (confirmed)

`CBCopilot/src/backend/services/rag_service.py:257`
```python
md_parser = MarkdownNodeParser()
```

`MarkdownNodeParser` splits only on markdown headers and **does not respect `Settings.chunk_size`** (global 1024-token setting is ignored by header-based parsers). A CBA structured with few top-level headers (or with ANEXO I as a huge section under one `#` heading) emits as one giant node. `.pdf` and `.txt` files take the sibling path at line 260-263 (`SentenceSplitter` with `chunk_size=backend_config.rag_chunk_size`), which caps correctly — which is why Daniel's instinct to try PDF would work as a workaround.

HRDD Helper (sibling repo) doesn't have this bug because `HRDDHelper/src/backend/services/rag_service.py` routes everything through `VectorStoreIndex.from_documents(..., chunk_size=...)` (single path, always capped). CBC's Sprint 9 RAG overhaul introduced the per-extension routing to preserve markdown header context — the intent was good, the implementation was asymmetric.

### Scope of fix

**1 — Chunker fix** (`rag_service.py`, ~5 lines)

After `MarkdownNodeParser` produces header-structured nodes, pipe them through a `SentenceSplitter(chunk_size=1024, chunk_overlap=200)` so any header-node exceeding 1 024 tokens is further split. Header metadata is preserved on every sub-node (important for Sprint 11 Phase B inline citations that reference article / page numbers). Pattern:

```python
md_nodes = md_parser.get_nodes_from_documents(markdown_docs)
from llama_index.core.schema import Document
final_md_nodes = []
for node in md_nodes:
    sub_docs = [Document(text=node.text, metadata=node.metadata)]
    sub_nodes = sentence_parser.get_nodes_from_documents(sub_docs)
    final_md_nodes.extend(sub_nodes)
```

Result: a 125 k-char CBA splits into ~120 chunks of ≤1 024 tokens each, properly embedded by BGE-M3 without truncation.

**2 — Observability (logs across the pipeline)** — Daniel explicitly asked for these so future regressions are catchable without guessing:

- `rag_service._parse_nodes`: per-document log `doc={name} ext={.md|.pdf|...} nodes_produced=N max_chunk_chars=X min=Y mean=Z`
- `rag_service._build_index`: per-scope log `scope={key} docs=N total_nodes=M inserted=K time=Xs`
- `rag_service.query_scopes`: per-query log `query={first 60 chars} scopes=N top_k=K returned=M max_chunk_chars=X reranked_to=R`
- `rag_service` embedder: warn if any node exceeds BGE-M3's 8 192 tokens (defensive — should never happen post-fix)
- `prompt_assembler._render_chunks`: log `chunks_injected=N total_chars=X largest_chunk_chars=Y`
- `prompt_assembler.assemble`: enhance the existing log with a section-size breakdown (ID, Scope, Behavioural, Guardrails, Role, Context, Organizations, Retrieved, Citation — the same nine sections I sectionised live today). Makes future bloats visible in one log line.

**3 — Reindex trigger**

Existing indices on disk won't benefit from the fix until reindexed. Three options in order of preference:
- (a) Auto-reindex on backend startup if any scope's chroma collection has nodes whose `text` length exceeds `chunk_size × chars_per_token × 1.5`. Safety net, cost = one reindex at deploy.
- (b) Admin manual reindex via the existing button (Sprint 5 shipped it). Explicit.
- (c) Leave stale, wait for next admin-triggered reindex. Worst.

Recommend (a) + document (b) as alternative.

**4 — Self-tests I can run before + after fix** (no device needed from Daniel):

- `test_chunker_now.py` (scratchpad): load the CBA.md with current `_parse_nodes()`, report node count + sizes. Expected: 1 node, 125 k chars. Confirms current bug reproduces.
- `test_chunker_fixed.py`: same load with proposed fix applied, report node count + size distribution. Expected: ~120 nodes, all ≤4 500 chars, max ≤5 000 chars.
- `test_embed_truncation.py`: tokenise the 125 k-char chunk with BGE-M3's tokenizer, confirm token count > 8 192 (expected yes). Confirms embedding IS being truncated on the current data.
- `test_prompt_sim.py`: build a mock retrieval of 5 × 1024-token chunks, pass through `prompt_assembler._render_chunks`, measure resulting section size. Expected: ~20 k chars in retrieved section instead of 125 k.
- All four scripts written in this session's workdir, run via `docker exec cbc-backend-cbc-backend-1 python3 /tmp/...` so they use the actual container's LlamaIndex / BGE-M3 / Chroma.

**5 — Live verification (after Daniel deploys the fix):**
- Compare `prompt assembled: N chars` before/after on same query: expect drop from ~133 k to ~25-40 k chars.
- Compare TTFT on first question for same CBA + query: expect drop from ~90 s to ~20-30 s (5-7× less prefill work).
- Verify `1 RAG chunks` → `5 RAG chunks` or similar (top_k actually hitting multiple granular chunks).
- Verify no regression on Sprint 11 Phase B inline citations (header metadata must survive the secondary split).

### Files to modify (on approval)

- `CBCopilot/src/backend/services/rag_service.py` — chunker pipeline fix + observability logs (the largest single change, maybe 30 lines added including logs)
- `CBCopilot/src/backend/services/prompt_assembler.py` — observability logs only, no behavioural change
- `CBCopilot/src/backend/main.py` — auto-reindex-on-startup helper hook (small)
- `docs/CHANGELOG.md` + `docs/STATUS.md` — close Sprint 15
- No admin UI changes, no config schema changes, no migrations

### Constraints (re-stated)

- No code changes until Daniel approves the plan.
- No local `docker compose build` — Daniel re-pulls via Portainer.
- Session JSON files on disk don't need migration; they'll naturally regenerate the smaller system prompt on next turn once the index is rebuilt.

### Expected outcomes after deploy

- First-question TTFT: 60-90 s → 20-30 s (chunk + ctx drops, cold-load still counts)
- Re-question TTFT: prefix cache works fully → 3-10 s (matches Daniel's pre-Sprint-13 memory)
- Retrieval quality: ~120 granular embeddings per CBA vs 1 truncated → dramatic improvement for questions that reference later portions of the document
- Scales to 200 CBAs cleanly: top-k=5 always returns 5 granular chunks regardless of corpus size

### Implementation status (2026-04-24 evening)

- ✅ Chunker fix landed in `rag_service._parse_nodes` (SentenceSplitter second-pass over MarkdownNodeParser output).
- ✅ Observability logs landed in `rag_service.query`, `rag_service.query_scopes`, `rag_service._parse_nodes` (per-document chunk distribution), `prompt_assembler.assemble` (per-section size breakdown).
- ✅ Empirical validation via live-container test: real Amcor CBA.md (125 095 chars) now produces **45 chunks** (max 4 070 chars, mean 3 336 chars, all under BGE-M3's 8 192-token cap); metadata preservation confirmed (45/45 chunks carry `file_name` + `header_path`). Before fix: 1 chunk of 125 095 chars.
- ⏳ Pending Daniel: Portainer re-pull → admin panel "Reindex" for the Amcor scope → first-question test to measure TTFT improvement.

### Remaining items from the audit (separate plan — NOT in this Sprint 15 code)

Surfaced while investigating but out of scope for the chunker fix. Grouped so Daniel can pick when to tackle each:

**A — Auto-detect stale legacy indices (small, diagnostic only)**
On backend startup, scan each Chroma scope's chunks for any > 30 000 chars. If found, emit a WARNING log: "Scope X has pre-Sprint-15 oversized chunks, reindex recommended." Non-intrusive, no auto-action. Adds visibility without risking data. ~15 lines.

**B — Admin-panel "reindex needed" banner**
When the admin opens General → RAG, surface a red banner per scope that has any oversized chunk, with a one-click Reindex button next to it. ~30 lines frontend + small backend endpoint. Lives alongside the existing Sprint 5 reindex UX.

**C — GET /admin/api/v1/rag/diagnostics endpoint**
New admin read-only endpoint that returns per-scope chunk count, mean/max chunk chars, embedding-truncation risk flag. Drives diagnostic views or external monitoring. ~20 lines.

**D — Session RAG force-injection size cap**
`session_rag.get_chunks_for_files` currently injects EVERY chunk of the user-attached files (intended: "the model can't miss the file"). With the now-correct chunker, a 500-page PDF upload produces ~500 chunks and all 500 get force-injected. The prompt could exceed sane limits. Consider a `max_forced_chars` cap (say 20 000 chars) with a note to the model if truncated. Not urgent; user uploads are rare but scale-sensitive.

**E — BGE-M3 truncation config guard**
If an admin ever bumps `rag_chunk_size` above 8 192 tokens (configurable in `deployment_backend.json`), BGE-M3 will silently truncate embeddings. Add a startup validation that warns if `rag_chunk_size × 4` (chars-per-token heuristic) > 32 768 chars. ~5 lines.

**F — Prompt cache stability across turns (architectural)**
Every turn re-runs `prompt_assembler.assemble()` with the new query_text, which re-runs RAG retrieval. If related questions retrieve different chunks, the system prompt differs between turns → Ollama's prefix cache gets partial miss. Not introduced by recent work — pre-existing. With Sprint 15's fix, chunk sizes are smaller, so the delta impact is reduced. Any mitigation (cache retrieval per session, shorten system prompt, isolate RAG section) is a meaningful refactor. Investigate only if post-Sprint-15 re-question TTFT remains >15 s.

**G — Preload CBC's inference model in Ollama**
Independent of RAG: cold-load of qwen3.6:35b at NP=4 costs ~30-45 s. Preloading via `~/.ollama/preload.conf` eliminates this at the cost of ~45 GB always-resident RAM. Daniel's call when RAM budget is firmed up.

None of A-G block Sprint 15 closure. Each is a ~1-hour job if/when Daniel wants to schedule.

### Open questions for Daniel (non-blocking)

1. Keep `.md` as preferred ingest format? With the fix in place, MD now chunks correctly — no need to switch to PDF unless there's another reason. MD keeps tables + headers readable, grep-able, version-controllable.
2. Which of A-G (if any) should land in a Sprint 16?

---

## Sprint 14 — Parallel polling + concurrency control — CLOSED 2026-04-24

Direct follow-up to Sprint 13. User-visible outcome: up to `max_concurrent_turns` chat conversations stream in parallel per backend (configurable from admin: 1 / 2 / 4 / 6, default 4). Architectural outcome: polling loop rewritten from serial to `asyncio.gather`-based parallelism, bounded by a global semaphore that's resized live when admin changes the setting. See ADR-008 for rationale and concurrency audit.

### Deliverables

- **D — Shared cancel watcher** (bug-fix that Sprint 14 needed before paralleling). Sprint 13's per-turn `_watch_cancel` would race under parallel turns (one watcher drains the sidecar set, siblings see empty, cancels get lost for specific sessions). Replaced with a single `cancel_watcher_loop` sibling of `polling_loop`, started from `main.py` lifespan. Populates module-level `_pending_cancellations: set[str]`; each `_process_turn` reads via `cancel_check=lambda: session_token in _pending_cancellations`. Token discarded on turn completion so stale signals can't affect future turns on the same session.
- **C — Parallelism in `polling.py`**. `_tick` now calls `asyncio.gather` across frontends. Per-frontend work (extracted into `_process_frontend`) gathers across queued messages. Each `_process_message_safe` acquires a global `_turn_semaphore` (sized from `LLMConfig.max_concurrent_turns`, resized per tick if the admin changed the value). Recovery / auth / document / upload handlers stay sequential per frontend (not LLM-bound; the parallelism win was in the stream path).
- **B — `max_concurrent_turns` admin dropdown**. New Literal[1, 2, 4, 6] field on `LLMConfig`, default 4. Admin dropdown in `LLMSection.tsx` below the disable-thinking toggle, with warning text: "Must match OLLAMA_NUM_PARALLEL and LM Studio Parallel; excess turns otherwise queue inside the runtime without visible indicator". EN + ES i18n keys; rest fall back to EN.
- **A — Ollama config on this Mac**. `OLLAMA_NUM_PARALLEL` raised from 2 to 4 in `~/Library/LaunchAgents/com.ollama.server.plist`, full `launchctl bootout` + `bootstrap` reload. `Ollama_UNI_Tools_Config.md` histórico updated with the change and its memory implication (each slot reserves its own full `num_ctx`).

### Files touched

- Backend: `services/polling.py` (parallelism + semaphore + shared cancel set + cancel_watcher_loop), `services/llm_config_store.py` (`max_concurrent_turns` field), `main.py` (start `cancel_watcher_loop` in lifespan).
- Admin: `src/api.ts` (`max_concurrent_turns` type), `src/i18n.ts` (2 new keys EN + ES), `src/sections/LLMSection.tsx` (dropdown).
- Ops: `~/Library/LaunchAgents/com.ollama.server.plist` (local Mac only), `Ollama_UNI_Tools_Config.md` (repo root).
- Docs: `docs/architecture/decisions.md` (ADR-008), `docs/STATUS.md`, `docs/CHANGELOG.md`.
- Handoff: `HRDD_Sprint14_port_prompt.md` (new, repo root) — ready-to-paste prompt for Claude-in-HRDD to replicate the same changes in HRDDHelper.

### Acceptance criteria

- [x] Python compiles clean (`py_compile`) on `polling.py`, `llm_config_store.py`, `main.py`.
- [x] `OLLAMA_NUM_PARALLEL=4` active on this Mac (verified via `ps eww`).
- [ ] **Live-test (Daniel's QA after Portainer re-pull):**
   1. Two users on same frontend send messages simultaneously → both get first tokens within ~1 s of each other (not one waiting 20+ s for the first to finish).
   2. Five users simultaneously → first four stream, fifth shows "en cola — 1 ahead".
   3. Change admin dropdown from 4 to 2 → next pair of concurrent sends shows the new cap (5th, 4th, 3rd queue; previously-running 4 complete normally).
   4. Click Stop on one of the parallel streams → only that turn cancels, the other 3 keep streaming.
   5. Session-close summariser triggered while inference is streaming → both run in parallel (different slots).

### Post-deploy follow-up fixes (same-day, 2026-04-24)

Sprint 14's initial commit (`6e175e0`) deployed via Portainer re-pull and Daniel started real QA immediately. Four problems surfaced; four commits followed that afternoon/evening. All four are in the Sprint 14 scope (parallel polling + disable-thinking interactions) and close the sprint definitively.

1. **`a09607e` — Admin UI polarity fix for the thinking toggle.** Sprint 13's `"Disable reasoning" + "Enabled"` label was a double-negative — users couldn't tell which direction the model was actually thinking. Replaced with a `<select>` OFF / ON labelled "Thinking / Reasoning". OFF (default) = no thinking. Backend field `disable_thinking` unchanged; the inversion lives only in the TSX binding. EN + ES translations wired.

2. **`5e75a78` — Diagnostic log per outgoing LLM request + `/no_think` scoped to qwen3.** Added an INFO-level one-liner in `_build_body` reporting provider, model, `num_ctx`, `disable_thinking`, `body_think_false`, `sys_hint_injected`, `n_messages` — visible in OrbStack container logs. Also scoped the `/no_think` user-message suffix to qwen3 models (it had been applied universally in Sprint 13 and was polluting prompts for non-qwen thinking models with literal user text).

3. **`f6743b7` — Fire-and-forget dispatch: fixed Sprint 14 regression where parallelism was silently serial.** Sprint 14's initial implementation did `await asyncio.gather(*msg_tasks)` inside `_process_frontend`, which blocked the polling loop for the FULL duration of the slowest in-flight stream. Users on the same (or other) frontends sending mid-stream saw "en cola" indicators for the full 20-60 s of the blocking turn, because no drain happened until gather returned. Replaced with `asyncio.create_task` + done-callback; tasks tracked in `_inflight_turns: set[Task]` for strong refs. Terminal events (`done`/`error`/`cancelled`) in `_push_chunk` now retry once with 500 ms backoff — losing a terminal event is what was leaving the UI stuck on `isStreaming=true` with a generic "algo salió mal" error while session_store had the full response. Added turn-start / first-token-latency / turn-end timing logs.

4. **`edc3a99` — Dropped the `/no_think` user-message suffix entirely; rely on Ollama `"think": false` body field for all thinking models.** The most impactful fix. Diagnosed live from OrbStack logs: re-question TTFT was 44-82 s instead of the ~10 s Daniel had pre-Sprint-13. Root cause was the suffix's placement-on-last-user-message-only mutation: turn N sent `USER1` with the suffix (it was the last user at that moment); turn N+1 sent `USER1` without the suffix (the suffix had moved to `USER2`). Ollama's prefix cache matched the system prompt only and then re-prefilled everything from USER1 onward on every re-question, costing 30-70 s per turn on qwen3.6:35b at num_ctx=256000. Removed `_is_qwen3_model` helper and the `_NO_THINK_USER_SUFFIX` constant entirely. `_apply_no_think` now only injects the system-prompt hint (idempotent → prefix-cache safe). For Ollama, `body["think"] = False` is the universal and authoritative switch (works for qwen3, deepseek-r1, gemma3-think, any future thinking model Ollama serves). For LM Studio, Daniel configures no-thinking in the LM Studio GUI directly — CBC sends nothing extra for that path.

Architectural invariants captured in ADR-008 still hold. The two user-visible promises of Sprint 14 — "up to N parallel turns" and "disable thinking actually disables thinking" — are now working correctly at the end of 2026-04-24.

### Known follow-ups (explicitly deferred)

- Per-frontend `max_concurrent_turns` override — global only for now, matches the pattern of `disable_thinking` / compression / routing. Add to `LLMOverride` if a deployment ever needs frontend-specific caps.
- Queue-inside-runtime indicator — when CBC cap > runtime cap, extras queue inside Ollama/LM Studio and CBC can't see them. Either keep aligned (admin discipline) or surface runtime queue depth via an admin proxy endpoint. Not urgent.
- HRDD port — handoff prompt written (`HRDD_Sprint14_port_prompt.md`, kept up to date with the suffix-removal fix). Daniel runs it in a Claude-in-HRDD session when ready.
- First-question TTFT optimisation — cold-load + full-prompt prefill dominates (30-60 s for a 35B MoE model at 256k ctx with a CBA in context). Pre-loading CBC's inference model in Ollama (via `~/.ollama/preload.conf`) would eliminate cold-load. Daniel's judgement call — costs ~45 GB RAM always resident.
- System-prompt stability across turns — the prompt_assembler re-runs per turn and may produce different output when the query's RAG retrieval changes. Not introduced by Sprint 13/14 but limits the prefix-cache win below what it could be. Deeper refactor, not urgent.

---

## Sprint 13 — Chat resilience & UX control — CLOSED 2026-04-24

Reactive sprint after Daniel hit a real-world LM Studio template-Jinja crash (`qwen3.6-35b-a3b`) that left the UI locked with no way to recover short of killing the chat. Three independent features that together let CBC (and HRDD when adapted) survive a wedged backend gracefully and give users / admins explicit knobs over it.

### Feature 1 — "Esperando turno" indicator
Sidecar exposes `GET /internal/queue/position/{session_token}` (cheap O(N) walk over the chat queue, nothing else). ChatShell polls it every 2 s while `isStreaming && !streamingText` (waiting for first token). Position > 0 → renders the activity bubble as `Waiting in queue — N ahead of you` instead of the generic spinner. Clears on first token or stream end. Only fires when there's actually contention on the same frontend.

### Feature 2 — Universal "disable thinking / reasoning" toggle
New `disable_thinking: bool = True` field on `LLMConfig` (sibling of `compression` / `routing`, global only — same inheritance pattern as those). Default ON because the qwen3 family's reasoning prelude was the single biggest hit on first-token latency Daniel measured. Combines four techniques in `llm_provider`:
- Top-level `"think": false` in the body (Ollama-native, ignored by other providers).
- ` /no_think` suffix on the last user message (qwen3 convention, honoured by both Ollama and LM Studio templates).
- System-prompt nudge `"Respond directly. Do not output <think>..."` injected into the existing system message (or prepended if none exists).
- Streaming-safe `_ThinkStripper` state machine that drops `<think>...</think>` blocks before the tokens reach the SSE channel — handles tags split across chunk boundaries (verified with 9-case unit test, including character-by-character splits).

For models without a thinking mode (gemma, llama, mistral) every layer is a no-op. Admin checkbox in `LLMSection` between slots and context-compression block; EN + ES translations wired (others fall back to EN per the Sprint 12 Phase B pattern).

### Feature 3 — Stop button + inactivity timeout + defensive UI reset
Three layers of defence against the wedged-backend scenario:
- **Backend inactivity timeout (60 s, `INACTIVITY_TIMEOUT`)** wraps the per-chunk `aiter_lines()` reader with `asyncio.wait_for`. The connection-level `STREAM_TIMEOUT=300s` got reset on every chunk and never fired in the qwen3.6 case; the per-chunk budget kills genuinely stalled streams in 60 s and lets the fallback chain try the next slot.
- **Cooperative cancel via per-turn watcher.** Sidecar accepts `POST /internal/chat/cancel/{session_token}` (sets a flag with TTL); `_process_turn` spawns a 1-s-tick watcher that polls `GET /internal/cancellations` (separate endpoint, deliberately NOT bundled into `/internal/queue` so it can fire mid-stream instead of waiting for the next 2-s poll cycle). Watcher flips `cancel_flag["requested"] = True`; `stream_chat_one_slot` checks it between chunks and raises `CancelledError`. Backend then emits a `cancelled` SSE event and persists the partial assistant message so the conversation log keeps what the user already saw.
- **ChatShell Stop button** (visible only during streaming) optimistically closes the EventSource, appends `(cancelled)` to the partial reply, unlocks the input, and fires the cancel POST in the background. New SSE listener for `cancelled` mirrors the cleanup so server-side cancels look the same. Defensive `setQueuePosition(null)` + `setStopRequested(false)` in every terminal-state handler (`done`, `error`, `cancelled`, `onerror` after 3 strikes) so the UI can't get stuck even if the sidecar hangs up dirty.

### Files touched
- `CBCopilot/src/backend/services/llm_config_store.py` — `disable_thinking` field on `LLMConfig`.
- `CBCopilot/src/backend/services/llm_provider.py` — `INACTIVITY_TIMEOUT`, `_apply_no_think`, `_ThinkStripper`, `cancel_check` plumbing across `stream_chat` / `stream_chat_one_slot`, `_build_body` re-shaped for the disable-thinking config.
- `CBCopilot/src/backend/services/polling.py` — per-turn `_watch_cancel` task, `cancelled` SSE emission with partial-message persistence.
- `CBCopilot/src/frontend/sidecar/main.py` — `POST /internal/chat/cancel/{token}`, `GET /internal/cancellations`, `GET /internal/queue/position/{token}`, `cancelled` added to SSE terminal-event set.
- `CBCopilot/src/admin/src/api.ts` + `CBCopilot/src/admin/src/i18n.ts` + `CBCopilot/src/admin/src/sections/LLMSection.tsx` — `disable_thinking` typed + checkbox + EN/ES translations.
- `CBCopilot/src/frontend/src/i18n.ts` — 4 new keys (`chat_stop`, `chat_cancelled_suffix`, `chat_queued`, `chat_queued_alone`) in EN + ES.
- `CBCopilot/src/frontend/src/components/ChatShell.tsx` — queue-position polling effect, `stopStream` handler + Stop button next to Send, `cancelled` SSE listener, defensive resets in every terminal handler.

### Acceptance criteria
- [x] Backend Python syntax check on all modified modules (`py_compile`).
- [x] `_ThinkStripper` 9-test suite passes (single-chunk, split tags, multiple blocks, no-close, char-by-char streaming).
- [x] Backend Docker image builds clean.
- [x] Frontend Docker image builds clean (validates ChatShell + i18n + admin SPA TypeScript).
- [ ] **Live-test (Daniel's QA)** — needs a re-pull on Portainer:
   1. Toggle `disable_thinking` OFF, send a question to a qwen3 model → see thinking prelude in tokens. Toggle ON → thinking suppressed.
   2. Open two browser tabs on the same frontend, send messages near-simultaneously → second tab shows "Waiting in queue — 1 ahead of you" until the first finishes.
   3. Send a long prompt; click Stop within a few seconds → reply collapses to `(cancelled)`, input unlocks immediately, next message goes through normally.
   4. Force a hung stream (LM Studio template error) → ChatShell unlocks itself within 60 s via inactivity timeout (no need to kill the chat).

### Known follow-ups (deferred)
- LM Studio worker-zombie recovery (admin "Eject model" button) — separate sprint, requires `lms` CLI shell-out from the backend.
- Per-frontend `disable_thinking` override — currently global only. Add to `LLMOverride` if a deployment ever wants it different per frontend.
- `num_ctx`-consistent loading per model in `llm_provider` to avoid Ollama reload thrashing — flagged during Sprint 13 discussion, not in scope.

---

## Sprint 12 Phase B — Admin i18n wiring pass 1 — **PARKED 2026-04-21**

Pass 1 landed: ~200 new keys, three translator batches, 11 files wired (Glossary / Orgs / Guardrails / LLM / SMTP sections; Company / PerFrontendLLM / PerFrontendOrgs panels; TranslationBundleControls; FrontendsTab body; SessionsTab + detail drawer). Fallback path (`AdminTranslations = Partial<…>` + `DICTIONARIES[lang]?.[key] ?? EN[key]`) means untranslated slots render in EN transparently — no UI regression while Batch-3 (SessionsTab) translations splice in.

Still-to-wire in a follow-up pass: `RAGSection`, `PromptsSection` (except prompt bodies — those stay EN by design), `RegisteredUsersTab` (XLSX import + filter + chips). Sprint 13 added 2 new admin keys (`llm_disable_thinking`, `llm_disable_thinking_description`) wired in EN + ES; the other 13 languages will be filled when Phase B's translator batches resume.

## Sprint 12 Phase A — Admin i18n + branded header — CLOSED 2026-04-21

Sprint 12 Phase A closed: admin panel shell speaks 15 languages + switches at runtime. Full translation bundle ready for the whole surface; only the frequently-touched chrome (header, tabs, login, setup, per-frontend session settings incl. the CBA citation toggles) has been wired to consume it in this phase. Remaining sections (Branding / RAG / Prompts / LLM / SMTP / Sessions detail / Users / Frontends tab body) still render English — the i18n keys exist, wiring them is mechanical.

- 15 languages: EN, ES, DE, FR, IT, PT, NL, PL, HR, SV, AR, JA, TH, ID, TR. Picked for G&P-relevant UNI affiliates (Daniel 2026-04-21); KO dropped (no G&P affiliates), ID added (Bahasa for Indonesian affiliates), TR added.
- HRDD-parity header: `bg-uni-dark` band with title + language selector + logout, tab strip on `bg-white`, clear separation before main content. Works on mobile.
- Language selector in the header, persisted in `localStorage` (`cbc_admin_lang`), fallback to `navigator.language` when unseen.
- RTL wired: `<html dir>` flips for AR on every lang change. Layout not yet audited end-to-end in RTL — follow-up for Phase B.
- Translations produced by i18n-translator subagent in three parallel batches (ES/DE/FR/IT/PT → NL/PL/HR/SV/TR → AR/JA/TH/ID). Flagged as MVP-quality pending native-speaker review before each affiliate handover.

### Sprint 12 Phase B (follow-up, separate sprint)

- Replace hardcoded English in the remaining sections with `t()` calls:
  BrandingSection, BrandingPanel, RAGSection, RAGPipelineSection, PromptsSection, LLMSection, SMTPSection, GuardrailsSection, GlossarySection, OrgsSection, FrontendsTab detail, SessionsTab detail drawer, RegisteredUsersTab.
- RTL layout audit for AR — especially flex rows with left/right assumptions (chevrons, dropdowns, action-button groups).
- Native-speaker review round for each language before first affiliate handover.

Phase A's sidepanel answers "which CBAs did the model draw on for this answer". Phase B is the complementary half: **where inside each document**. The user sees `[filename, p. 14]` or `[filename, Art. 12]` references inline with the response prose, and clicking one jumps to that document in the panel.

### Sprint 11 Phase B plan

Gated end-to-end by the `cba_citations_enabled` flag that Phase A already plumbed (off by default). When off, Phase B is a no-op.

1. **Chunk metadata pipeline** — Surface `page_label` from LlamaIndex's PDF reader through the chunk pipeline. `rag_service.Chunk` gains a `page_label: str = ""` field; `_hybrid_retrieve` populates it from node metadata. Chroma already stores arbitrary metadata so no schema migration needed.
2. **Article regex fallback** — When a chunk has no page (markdown, plain text, OCR failures), scan its body for an article reference using a multilingual regex (`Art(?:ículo|icle|igo|icolo)?\.?\s+\d+(?:[.\-]\d+)?`). Use the last hit as the best-effort citation pointer. Same helper also catches `Anexo N` / `Annex N` as a deeper fallback.
3. **Prompt update (gated)** — `prompt_assembler._render_chunks` emits each chunk heading with the citation label embedded (`### Source: amcor_lezo.md | Art. 12`) and appends a small instruction block telling the LLM to cite with `[filename, ref]` brackets inline. Only when the flag is on — otherwise the existing behaviour.
4. **Session-settings plumbing** — `polling._process_turn` reads `session_settings.cba_citations_enabled` for the frontend and threads it into `prompt_assembler.assemble(..., cite_inline=True)`.
5. **Enriched sources SSE** — each entry in the `sources` event now includes a per-chunk `citation_label` dict (`{"p. 14": 2, "Art. 12": 1}`) so the panel can show "referenced 3 times" and cross-highlight on click.
6. **React citation chips** — in `ChatShell`'s markdown renderer, intercept anchor tags with `href` starting with `#cite:` and render them as clickable pills. The backend doesn't emit link syntax; instead we regex-post-process the streamed text to turn `[filename, p. N]` occurrences into `[filename, p. N](#cite:filename)` before it hits ReactMarkdown.
7. **Panel cross-highlight** — `CitationsPanel` accepts `highlightedFilename` + briefly pulses + scrolls that entry into view. `ChatShell` orchestrates: citation click → `setHighlighted(filename)` → `setPanelOpen(true)` → effect in the panel handles the visual.

### Risks / known limits
- LLMs will sometimes forget the citation format or hallucinate numbers. Accept — the user still has the panel + download as ground truth. Monitor in real use; if it's bad, tighten prompt.
- Article regex is best-effort for ES/EN/PT/FR/IT. Other languages fall back to no inline citation but still show the doc in the panel.
- PDF page labels depend on the reader. If PyMuPDFReader isn't the default resolved reader for a given PDF, the system silently falls back to article regex.

### Deferred (not in this sprint)
- Per-page jump links that open the PDF at the cited page (needs a PDF viewer component — separate piece of work).
- Composite citations ("see Arts. 12 and 14 of ...").
- Native-language article patterns beyond ES/EN/PT/FR/IT.

---

## Sprint 11 Phase A — CLOSED 2026-04-21

Sprint 11 Phase A closed. Delivers the CBA sidepanel with per-session accumulating document citations and pull-inverse downloads, plus two fixes that showed up during real-use testing (mobile table overflow, cascade reindex buttons).

Phase B (inline page / article citations in response text) is scaffolded end-to-end via a new per-frontend flag `cba_citations_enabled` but the feature itself is deferred to the next sprint — required changes: PDFReader metadata preservation, prompt_assembler update to instruct the LLM on citation format, panel cross-links between inline citations and the source list.

### Prior sprints
- Sprint 10 (2026-04-21) — Chat UX + pure pull-inverse + ChromaDB.
- Sprint 9 (2026-04-21) — RAG overhaul + HRDD-parity architecture hardening.
- Sprint 8 (2026-04-20) — Polish, testing, deployment + full i18n.

---

## Sprint 9 (previous) — RAG Overhaul + HRDD-parity Architecture Hardening — CLOSED 2026-04-21

Sprint 9 closed. Two workstreams landed together while Daniel was standing up the first real deployment in Portainer across two hosts (backend on Mac Studio, frontends on M4s over Tailscale):

1. **HRDD-parity architecture hardening.** CBC had silently accreted coupling to a shared Docker network (`cbc-net`) and three direct sidecar→backend HTTP calls over Sprints 7/7.5. That broke the cross-host deployment model (frontend and backend on different Docker hosts by design). Reverted to pure pull-inverse.
2. **RAG overhaul.** The Amcor-Lezo CBA exposed retrieval failing on its own content — the system couldn't surface the Annex I salary tables even when asked literally. Swapped the embedder (MiniLM → BGE-M3), added a cross-encoder reranker, and wired an optional Contextual Retrieval toggle. Verified on Daniel's corpus: "works much better".

Next decision gates (after real-use measurement):
- Activate Contextual Retrieval if recall still lags on table-heavy documents.
- Migrate vector store to ChromaDB when corpus crosses ~100+ companies (captured in `docs/IDEAS.md`).

---

## Sprint 9 — CLOSED

### Part 1 — Architecture hardening (HRDD parity)

- **Compose files stripped of `cbc-net`.** Both stacks now run on Docker's default bridge; each one is self-contained on its Docker host. The backend polls registered frontend URLs over LAN / Tailscale / Bonjour, same as HRDD Helper. Removed `container_name:` declarations so Portainer stack-name prefixing works for multi-frontend on one host.
- **`CBC_BACKEND_URL`** exposed on the frontend compose as an optional env var for the one remaining (auth) sidecar→backend relay. Empty default means same-host deployments keep working with service-name DNS; cross-host points it at the Tailscale / hostname of the backend.
- **Three pull-inverse refactors** to match HRDD's architecture:
  - **Guardrails thresholds**: backend pushes on each poll cycle (HRDD branding-push pattern). Sidecar caches to disk; ChatShell reads via `/internal/guardrails/thresholds` with 2/5 fallback.
  - **Session recovery**: React `POST /internal/session/recover` queues a `recovery_request`. Backend drains on its next poll, resolves, `POST`s back to `/internal/session/{token}/recovery-data`. SessionPage now polls every 400 ms with a 15 s deadline.
  - **Uploads**: React `POST /internal/upload/{token}` stores file locally + queues notification. Backend polls `/internal/uploads`, GETs each file, ingests into session RAG, DELETEs the sidecar copy. SMTP admin alert moved into the ingest path.
- **Company list pull-inverse.** Backend polling pushes admin-registered companies to the sidecar; sidecar caches them and serves `/internal/companies` (admin CRUD invalidates via `polling.invalidate_companies_pushed(fid)`). Compare All is now synthesised at read-time as a frontend-level concept (it's NOT a registered company — it has its own `compare_all.md` prompt and combined-RAG routing in `resolvers.py`, which was already correct).
- **CompanySelectPage branded buttons.** All buttons use the primary colour; Compare All gets a subtle ring + subtitle to stand out while the rest of the list stays visually consistent.
- **`docs/INSTALL.md`** rewritten: pull-inverse architecture explained up front; Portainer Repository + Web-editor modes; cross-host deployment with `CBC_BACKEND_URL`; no pre-existing Docker network required.

### Part 2 — RAG overhaul

The Amcor-Lezo stress test: the CBA Markdown file had complete salary tables in Annex I (lines 1296-1335), yet the LLM reported "no dispongo de información sobre tablas salariales" and, when asked to cite Annex I literally, "no está presente en los documentos". Two stacked causes: the old `SentenceSplitter` at 512/50 tokens was orphaning the `ANEXO I` heading from its numeric content, and `all-MiniLM-L6-v2` (English-primary, 384-dim) can't match Spanish/Basque abstract queries against numeric table bodies.

Three sequential changes landed to `src/backend/services/rag_service.py`:

- **Markdown-aware chunker + bigger chunks** (commit `5f55e8a`): route `.md` through `MarkdownNodeParser` (splits by header boundaries, keeps each section contiguous); keep `SentenceSplitter` for PDFs/TXT but bump `CHUNK_SIZE` 512→1024 and `CHUNK_OVERLAP` 50→100. Hybrid BM25 + dense via `QueryFusionRetriever` (reciprocal rerank). `DEFAULT_TOP_K` 5→8. First fix — made a dent but still missed Annex I under literal query.
- **BGE-M3 + cross-encoder reranker** (commit `f488ec1`): swap embedder to `BAAI/bge-m3` (1024-dim, 100+ languages, 568M params) — single biggest quality lever for a multilingual corpus. New post-processor stage: fetch `rag_reranker_fetch_k=30` candidates from hybrid retrieval, rerank with `BAAI/bge-reranker-v2-m3` down to `rag_reranker_top_n=8`. Model names admin-configurable via `deployment_backend.json`. Dockerfile pre-downloads both models (+ MiniLM fallback) so cold starts stay instant; image grows ~3 GB.
- **Contextual Retrieval toggle** (commit `f488ec1`): Anthropic's Sept-2024 recipe. When enabled, `_contextualise_nodes` synchronously calls the summariser LLM for each chunk to generate a 1–2 sentence context line, prepended at index time so embeddings carry document-level grounding. Off by default — adds one LLM call per chunk, which means minutes-to-hours for a big corpus. Runtime toggle via new `POST /admin/api/v1/rag/settings/contextual`; endpoint reindexes every scope and rolls the toggle back on failure. Admin UI: new `RAGPipelineSection` on General tab shows the embedder/reranker read-only + exposes the CR switch with a clear warning.

### Build fixes (Portainer)

Portainer on Daniel's Mac Studio hid build logs behind a paywall. Reproduced the build locally to see the actual pip error:

- First error: dependency resolver deadlock from `llama-index-core>=0.12,<0.15` colliding with newer `llama-index-embeddings-huggingface` needing core `>=0.13`. Fix: bump core / readers-file / embeddings-huggingface / retrievers-bm25 pins to the 0.13/0.14 line.
- Second error: new core line pulled in `llama-index-workflows` which requires `pydantic>=2.11.5`; our pin was `pydantic==2.10.4`. Loosen to `>=2.11.5`.
- Added `build-essential` to `Dockerfile.backend` defensively so any C-extension dep (PyStemmer via bm25 is one) can compile wheels on `python:3.11-slim`.

Final working versions: `llama-index-core 0.14.20`, `readers-file 0.6.0`, `embeddings-huggingface 0.7.0`, `retrievers-bm25 0.7.1`, `pydantic 2.13.3`.

### Delivered commits

```
7adcca0  Allow CBC_BACKEND_URL override on frontend stack for cross-host deploy
6e4aea1  Restore pull-inverse (HRDD parity): drop cbc-net + refactor 3 sidecar→backend calls
40c8b01  Push per-frontend companies to sidecar so admin list beats the hardcoded stub
310eaad  CompanySelectPage: auto-inject Compare All + branded blue buttons
9394aa6  Compare All is a frontend concept, not a registered company
5f55e8a  RAG: markdown-aware chunker + hybrid BM25/semantic retrieval
f488ec1  RAG overhaul: BGE-M3 + bge-reranker-v2-m3 + Contextual Retrieval toggle
8fff682  Fix backend build: loosen bm25 pin + install build-essential
ff9afc6  Fix backend build: bump llama-index + pydantic to compatible versions
```

### Validated on Daniel's corpus

- Indexing works with the new chunker + BGE-M3 on `CBA—Amcor_Flexibles—Lezo—Spain.md`.
- Retrieval for salary questions is "much better" (Daniel, 2026-04-21) — the Anexo I tables surface on relevant queries.
- Cross-host deployment functional: Mac Studio backend + M4 frontend over Tailscale, no shared Docker network.

### Open items (future sprints)

- **Measure recall properly**. We upgraded three things in sequence. If residual gaps show up as the corpus grows, activate Contextual Retrieval with one click from the admin.
- **ChromaDB migration** (captured in `docs/IDEAS.md`). Trigger at ~100+ companies with active docs or when query latency crosses ~50 ms. Drop-in via `llama-index-vector-stores-chroma`; enables collapsing multi-scope into a single collection with metadata filters.
- **Auth relay still not pull-inverse**. The one remaining sidecar→backend call (`/api/v1/auth/request-code`, `/verify-code`) uses `CBC_BACKEND_URL`. HRDD does this pull-inverse too; easy follow-up when we next touch auth.
- **PDF ingestion quality**. The markdown-aware path helps `.md` docs. Most real CBAs will arrive as PDFs; the default `PyMuPDFReader` / `PDFReader` handles text well but mangles complex tables. Worth revisiting with Docling or Unstructured.io if table recall in PDFs lags.

---

## Sprint 8 — CLOSED

### Decisions locked (2026-04-20)

- **D1 = A** — single sprint, both halves (i18n + polish) shipped together.
- **D2 = C** — Both workflows for editable-text translations, admin-triggered: save does NOT auto-translate. Three buttons per textarea: `Download JSON`, `Upload JSON`, `Auto-translate missing (LLM)`. Upload merges onto existing record (preserves non-text fields); Auto-translate preserves existing non-empty translations (overwrite=False in v1).
- **D3 = A** — Full 31 languages baked in. Matches HRDD parity.
- **D4 = A** — Claude generates translations now; native-speaker QA flagged as later polish in CHANGELOG + SPEC.
- **D5 = B** — Per-tier source-language selector. One dropdown per branding editor, applies to both `disclaimer_text` and `instructions_text` textareas in that tier.

### Delivered (7 phases)

- **Phase A** — `LangCode` union expanded to 31 codes (`types.ts`). `LANGUAGES` + `RTL_LANGS` exports in `i18n.ts`. `LanguageSelector` already iterates the list, no changes needed.
- **Phase B** — `i18n.ts` rewritten to ~3000 lines: 31 dictionaries × 82 keys each. `t(key, lang)` falls back `lang → EN → key-name`. MVP-quality translations generated by Claude; native-speaker QA deferred.
- **Phase C** — Backend `Branding` model + `source_language`, `disclaimer_text_translations`, `instructions_text_translations`. Resolver tier-ownership rule (translations travel with source text). New `TranslationBundle` Pydantic model + `GET/PUT /admin/api/v1/branding/defaults/translations` and `/frontends/{fid}/branding/translations`. Sidecar baseline extended. Admin `api.ts` types + `components/TranslationBundleControls.tsx` reusable card (source-lang picker, Download, Upload, coverage counters). BrandingSection + BrandingPanel mount it.
- **Phase D** — `prompts/translate.md` system prompt + `services/branding_translator.py` (walks all 30 target langs × 2 text blocks, calls `llm_provider.chat(slot="summariser")` through the normal fallback chain, preserves non-empty slots). Endpoints `POST /admin/api/v1/branding/defaults/auto-translate` + per-frontend equivalent. Auto-translate button wired in BrandingSection + BrandingPanel with stats toast.
- **Phase E** — `pickBrandingText(source, sourceLang, translations, lang)` helper in `i18n.ts`. DisclaimerPage + InstructionsPage call it; cascade is `translations[lang] → source → i18n default`. `App.tsx` flips `document.documentElement.lang` + `dir` on every lang change using `RTL_LANGS`.
- **Phase F** — `docs/INSTALL.md` written (one-time host setup, backend + frontend stacks, LLM provider choice with env-var key handling, SMTP, admin bootstrap, per-frontend config, content drop-in, smoke test, upgrade, troubleshooting). Error-handling scan clean (upload JSON parsing, auto-translate per-lang failure swallow, missing-source guard). Browser/Docker E2E + Compare-All perf left for Daniel's env.
- **Phase G** — SPEC §7 rewritten (§7.1 languages, §7.2 tier-owned translations, §7.3 workflow). CHANGELOG entry for Sprint 8. STATUS closed (this section).

### QA left for Daniel's env

- `docker compose -f CBCopilot/docker-compose.backend.yml build && up -d` → admin loads, LLM tab reachable.
- Translate-text flow end-to-end: admin sets a disclaimer → clicks Auto-translate → user in a non-source language sees the translation.
- Upload JSON round-trip: Download → edit one field → Upload → admin reload shows the change.
- RTL QA: switch user to `ar` / `ur`, confirm layout mirrors on DisclaimerPage + InstructionsPage + ChatShell.
- Compare-All with ≥10 companies loaded: verify RAG merge stays under a sane latency budget (target P95 < 4 s for the first token).

### Risks / open items

- Translation quality: MVP-level. Native-speaker review is a later polish step for any language CBC ships in production.
- Auto-translate on a very small summariser can be slow (~60 s) or fail mid-way; stats tell the admin how many keys landed, and the operation is idempotent (re-run fills only remaining gaps).

## Sprint 8 — PLANNING (archived)

**Goal:** CBC production-ready. Full 31-language UI matching HRDD (Croatian already present as `hr`); admin-editable `disclaimer_text` + `instructions_text` gain a translation workflow; end-to-end Docker flow documented; error handling + responsive polish.

### Languages (31, identical to HRDD)

en · zh · hi · es · ar · fr · bn · pt · ru · id · de · mr · ja · te · tr · ta · vi · ko · ur · th · it · pl · nl · el · uk · ro · **hr** · xh · sw · hu · sv

Croatian is already in HRDD's list — no new language to add versus HRDD.

### Deliverables

**i18n — static UI** (menus / buttons / labels / instructions / disclaimer / survey / auth / chat / guardrails UI strings)
- `types.ts` — expand `LangCode` union to 31 codes.
- `i18n.ts` — full `LANGUAGES` list + complete translation table for every existing key.
- `LanguageSelector.tsx` — grid already iterates `LANGUAGES`, just shows more options.
- Where HRDD has existing translations for overlapping keys (session, auth, nav, chat, guardrails), reuse verbatim to save quality + time.

**i18n — editable branding text** (`disclaimer_text`, `instructions_text`)
The puzzle Daniel flagged: admin writes text once in a source language; users of any of 31 languages should see it in theirs. Proposed model (D2 below):
- Branding gains `disclaimer_text_translations: dict[str, str]` and `instructions_text_translations: dict[str, str]`.
- Legacy single-string fields `disclaimer_text` / `instructions_text` stay as the source value + ultimate fallback.
- Admin editor gets:
  - Source-language selector per tier (D5).
  - `Download JSON template` button → emits `{<lang>: ""}` for every lang, source pre-filled.
  - `Upload JSON translations` → merges into `*_translations`.
  - `Auto-translate (LLM)` button → background job calls summariser slot (fallback: inference) with a translate-to-N-languages prompt, populates missing slots. Admin can re-run to overwrite.
- DisclaimerPage / InstructionsPage read `branding.<key>_translations[lang]` → fall back to the source string → fall back to the built-in i18n default.

**MILESTONES §Sprint 8 polish** (kept)
- End-to-end Docker flow test (clean state → both frontends + admin → full chat).
- Responsive design pass (phone + tablet).
- Error handling: LLM timeout, SMTP offline, RAG empty, sidecar disconnect.
- `docs/INSTALL.md` (OrbStack + Portainer flows, env vars, first-time setup, SMTP config).
- Compare All 10+ companies perf check.

### Decisions to lock

- **D1 — Split 8A / 8B?**
  - A. One sprint. i18n work is mostly Claude-driven translation + mechanical wiring; polish tasks are small. *(recommended for momentum)*
  - B. Split: 8A polish/deploy/perf/responsive (user-shippable immediately); 8B full i18n + editable-text workflow.

- **D2 — Translation workflow for editable text** (Daniel's core question).
  - A. **JSON template only** (his Option 1). Download → edit externally (e.g. via Claude Code) → upload.
  - B. **LLM auto on every save** (his Option 2). Background task on each save, fires 30 LLM calls.
  - C. **Both, admin-triggered** (his "both for control", my recommendation). Buttons next to each textarea: `Download JSON`, `Upload JSON`, `Auto-translate now (LLM)`. Save alone does NOT auto-translate — explicit button does. Merge vs. overwrite semantics defined.

- **D3 — Full 31 languages or priority subset?**
  - A. **Full 31** baked in. ~20 KB gzipped. Users never see fallback-EN for static UI. *(recommended — matches HRDD parity)*
  - B. Priority subset (EN/ES/FR/DE/PT/HR), rest fall back to EN at runtime.

- **D4 — Who writes the translations.**
  - A. **Claude generates now** using its multilingual capabilities; flag for later native-speaker QA. *(recommended — realistic path to ship; native refinement can follow)*
  - B. Placeholder-only; ship blocked on external translation work.

- **D5 — Source-language granularity for editable text.**
  - A. Per-field (admin picks source lang for disclaimer separately from instructions).
  - B. **Per-branding-tier** (one source lang for all editable text in that tier). *(recommended — simpler UX; same admin writes both fields typically)*

### Implementation order (assumes all-A / C-on-D2)

1. **Phase A** — `LangCode` + `LANGUAGES` expansion; LanguageSelector responsive pass.
2. **Phase B** — full EN→30 translation of every i18n key (disclaimer → instructions → survey → chat → auth → nav). Reuse HRDD overlap where applicable.
3. **Phase C** — Branding model: `*_translations` fields + source-lang selector + download/upload JSON endpoints + admin UI wiring.
4. **Phase D** — `translate.md` prompt + background LLM auto-translate job (summariser slot cascade). Admin button triggers; progress visible.
5. **Phase E** — DisclaimerPage / InstructionsPage pick user's lang from translations with cascade fallback.
6. **Phase F** — Error polish + responsive + INSTALL.md + Compare All perf check.
7. **Phase G** — SPEC §7 update; CHANGELOG; STATUS close.

### Risks
- Translation quality: MVP-level, needs native review for formal releases. Flag in CHANGELOG + SPEC.
- Bundle size: ~20 KB gzipped extra — fine.
- Auto-translate: 30 LLM calls × a couple seconds each = 60-90 s background job. Admin UI should show progress + let the admin keep editing.
- RTL languages (ar, ur, he-not-in-list): Tailwind + `dir="rtl"` on `<html>` when `lang in rtlSet`. Verify during responsive QA.
- HRDD's in-bundle translations don't cover every CBC key (we have CBC-specific ones like `chat_guardrail_warning`, `chat_summary_heading`, etc). Net new strings go through Claude.

---

## Sprint 7.5 — COMPLETE

### Decisions locked (2026-04-20)

- **D1 = B** — No new `fabrication` category. Runtime patterns stay as they are. Rationale (Daniel): the tool is used by registered union delegates only; if someone tries to jailbreak the LLM, that's on them. The `guardrails.md` prompt layer already instructs the LLM to refuse fabrication.
- **D2 = Global only** — `guardrail_warn_at` + `guardrail_max_triggers` live in `deployment_backend.json` / `core/config.py`. Per-frontend overrides can land later if needed.
- **D3 = A (HRDD pattern)** — Enforce guardrails backend-side. On any triggered turn, **skip the LLM**, push the category-specific fixed response as the assistant turn, increment counter. When `violations >= guardrail_max_triggers`, push the session-ended message, stamp `status='completed'`, flag the session.
- **D4 = A** — New `GuardrailsSection` mounted at the bottom of `GeneralTab`.
- **D5 = A** — Markdown test corpus under `docs/knowledge/`.

Pattern review: narrow the brittle `workers? from \w+ (?:are|should be) (?:fired|…)` — "fired" is common in legitimate CBA text ("workers from contract X are fired if…"); drop `fired` from that pattern's verb list, keep `deported|removed|eliminated` where the intent signal is clearer.

## Sprint 7.5 — PLANNING (archived plan)

**Goal (MILESTONES §Sprint 7.5):** reviewed runtime guardrails that actually fit CBC's domain (CBA research, not HRDD's labour-violation docs). Thresholds admin-configurable; session-end at threshold enforced backend-side; admin can see what's active.

### What exists today (Sprint 6A shipped as-is)

- `services/guardrails.py` — HRDD's hate-speech + prompt-injection regex tables, CBC-themed localised responses. Two categories.
- `polling._process_turn` calls `guardrails.check()`, increments the session's counter, **logs only** — the LLM still runs on the turn.
- `ChatShell.tsx` hardcoded `VIOLATION_WARN_AT = 2` / `VIOLATION_END_AT = 5`. Shows amber banner at 2, red "session ended" at 5. Backend never enforces the end.
- No admin UI for inspecting active rules.

### Deliverables

**Backend**
- `services/guardrails.py` — add `fabrication` category (CBA-specific jailbreak attempts). Review + slightly broaden injection list. Keep hate patterns (safety baseline). Expose `get_patterns()` + `get_thresholds()` for the admin viewer.
- `core/config.py` — `guardrail_warn_at: int = 2` (exists: `guardrail_max_triggers` which we'll rename conceptually to end-threshold).
- `polling._process_turn` — when `violations >= guardrail_max_triggers`, **skip the LLM call**: push the localised `session_ended` message as token + `done`, stamp `status='completed'`. Matches HRDD's Sprint 16 pattern.
- `api/v1/admin/guardrails.py` (new) — `GET /admin/api/v1/guardrails` returns `{categories, thresholds, responses}` for the admin viewer.
- Sidecar `/internal/config` — include `guardrail_warn_at` + `guardrail_end_at` in the response so ChatShell uses live values instead of hardcoded constants.

**Frontend**
- `types.ts` — `DeploymentConfig.guardrail_warn_at?` + `guardrail_end_at?`.
- `ChatShell.tsx` — read thresholds from `config` prop; drop the hardcoded constants.

**Admin**
- `api.ts` — `getGuardrailsInfo()`.
- `sections/GuardrailsSection.tsx` (new, read-only) — lists categories with their human-readable pattern strings, shows current thresholds, shows the localised response text.
- `GeneralTab.tsx` — mounts the section near the LLM block.

**Docs**
- `docs/knowledge/guardrails-test-corpus.md` — small file with sample messages (triggering + non-triggering) that Daniel can paste into the chat to verify behaviour.
- SPEC §4.10 — updated rule set.
- CHANGELOG + STATUS close.

### Decisions to lock

- **D1 — New category for fabrication attempts.**
  - A. Add `fabrication` category with regex like `pretend\s+the\s+(?:cba|agreement)\s+says`, `make\s+up\s+(?:a\s+)?clause`, `invent\s+(?:a\s+)?(?:wage|clause|figure)`. Same treatment as hate/injection (counts as violation, ended-session response). *(recommended — these are the CBC-specific traps the SPEC mentions)*
  - B. Leave pattern tables as-is; rely on the `guardrails.md` prompt to reject fabrication requests.

- **D2 — Per-frontend thresholds.**
  - A. Global only in 7.5 (`guardrail_warn_at`, `guardrail_max_triggers` in `deployment_backend.json`). *(recommended — scope discipline. Per-frontend can land later if needed.)*
  - B. Add both to `session_settings_store` with per-frontend override. More plumbing.

- **D3 — Enforce session-end backend-side.**
  - A. When `violations >= end_at`, skip the LLM entirely. Push a `token` event with the localised session-ended message, push `done`, stamp `status='completed'`. Matches HRDD's Sprint 16. *(recommended — closing the loop Daniel flagged; current state is UI-only)*
  - B. Keep Sprint 6A behaviour (log-only + UI banner). Do not block the turn server-side.

- **D4 — Admin viewer placement.**
  - A. New `GuardrailsSection` mounted in `GeneralTab` near the LLM section. Single scroll. *(recommended — no new tab needed for a read-only block)*
  - B. New top-level "Guardrails" tab. Feels heavy for a read-only viewer.

- **D5 — Test corpus format.**
  - A. Markdown file under `docs/knowledge/` with paste-ready examples. Daniel runs them manually through the chat. *(recommended — matches existing `lessons-learned.md` / `hrdd-helper-patterns.md` style)*
  - B. Python test script that programmatically asserts each category fires on each sample. Proper unit testing. More work.

### Implementation order

1. Backend pattern review + `fabrication` category + `get_patterns()` helper.
2. `guardrail_warn_at` + `guardrail_end_at` wiring (config → sidecar → frontend).
3. Polling enforcement of session-end at threshold.
4. Admin `GET /admin/api/v1/guardrails` + `GuardrailsSection` viewer.
5. Test corpus doc + SPEC §4.10 update.
6. Smoke: live chat → trigger injection pattern → see banner at 2 → at 5, chat locks with the localised message.

### Risks
- Pattern false-positives in legitimate CBA questions (e.g. user writes "workers from Spain are fired under the new agreement" — current pattern would catch that because "workers from \w+ (?:are|should be) fired"). Review-and-tune step is non-trivial — I'll narrow that one.
- Thresholds too low for real use (2/5 might be too aggressive for real union delegates who don't know they're typing adjacent to a trigger). Default stays 2/5 but note the knob exists.

---

## Sprint 7 — COMPLETE

### Deliverables (all ✓)
- `services/session_lifecycle.py` — background scanner (5 min interval): auto-close idle sessions after `auto_close_hours`, rm -rf session trees after `auto_destroy_hours` post-close. `auto_destroy_hours=0` means never. Wired into `main.py` lifespan.
- `services/session_store.py` — new `completed_at` field persisted on status flip. `set_status("completed")` stamps it automatically; drives the auto-destroy timer.
- `api/v1/auth.py` — real `POST /api/v1/auth/request-code` + `verify-code`. Contacts allowlist check when `auth_allowlist_enabled` (default True). SMTP send when configured; `dev_code` returned inline when offline (D7=A). 15-minute TTL, one-shot codes.
- Sidecar `/internal/auth/*` rewritten as thin relays to the backend (dev-stub gone).
- `api/v1/sessions/uploads.py` — new `GET /{token}/recover` (honours `session_resume_hours`, HTTP 410 past window). Upload handler now fires `_maybe_alert_admins` (non-blocking SMTP to `resolve_admin_emails(frontend_id)`).
- `polling._process_close` — after inline summary delivery, schedules `_email_summary` when `survey.email` is set AND SMTP configured. Non-blocking; UI close flow untouched.
- `api/v1/admin/sessions.py` — list (sorted by last_activity desc) + detail (survey + messages + uploads) + flag toggle + destroy.
- `admin/src/SessionsTab.tsx` — list + detail drawer. Columns: Token, Frontend, Company, Country, Status, Msgs, Violations, Last activity, Flag, Destroy. Filter tabs (all/active/completed/flagged). 10-s auto-refresh. HRDD role/mode/report columns dropped (ADR-004/006).
- `admin/src/Dashboard.tsx` — Sessions tab added between Frontends and Registered Users.
- `frontend/src/components/SessionPage.tsx` — "Resume existing session" flow with token input, error handling (404 / 410 / network).
- `frontend/src/components/ChatShell.tsx` — accepts `recoveryData`; on mount, replays persisted messages instead of seeding the initial-query bubble; seeds `violations` + `sessionEnded` from recovery metadata.
- `frontend/src/App.tsx` — `handleResumeSession` bypasses survey and lands directly in chat with language + frontend_id + survey populated from the recovery payload.
- `frontend/src/types.ts` — `RecoveryData`/`RecoveryMessage` types.
- `backend/requirements.txt` — added `email-validator>=2.0` (pydantic `EmailStr`).
- `admin/package.json` — added `react-markdown` + `remark-gfm` for the detail-drawer conversation viewer.

### Acceptance tested end-to-end
- **D1 (recovery)**: curl survey → 12 s wait → `GET /internal/session/{token}/recover` returns `status=active, messages=[user/hi], session_resume_hours=48`.
- **D2 (allowlist)**: `POST /internal/auth/request-code` with `nobody@test.com` (not in Contacts) → HTTP 403 `"This email is not authorized for this deployment."`. Turning `auth_allowlist_enabled: false` in `deployment_backend.json` bypasses the check for bootstrap.
- **D3 (auto-destroy)**: `set_status("completed")` stamps `completed_at`; scanner reads it on next tick. Verified via Python REPL — `auto_destroy_hours=0` skips the destroy path.
- **D7 (SMTP fallback)**: with no SMTP configured, backend returns `dev_code` in the response body; AuthPage shows the amber banner as before.
- **Lifespan**: `Session lifecycle scanner started (interval 300s)` logged on boot; `rag_watcher` + `polling` + `lifecycle` run concurrently.

### Known caveats
- Out-of-the-box: `auth_allowlist_enabled=true` + empty Contacts → *no one* can auth. For bootstrap, either add contacts in Registered Users or flip `auth_allowlist_enabled=false` in `deployment_backend.json`. A "SMTP / Contacts bootstrap" banner on the admin dashboard is a nice-to-have for Sprint 8.
- Admin SMTP-offline alert: nothing surfaces the fact that upload alerts are silently skipped. Log line is there; no UI. Sprint 8 polish.
- ChatShell recovery reopens the SSE unconditionally. If the session is `completed`, no tokens will ever arrive — harmless but keeps a connection warm. Could skip the `openStream` call when `recoveryData.status === 'completed'`; small polish.

### Decisions locked (2026-04-20)

- **D1 = B** — Session recovery replays the persisted conversation and opens a fresh SSE. No re-attachment to in-flight streams. Covers "closed tab, coming back" — the real use case.
- **D2 = A** — Contacts is the authoritative allowlist. `auth_allowlist_enabled=true` by default, togglable in `deployment_backend.json` for bootstrap. Per-frontend auth-on/off toggle (from Sprint 4A `session_settings`) already exists — that disables auth entirely for a frontend; D2 is about which emails pass *when* auth is on.
- **D3 = A** — Auto-destroy fires N hours after the session reaches `completed`. Active sessions never self-destruct.
- **D4 = A** — All three SMTP send paths: auth code, user summary at close, admin alert on chat upload.
- **D5 = A** — SessionPage gains a "Resume existing session" textbox-and-button path next to the existing "Start new session" button (HRDD pattern).
- **D6 = A (reuse HRDD fields where they fit)** — Admin SessionsTab: list + detail drawer. Column set to be derived from HRDD's SessionsTab, filtered to what applies to CBC's domain (drop HRDD-specific roles/modes; keep token, company, country, messages, status, last_activity, violations, flagged, actions).
- **D7 = A** — Graceful SMTP-offline fallback. When `smtp_service.is_configured()` is False, the backend still returns `dev_code` in the auth response so bootstrap demos keep working. Once SMTP is configured, the field is omitted and email is sent.

## Sprint 7 — PLANNING

**Goal (MILESTONES §Sprint 7):** Session management works end-to-end. Real SMTP replaces the dev-banner stubs for auth and summary delivery. Background scanners auto-close and auto-destroy per the per-frontend session settings. Admins have a sessions tab to inspect what's running.

### Already-present pieces (trust inventory)
- `services/session_store.py` (Sprint 6A — disk-backed + cache + destroy rmtree)
- `services/smtp_service.py` (Sprint 3 — config + send_email + frontend override)
- `services/contacts_store.py` (SPEC §4.11 follow-up — authorized users directory)
- Admin `RegisteredUsersTab.tsx` (Contacts UI)
- Session RAG (Sprint 5) + session_rag.destroy_session hook already used by `session_store.destroy_session`

### Deliverables

**Backend new**
- `services/session_lifecycle.py` — background task loop (every 5 min): mark idle sessions `completed` after `auto_close_hours`; rm -rf sessions past `auto_destroy_hours` after close.
- `api/v1/sessions/recovery.py` — `GET /api/v1/sessions/{token}` (conversation + survey + status) used by the frontend on token reconnect. Honours `session_resume_hours`.
- `api/v1/admin/sessions.py` — list + detail + flag + destroy, admin-auth-gated.

**Backend changes**
- `polling.py _process_close`: after generating the inline summary, if `survey.email` is set AND SMTP configured, send the summary via `smtp_service.send_email` (non-blocking; failures logged, don't break the flow).
- `api/v1/sessions/uploads.py upload_to_session`: fire-and-forget admin alert via SMTP when a user uploads during chat (if `send_new_document_to_admin` toggle is on).
- Sidecar `/internal/auth/request-code` + `/internal/auth/verify-code`: swap the dev-stub generator for a backend-mediated path. The sidecar relays the email to a new `POST /api/v1/auth/request-code` on the backend which (a) checks Contacts allowlist, (b) generates a 6-digit code, (c) sends via SMTP. Verify is unchanged in pattern, just moves to the backend.
- Add `auth_allowlist_enabled: bool = true` to `deployment_backend.json` so the admin can turn off Contacts enforcement during bootstrap.

**Admin UI**
- `admin/src/SessionsTab.tsx` — list (token / company / status / message count / last activity / violations / flagged) with a detail drawer showing the full conversation.jsonl + survey + RAG paths. Destroy + flag buttons.
- `Dashboard.tsx` — add the Sessions tab (4 tabs total: General / Frontends / Sessions / Registered Users).

**Frontend**
- `SessionPage.tsx` — add a "Resume existing session" path: textbox for token + button. On submit, `GET /api/v1/sessions/{token}` via the sidecar. If within resume window, skip ahead directly to chat; if not, show an error.
- `ChatShell.tsx` — accept optional `recoveryData` prop so an existing conversation can be replayed into the bubble list on mount.
- `AuthPage.tsx` — keep the dev banner visible only when SMTP is not configured (the backend-mediated path returns `dev_code` in that case so the UX doesn't break during setup).

### Decisions to lock

- **D1 — Session recovery scope.**
  - A. Full: token → replay conversation + reopen SSE; resume in-flight streams if backend is still generating.
  - B. **Partial** (recommended): replay the persisted conversation, reopen SSE for future turns; don't try to re-attach to a live stream. Simple + covers the real use case ("closed the tab, coming back").

- **D2 — Auth allowlist enforcement.**
  - A. Contacts is authoritative. Emails not in Contacts fail auth with a "contact your admin" message. `auth_allowlist_enabled=true` by default, togglable in `deployment_backend.json`. *(recommended — matches SPEC §4.11)*
  - B. Allow any email — Contacts is informational only.

- **D3 — Auto-destroy trigger.**
  - A. **N hours after session close** (recommended). Safer: never destroys an active session. `auto_destroy_hours=0` = disabled.
  - B. N hours after session creation regardless of state (useful if you need a hard "burn after X hours" guarantee even for sessions still open).

- **D4 — SMTP sending scope this sprint.**
  - A. All three: auth codes + user summary on close + admin alert on chat upload *(recommended — smtp_service already supports it; just wire three call sites)*.
  - B. Only auth codes + summary; defer admin alert to Sprint 8.

- **D5 — Recovery UX on SessionPage.**
  - A. **"Resume existing session" textbox + button** (recommended — matches HRDD). Session token pasted → validated → jump to chat.
  - B. Recovery by URL only (`/?recover=TOKEN`). No UI affordance.

- **D6 — Admin SessionsTab depth.**
  - A. **List + detail drawer** (recommended): click a row → see conversation.jsonl + survey + RAG paths + flagged toggle + destroy button.
  - B. List-only: destroy button inline per row, no detail drawer (lands Sprint 8).

- **D7 — SMTP-not-configured fallback for auth.**
  - A. **Graceful degrade** (recommended): backend detects `smtp_service.is_configured()==False` and still returns the 6-digit code in `dev_code` (as today). Admin bootstrap stays smooth.
  - B. Fail hard — no SMTP = no auth. Admin must configure SMTP first. Safer security posture but painful bootstrap.

### Implementation order

1. **Phase A — Session lifecycle scanner** (auto-close + auto-destroy). Lifecycle is foundational; everything else relies on it.
2. **Phase B — Session recovery** (backend GET + SessionPage button + ChatShell replay prop).
3. **Phase C — Real auth flow** (backend request/verify endpoints + SMTP + Contacts allowlist + sidecar relay). Dev-code fallback when SMTP is down.
4. **Phase D — Summary email on close** (polling._process_close wires SMTP).
5. **Phase E — Admin alert on upload**.
6. **Phase F — Admin SessionsTab + Dashboard integration**.
7. **Phase G — Docs** (SPEC confirm, CHANGELOG, STATUS close).

### Risks / open questions

- **Pitfall 9 — Docker volume permissions**: session auto-destroy calls `shutil.rmtree` as root (backend container). Should just work; test with real OrbStack paths.
- **SMTP config discoverability**: if Daniel's SMTP isn't set up, most of Sprint 7 becomes silently-logging. D7=A means this is fine, but add a small "SMTP offline" banner at the top of the admin for visibility.
- **Session recovery vs destroyed**: if session was destroyed (ADR-005), the recovery GET returns 410 Gone. UI shows a polite "that session no longer exists".
- **Guardrail-ended sessions should still be recoverable** (read-only): users can see the session-ended state without being allowed to send new messages.

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

---

## Sprint 18 — pending hand-off (sesión cerrada 2026-05-03)

Daniel pidió guardar este estado para recuperarlo al reiniciar Claude — entregar verbatim cuando lo solicite.

### Código pusheado y ya en main
- ✅ Fase 1 — Top-K dinámico (`57b2231`)
- ✅ Fase 2 — Watcher debounce robusto (`57b2231`)
- ✅ Fase 3 — Chunking legal-aware (`2dcf569`)

### Bloqueado en Daniel, no en Claude
- 🟡 Repull en Portainer.
- 🟡 **Wipe & Reindex All** (Fase 3 cambia chunks → re-embed obligatorio).
- 🟡 Validación de los 8 tests (4 de Fases 1+2 + 4 de Fase 3, lista completa en CHANGELOG):
  1. "Compara vacaciones en los convenios de Amcor" cubre los 23 docs.
  2. "Lista los convenios FR del corpus" enumera los 15+.
  3. "Compara subidas salariales pactadas" cita cifras concretas.
  4. Subir N archivos seguidos → un solo reindex.
  5. "¿Qué dice el Artículo 23 del CBA Lezo?" → un chunk con clause_id="Artículo 23" + cuerpo entero.
  6. "Compara Artículo 37 entre Lezo y los franceses" → chunks etiquetados, no cortados.
  7. "Qué dicen los anexos del CBA Lezo" → chunks con clause_id="ANEXO II" / "ANEXO III".
  8. Citation panel muestra clause ids reales en los chips locator.

### Pendiente de Claude, condicional a la validación
- 🟦 **Si pasa todo:** cerrar Sprint 18 formalmente — actualizar `ARCHITECTURE.md` (§2 services + §6 failure modes para incluir `_segment_by_clause` y los nuevos thresholds), marcar Sprint en STATUS como CLOSED, decidir Sprint 19 (chunking ya está hecho, el siguiente candidate sería modo cita textual o las otras palancas parked).
- 🔴 **Si NO pasa algún test:** abrir Fase 4 según el síntoma:
  - Si recall cross-lingüe sigue cojeando → query rewriting + glossary técnico-legal (parked en IDEAS).
  - Si "lista convenios FR" falla → modo catálogo.
  - Si chats se ralentizan durante reindex → MVCC chat protection.

### Ideas paralelas apuntadas pero no en este sprint
- Modo cita textual (full-text search sobre los docs recuperados) — en `docs/IDEAS.md`. No requiere reindex, se puede añadir como Fase 4 si Daniel quiere.
- Top-K knobs editables desde admin RAG Pipeline (sliders para floor/ceil/per-doc + watcher seconds) — en el ticket Sprint 18 de IDEAS como add-on. Habíamos quedado en validar primero los defaults.

### Recomendación de orden al retomar
1. Daniel: repull + Wipe & Reindex + corre los 8 tests.
2. Reporta resultado.
3. Si todo OK, Claude cierra Sprint 18 formal y abren Sprint 19 con modo cita textual (idea pendiente de confirmar) o las otras palancas parked.
4. Si algo falla, Claude arregla en Fase 4 dentro del Sprint 18 antes de cerrar.

