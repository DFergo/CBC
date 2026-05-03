# CBC — Changelog

## Sprint 18 fase 4 — Top-K + watcher knobs admin-editables (2026-05-03)

### Why

Tras pushear Fases 1+2+3 con valores hardcoded, Daniel pidió poder tunear los 9 knobs desde el admin sin redeploy ("probar hasta dar con el sweet spot calidad/velocidad"). El patrón `runtime_overrides_store` de Sprint 15 ya cubría chunk_size + embedding_model + contextual_enabled — extendido para los nuevos.

### Backend

- `core/config.py`: 9 nuevos fields con defaults equivalentes a las constantes que vivían en `rag_service.py` y `rag_watcher.py` (`rag_top_k_floor=5`, `_ceil=40`, `_per_doc=2`, `rag_tables_top_k_floor=2`, `_ceil_single=6`, `_ceil_compare_all=12`, `rag_watcher_debounce_seconds=30`, `_max_hold_seconds=300`, `_lock_replan_seconds=30`).
- `runtime_overrides_store._TRACKED_FIELDS` extendido con los 9 — persistencia en `runtime_overrides.json` y aplicación al boot vía `apply_startup_overrides()`.
- `rag_service.compute_dynamic_top_k` y `compute_dynamic_tables_top_k` ahora leen de `backend_config.rag_top_k_*` en lugar de las constantes módulo (constantes eliminadas).
- `rag_watcher`: las 3 constantes `DEBOUNCE_SECONDS / MAX_DEBOUNCE_HOLD_SECONDS / LOCK_BUSY_REPLAN_SECONDS` reemplazadas por helpers `_debounce_seconds() / _max_hold_seconds() / _lock_busy_replan_seconds()` que leen de `backend_config` en cada llamada — un cambio admin aplica en el siguiente tick del debouncer sin restart.
- Endpoint nuevo `PATCH /admin/api/v1/rag/tuning` + `RAGTuningUpdate` Pydantic body. Wrapper en `rag_service.update_runtime_rag_tuning(**fields)` que valida rangos contra `_TUNING_RANGES` y la constraint cross-field `top_k_floor ≤ top_k_ceil` (también para tablas single + compare_all). Devuelve `{applied: <todos los valores efectivos>, changed: <campos que movieron>}`.
- `GET /rag/settings` ahora incluye un sub-objeto `tuning` con los 9 valores actuales.
- `deployment_backend.json`: `rag_watcher_debounce_seconds` 5 → 30 para que el JSON refleje el nuevo default consistente con Fase 2.

### Admin UI

- `api.ts`: nuevos types `RAGTuning`, `RAGTuningUpdateResult`. Función `updateRAGTuning(patch)` que hace PATCH /rag/tuning. `GlobalRAGSettings` extendido con `tuning?: RAGTuning`.
- `sections/RAGPipelineSection.tsx`: sección `<details>` colapsable nueva "Tuning avanzado" debajo del bloque Contextual Retrieval (visible cuando se expande RAG Pipeline). 9 sliders con rangos desde `TUNING_BOUNDS` (mirror del backend `_TUNING_RANGES`), botón Save (deshabilitado si no hay diff vs settings.tuning), botón Reset to defaults, pill verde "Saved · N campos actualizados" tras guardar, error inline en rojo si la validación backend rechaza.
- `i18n.ts`: 27 keys nuevas EN + ES (heading, subtitle, description, save, reset, saved, no_changes + un label + un hint por cada uno de los 9 sliders). Otros 13 idiomas caen a EN vía `useT` fallback.

### Cost / impact

- Coste de runtime: cero. Los reads de `backend_config` son atributo Python, sub-microsegundo.
- Reindex: NO necesario — todos los knobs son query-path / watcher-path, no indexing.
- UI: una nueva sección colapsable, default cerrada; admin que no la abre no ve diferencia.

### Validación pendiente Daniel post-repull

1. Admin → General → RAG Pipeline → expandir → ver nueva sección "Tuning avanzado / Top-K + parámetros del watcher".
2. Abrirla → ver 9 sliders con los defaults (5 / 40 / 2 / 2 / 6 / 12 / 30 / 300 / 30).
3. Mover algún slider, click Save → respuesta backend OK, pill verde "Guardado · N campos actualizados", reload muestra valor persistido.
4. Restart contenedor (Portainer recreate stack) → los valores tuneados sobreviven (vienen de `runtime_overrides.json`).
5. Validación cross-field: intentar `top_k_floor=10, top_k_ceil=5` debería rechazarse con error inline.

### Architecture impact

§5 ARCHITECTURE.md (Runtime control reference table) gana 9 filas nuevas. Pliego cuando Daniel valide.

---

## Sprint 18 fase 3 — Chunking legal-aware (clause splits + clause_id metadata) (2026-05-01)

### Why

Fases 1+2 abrieron el grifo de retrieval (top-K dinámico). Pero el chunker subyacente seguía partiendo artículos a mitad: un Artículo 23 largo de un CBA acababa con su cuerpo dividido en dos chunks por el SentenceSplitter, así el LLM citaba media regla. La validación externa (RAG-for-legal literature: Redis blog, arxiv 2504.16121, Milvus / Zilliz) confirma que el chunking estructural es la palanca low-cost-high-leverage para corpora legales — y CBAs comparten señal estructural fuerte: cada regla vive bajo un header numerado.

### Fix

**`CBCopilot/src/backend/services/rag_service.py`**:

- Nuevo `_CLAUSE_HEADER_RE` (~12 alternativas regex, case-insensitive, multiline). Detecta `Art. N` / `Art. 12.4` / `Artículo N` / `Article N` / `Articolo N` / `Cláusula N` / `Clause N` / `Section N.N.N` / `ANEXO [IVX]+` / `Anexo N` / `Annexe N`. Cubre ES + FR + EN + IT + uppercase / lowercase variants observadas en el corpus real (Lezo, Capsules France, Saint Seurin, Venthenat, Australian enterprise agreements).
- Nuevo `_segment_by_clause(text)` — devuelve `[(clause_id, body)]`. Body extiende desde un header (inclusive) al siguiente (exclusive) o EOF. Texto antes del primer header sale con `clause_id=""` (preámbulo). `[("", text)]` cuando el doc no tiene headers — fall-through al chunker tradicional, sin regresión.
- Normalización: `Artículo N` → conserva forma original. `Art. 12.4` / `Art 12.4` → canonicalizado a `Art. 12.4` (strip whitespace + dot consistency).
- `_parse_nodes` reescrito: extracted helper interno `_emit_clause_aware(text, meta)` aplica `_segment_by_clause` y luego SentenceSplitter por segmento. Cada segmento mete `clause_id` en su metadata. SentenceSplitter sigue capeando si la clause body excede `chunk_size` (e.g. Artículo 72 de Lezo = 17 543 chars → ~5 sub-chunks, todos con `clause_id="Artículo 72"`).
- Aplicado a TODOS los formatos: markdown header-nodes (segunda pasada tras MarkdownNodeParser), .pdf, .txt, .docx. PDFs australianos con `SECTION 13.4.1` también capturados.
- `Chunk` dataclass extendido con `clause_id: str = ""`.
- `query()` propaga `clause_id` desde node metadata al `Chunk`.

**`CBCopilot/src/backend/services/prompt_assembler.py`**:

- `_citation_label_for(chunk)` ahora prioriza `chunk.clause_id` sobre los anteriores fallbacks (page_label → article regex → annex regex → empty). Es autoritativo: viene del chunker, no del body — así cuando un chunk menciona Art. 23 en passing pero pertenece a Art. 17, citation correcta.

### Verificación en vivo (container actual, código nuevo cargado dinámicamente)

Sobre los 23 docs Amcor reales:

- `CBA Lezo (ES)` → 75 segments. Artículo 1 a 72, ANEXO II, ANEXO III. Cubre 100 % del CBA.
- `Amcor-FR-Venthenat-PremioAntiguedad-2023.md` → 9 segments (Article 1-9). Detectado.
- `Amcor-FR-PackagingFrance-IgualdadProfesional-2024.md` → 6 segments (ARTICLE 1-6 mayúscula). Detectado.
- `Amcor-FR-Chalon-AstreintasTecnicas-2025.md` → 3 segments (Article 11 dos veces — el doc reusa numeración entre capítulos; ambos quedan con el mismo clause_id, comportamiento esperado del regex).
- 11 docs FR sin clause headers (NAO, Prévoyance, FuncionamientoCSE, etc.) → 1 segment cada uno. Fall-through al SentenceSplitter normal.
- AU sample `SECTION 13.4 / 13.5` → detectado correctamente.

### Coste

- Re-embed obligatorio: cada chunk cambia su texto + metadata. **Wipe & Reindex All** tras repull para aplicar.
- Sin coste extra de embedding ni LLM por chunk (regex es O(n) sobre el texto).
- Ingest time: ~+5 % por la pasada regex. Imperceptible.
- Storage: idéntico (mismos N chunks, ligeramente distinto layout interno).

### Validación pendiente Daniel post-repull + Wipe

Además de los 4 tests del Sprint 18 fases 1+2:

5. Query `"¿qué dice el Artículo 23 del CBA de Lezo?"` → un chunk único cita `Artículo 23` con su cuerpo entero, locator `Artículo 23` en citation panel.
6. Query `"compara Artículo 37 entre Amcor Lezo y los franceses"` → chunks etiquetados con clause_id correspondiente, no fragmentos a mitad de regla.
7. Query `"qué dicen los anexos del CBA de Lezo"` → chunks etiquetados `ANEXO II` y `ANEXO III` (no fragmentos arbitrarios).
8. Citation panel: para cada source, los chips locator deben mostrar clause ids reales (`Art. 23`, `Section 13.4.1`, `ANEXO II`) en vez de `p. 14` o vacío.

Si validación 5-8 pasa además de 1-4, Sprint 18 cierra. Las antiguas fases 4-5 (modo catálogo, query rewriting cross-lingüe, glossary técnico-legal, MVCC chat protection) pasan a Sprint 19 sólo si la validación lo exige.

### Architecture impact

§4.2 SPEC y §2 ARCHITECTURE.md (Services layer → rag_service) ganan línea sobre `_segment_by_clause`. §6 ARCHITECTURE.md (failure modes) sin cambios. Plegamos en la doc cuando Daniel valide y cerremos sprint formalmente.

---

## Sprint 18 fases 1+2 — Top-K dinámico + watcher debounce robusto (2026-04-29)

### Why

Daniel uploaded 20 archivos (4 PDFs AU + 19 .md FR + 1 CBA ES = 23 docs) to the Amcor scope and ran three test queries:

1. "Compara vacaciones en los convenios de Amcor" → response covered ES + 2 PDFs AU; **15+ FR docs ignored** despite being indexed.
2. "Lista los convenios FR del corpus" → enumerated only 4 of 15+.
3. "Compara subidas salariales pactadas" → claimed "no figures available" though every CBA had its salary tables.

Diagnosis (logs + code read): `RAG_TOP_K_PER_SCOPE = 5`. With one scope holding 23 documents, the chat saw 5 chunks per turn — by definition incapable of covering the corpus. Cross-lingüe with technical terms (`enveloppe individuelle`, `prévoyance`, `astreinte`) made it worse, but the top-K cap was the dominant cause.

Same upload also triggered **three full reindex passes** (logs: `Built Chroma chunks for scope g-p1/amcor: 1 files → 390 nodes` then `... 24 files → 760 nodes` then `... 24 files → 760 nodes` again, ~50 s each). Browser uploads paced at >5 s between files break the existing debounce.

### Fase 1 — Top-K dinámico

**`CBCopilot/src/backend/services/rag_service.py`**:
- New `compute_dynamic_top_k(scope_keys)` — counts files via `_list_indexable_files` per scope, returns `min(max(5, total_files * 2), 40)`. 1 doc → 5 (status quo), 5 docs → 10, 23 docs → 40 (cap), 50 docs → 40 (cap; sprint 18 phase 3+ if recall still falls short at that scale).
- New `compute_dynamic_tables_top_k(scope_keys, is_compare_all)` — base `dynamic_top_k // 4`, floor 2, ceil 12 in Compare All / 6 single. Lower than prose because table cards are dense + a CSV.
- `query()` reranker pipeline: `fetch_k = max(rag_reranker_fetch_k, top_k * 3)` so the cross-encoder always has 3× headroom over the final K. Otherwise bumping `top_k` would make the reranker a no-op.

**`CBCopilot/src/backend/services/prompt_assembler.py`**:
- `_resolve_rag` calls `rag_service.compute_dynamic_top_k(scope_keys)` and passes the result to `rag_service.query_scopes`.
- `assemble`: same for `compute_dynamic_tables_top_k`.
- `effective_max_chunks = max(max_rag_chunks, len(chunks))` — prevents the static 20-chunk cap in `polling.py` from re-strangling the prompt to fewer chunks than the dynamic K just retrieved.
- `RAG_TOP_K_PER_SCOPE = 5` kept as the floor for `session_rag` queries (where the scope is one session's uploads, not corpus tiers).

**Verified live in container** before push:
```
compute_dynamic_top_k(['g-p1/amcor'])                         = 40
compute_dynamic_top_k(['g-p1/amcor', 'g-p1', 'global'])       = 40
compute_dynamic_top_k(['global'])                             = 5
compute_dynamic_tables_top_k(['g-p1/amcor'], False)           = 6
compute_dynamic_tables_top_k(['g-p1/amcor'], True)            = 10
compute_dynamic_tables_top_k(['global'], False)               = 2
```

### Fase 2 — Watcher debounce robusto

**`CBCopilot/src/backend/services/rag_watcher.py`**:
- `DEBOUNCE_SECONDS`: 5 → 30. Browser file picker pacing tolerated; bulk uploads collapse to one reindex.
- New `MAX_DEBOUNCE_HOLD_SECONDS = 300` ceiling. `_ScopeDebouncer` tracks `_first_event_at[scope]`; when an incoming event arrives within the hold window, the next timer fires after `min(DEBOUNCE_SECONDS, remaining_hold)`. Continuous slow uploads (e.g. iCloud trickling) reindex every 5 minutes anyway instead of being deferred forever.
- New `LOCK_BUSY_REPLAN_SECONDS = 30`. `_fire(scope)` probes `rag_service._build_locks[scope_key]` via `acquire(blocking=False)`. If a reindex is already running, defer the watcher fire 30 s rather than queueing behind the lock — keeps chat queries unblocked for the duration of the in-flight build.

### Cost / impact

- Prompt size: max ~80 k chars in worst case (40 chunks × ~2 k chars + tables block). Comfortable inside the 130 k num_ctx Daniel runs on gemma4:26b.
- TTFT: rerank scales from 5×3=15 candidates to 40×3=120 candidates per scope. ~1-2 s extra latency on cold cache. Steady-state with prefix cache hot is unchanged.
- Watcher behaviour: small individual uploads still trigger a reindex (30 s after the last event). Bulk uploads collapse to one reindex regardless of pacing inside the hold window.

### Architecture impact

§5 of `docs/architecture/ARCHITECTURE.md` (Runtime control reference) — top-K is no longer a fixed knob; describe `compute_dynamic_top_k` as the policy. §6 (Failure modes) — add "watcher amplification" as a now-prevented mode. Will fold into the doc when Daniel validates and we close the sprint formally; for now the CHANGELOG carries the canonical record.

### Validation pending Daniel post-repull

1. Re-run "Compara vacaciones en los convenios de Amcor" — expected: response covers all 23 docs (or names which ones lack a vacaciones clause).
2. Re-run "Lista los convenios FR del corpus" — expected: 15+ filenames listed.
3. Re-run "Compara subidas salariales pactadas" — expected: numbers from each CBA cited.
4. Trigger another 20-file upload — expected: a single reindex log line, not three.

If validation 1-3 passes, sprint closes here. If it doesn't, fases 3-5 land next: modo catálogo, query rewriting cross-lingüe, glossary técnico-legal, MVCC chat protection.

---

## Sprint 17 — Living Architecture Documentation (2026-04-24)

Sprint 16 closure flushed enough drift that re-discovering the architecture from source on every Claude session became visibly wasteful. Sprint 17 lands a single living document plus the discipline to keep it honest.

### Deliverables

**New file — `docs/architecture/ARCHITECTURE.md` (~580 lines).** Ten sections, paste-ready dual-use:
- §1 System overview + textual architecture diagram.
- §2 Services layer — every file under `CBCopilot/src/backend/services/` with responsibility, state, callers, and the admin UI path that drives it.
- §3 Data flows — chat turn, RAG query (prose), table query (Sprint 16), document ingest, Compare All, session lifecycle.
- §4 Storage layout — the full `/app/data/` tree with writer + reader per path.
- §5 Runtime control reference table — every admin-editable knob with UI path, persistence file, reader service, default, and cost of flipping. Covers RAG settings, three LLM slots + routing + thinking + max_concurrent_turns, branding, prompts, glossary, organizations, contacts, SMTP, frontends, companies, session settings, document metadata.
- §6 Failure modes — Stop / cancel, inactivity timeout, circuit breaker, wipe & reindex, partial reindex detection, watcher debouncing, prefix-cache cold spots, concurrent reindex (Sprint 16 #38 fix), session destroy.
- §7 Dependencies and integrations — Ollama, LM Studio, Chroma, BGE-M3, bge-reranker-v2-m3, pdfplumber, watchdog, sentence-transformers / llama-index-*, FastAPI / uvicorn / pydantic. Each: where pinned, graceful degradation, Dockerfile pre-download (or absence thereof).
- §8 Architectural invariants — 11 hard invariants tied to the file that enforces each.
- §9 Admin UI map — walk-through of every tab (General, Frontends, Sessions, Registered Users, language selector) with each control wired to backend service + persistence file + behaviour.
- §10 Pointers to SPEC, MILESTONES, STATUS, CHANGELOG, decisions (ADR log), lessons-learned, hrdd-helper-patterns, IDEAS, Ollama_UNI_Tools_Config.

**Updated — `CLAUDE.md` "Key Documents — READ ORDER".** ARCHITECTURE.md is now item 1, before MILESTONES + SPEC. The original `architecture/overview.md` stays in the list as historical context (item 7) but ARCHITECTURE.md supersedes it.

**Updated — `.claude/commands/sprint.md` (the `/sprint` skill).** Planning gains a step 1 "Read ARCHITECTURE.md" before MILESTONES. Finalizing gains an explicit "Update ARCHITECTURE.md if this sprint changed services / data flows / storage / runtime controls / dependencies / invariants — otherwise note 'no architecture changes this sprint' in the CHANGELOG." This is the discipline that keeps the doc honest without a drift-detection sub-agent.

**New file — `docs/knowledge/architecture-drift-audit.md`.** Records the deferred decision on the drift-detection sub-agent: what it would do, why we're not building it now (single dev + high Claude involvement + the workflow change above is the cheapest path), four concrete triggers to revisit. Future Claude / developer reads this before re-debating.

### Sprint 16 idea capture

Daniel surfaced a use-case while walking the live system: the chat refuses to give a verbatim quote of a CBA article ("I don't have access to the source text") because it only has paraphrased chunks. The CBAs are on disk and could be searched literally for the matched fragment when the user asks for a "cita textual / verbatim / transcribe". Captured as a candidate sprint in `docs/IDEAS.md` under "Modo cita textual — full-text search sobre los docs recuperados en la sesión". Not scheduled.

### Architecture impact of this sprint

By the new `/sprint` step 2 rule: Sprint 17 added one document (`ARCHITECTURE.md`) and a knowledge note, but no services, data flows, storage paths, runtime controls, dependencies, or invariants changed. The doc itself describes the post-Sprint-16 state. Self-referential but consistent.

### Files touched

- `docs/architecture/ARCHITECTURE.md` (new, ~580 lines)
- `docs/knowledge/architecture-drift-audit.md` (new, ~40 lines)
- `docs/IDEAS.md` (added one entry, "Modo cita textual")
- `CLAUDE.md` (READ ORDER reordered, two new entries)
- `.claude/commands/sprint.md` (Planning + Finalizing extended)
- `docs/STATUS.md`, `docs/CHANGELOG.md` (sprint close)

---

## Sprint 16 follow-ups — UX polish + concurrency tightening (2026-04-24)

Three items surfaced during Daniel's post-Sprint-16 live validation. All resolved in this commit; Sprint 16 closed.

### Task #36 — Disambiguate tables that share a source_location

**Problem:** the Amcor Lezo CBA only has one top-level `####` heading, so all 4 extracted tables ended up with the same `name` and `source_location` (the document title). The admin listing + Chroma card texts became four indistinguishable rows — cosmetic but confusing for validation.

**Fix** (`CBCopilot/src/backend/services/table_extractor.py`):
- After the main extraction loop, count tables per source_location. When two or more collapse onto the same location:
  1. Append the first 3 column names as a discriminator (`"Convenio... — Coef., Al día, A la noche"`) — works when different tables in the same section have different columns.
  2. If column-based disambiguation still leaves duplicates (e.g. two tables with identical headers), add a `"(tabla N de M)"` ordinal suffix.
- Leaves names alone when the table already had a unique label. No-op for single-table documents.

### Task #37 — Redesign admin UI: tables as a compact dropdown under each company

**Problem:** the Sprint 16 `TablesSection` mounted at three tiers (General, Frontends, Companies) as a full-width card with a 5-row CSV preview inline per table. With 50 CBAs per company the page would be unscrollable. Global + frontend tiers barely have documents anyway.

**Fix:**
- `admin/src/GeneralTab.tsx`: remove `TablesSection` from the global tier.
- `admin/src/FrontendsTab.tsx`: remove `TablesSection` from the frontend tier.
- `admin/src/sections/TablesSection.tsx`: rewrite as a collapsed-by-default `<details>` element. Summary line shows `Tablas extraídas (N)` + the Re-extract button. On expand, a flat list per document: `name · source_location · N rows · CSV download link`. No inline previews. Compact enough to drop inside `CompanyManagementPanel`'s existing flow without overwhelming the page.
- Intent shift: the admin just needs to verify "did my CBA produce tables, and can I pull one if I want to check it?". The CSV link stays for deep inspection; the 5-row inline preview was overkill.

### Task #38 — Eliminate the redundant 2× `_build_index` during wipe-and-reindex

**Problem:** `wipe_chroma_and_reindex_all` triggers two full `_build_index(g-p1/amcor)` passes (each ~23 s with BGE-M3 embedding + table extraction). The Fase 0.b per-scope lock prevents chunk duplication, so the final count is correct (44 / 4), but the wipe takes twice as long as it should. The re-extract path (single-scope reindex) has only one pass, which pinpointed the race: a concurrent `get_index()` from the chat path or the UI firing during the wipe finds 0 chunks mid-build and re-enters `_build_index`.

**Fix** (`CBCopilot/src/backend/services/rag_service.py`):
- `_build_locks` now uses `threading.RLock` instead of `threading.Lock`. Reentrant semantics are needed for the next step without deadlocking.
- `get_index()` now acquires the per-scope `build_lock` before deciding whether to build. If the wipe thread is inside, `get_index` waits, then re-checks `_scope_chunk_count`. By then the wipe's insert has landed, so it just wraps the existing chunks instead of firing a redundant rebuild.
- No change to `_build_index` itself — it still acquires the same lock, now as a reentrant acquire from either caller.
- Observable impact: Wipe & Reindex All should drop from ~53 s to ~27 s on Daniel's 1-CBA corpus.

---

## Sprint 16 — Structured Table Pipeline + Fase 0.b duplicado fix (2026-04-24)

### Why

Daniel's post-Fase-0 test revealed two problems:

1. **88 chunks in `cbc_chunks` where there should be 44.** The Amcor Lezo CBA produced 44 chunks at chunking, yet Chroma stored 88. Direct inspection confirmed every chunk was duplicated — same text, same file metadata, different UUIDs. Cause: `_build_index` had no per-scope serialisation, so two threads (wipe-and-reindex + a concurrent `get_index()` or watcher callback) could both clear the scope (no-op on an empty collection) and both insert 44 nodes → 88 chunks. BM25 also saw 88 nodes, so retrieval ranked duplicates as higher-weight matches. Every subsequent Wipe & Reindex doubled the count (risk of 176, 352…).
2. **Salary tables in CBAs remain invisible to vector RAG.** Even with Sprint 15's clean chunker + BGE-M3, a 30-row × 6-column salary grid embeds as one opaque vector that loses to prose chunks talking about salaries without containing them. "Dame la tabla salarial de Lezo" got prose paraphrases with hallucinated numbers and even a mangled filename (`Amfor_Flexibles`). With 200+ CBAs on the roadmap, this scales poorly.

### Fase 0.b — Deduplication fix

- `CBCopilot/src/backend/services/rag_service.py`: new per-scope `_build_locks: dict[str, threading.Lock]` + `_get_build_lock(scope_key)` helper. `_build_index(scope_key)` now wraps its entire body in `with _get_build_lock(scope_key):`. The second thread to arrive waits, enters, `_delete_scope` removes what the first just inserted, re-ingests cleanly. Wasted CPU on the second build but correct final chunk count.
- The race condition didn't require `_discover_all_scope_keys` to duplicate (verified in live container — it returns the correct `['global', 'g-p1/amcor']`) nor the watcher to misbehave. It was pure concurrent `_build_index` callers, of which there are several: the admin wipe endpoint via `asyncio.to_thread`, `get_index()` from the chat query path, and possibly the debounced watcher.

### Fase 0.b — Contextual Retrieval stays off by default

- `CBCopilot/src/backend/core/config.py`: updated the `rag_contextual_enabled` comment to reflect that CR's main value (tabular retrieval) is now covered by the Structured Table Pipeline. Default stays `False`. Code / toggle / endpoint left intact for users who want to experiment with prose-heavy corpora.

### Sprint 16 — Structured Table Pipeline

**New backend service:** `CBCopilot/src/backend/services/table_extractor.py`

- Dataclass `TableSpec` with stable sha1-16 `id`, `doc_name`, `name`, `description`, `source_location`, `csv_text`, `columns`, `row_count`, plus `as_card_text()` (for embedding) and `as_manifest_dict()` (for JSON persistence).
- `extract_markdown_tables(md_text, doc_name)` — regex-based pipe-table detection. Walks header chains up the document to build a `"ANEXO I › Tabla A — Salario base"` location. Captures nearby prose as description. Handles cells with commas, irregular row widths, and multiple tables per document.
- `extract_pdf_tables(pdf_path, doc_name)` — pdfplumber `page.extract_tables()`. Returns `[]` for image-only PDFs (accepted low-fidelity; admin sees an "0 tables extracted — document may be scanned" warning).
- Persistence at `{scope_root}/tables/{doc_stem}/{table_id}.csv` + `manifest.json`. Sanitised stems prevent filesystem escape.
- `save_tables_for_doc`, `load_manifest`, `load_csv`, `list_scope_tables`, `delete_scope_tables`, `delete_doc_tables`.

**Dependency:** `pdfplumber>=0.11` added to `CBCopilot/src/backend/requirements.txt`. Pure Python (pdfminer.six under the hood), no Dockerfile pre-download step needed.

**Chroma integration:** `CBCopilot/src/backend/services/rag_service.py`

- New `cbc_tables` collection on the same `PersistentClient` — `client.reset()` wipes both in one atomic step.
- `_get_tables_collection()` lazy-init.
- `_extract_and_embed_tables(scope_key, files)` called from `_build_index` after prose chunks insert. Extracts tables, persists CSVs, batch-embeds cards via `BGE-M3.get_text_embedding_batch`, upserts to Chroma. Also cleans up orphan on-disk dirs (docs removed since the last extraction).
- `query_tables(scope_keys, query_text, top_k=2)` for runtime retrieval. Returns dicts with `scope_key`, `doc_name`, `table_id`, `name`, `source_location`, `row_count`, `csv_text`, `distance`.
- `_delete_scope(scope_key)` extended to also drop table cards from `cbc_tables`.
- `_purge_all_tables_on_disk()` called from `wipe_chroma_and_reindex_all` — clears `{scope}/tables/` across every scope so the next reindex starts clean.

**Prompt integration:** `CBCopilot/src/backend/services/prompt_assembler.py`

- After `_resolve_rag`, call `rag_service.query_tables(scope_keys, q, top_k=2)` (`top_k=4` in Compare All).
- New `_render_tables(table_hits)` emits a `## Relevant tables` section with each table's name + source + location, then the CSV fenced as ```csv```. Per-table cap of 6 000 chars with a `[... truncated ...]` note.
- `AssembledPrompt.layers["tables"]` added — visible in the existing per-section size-breakdown log.
- `sources` SSE event extended: table hits carry `kind: "table"`, `table_id`, `table_name`, `source_location`, `row_count`.

**Admin API:** `CBCopilot/src/backend/api/v1/admin/tables.py`

- `GET /admin/api/v1/tables?frontend_id=…&company_slug=…` — per-scope list grouped by document, each table with 5-row preview inline.
- `POST /admin/api/v1/tables/reextract` — full scope reindex (prose + tables), offloaded via `asyncio.to_thread` (Fase 0 pattern).
- `GET /admin/api/v1/tables/{fid}/{slug}/{doc}/{table_id}.csv`, plus `-global` and `-frontend` variants — plain-text CSV download for admin preview.
- Router registered in `main.py`.

**Admin UI:** `CBCopilot/src/admin/src/sections/TablesSection.tsx`

- Per-scope list grouped by source doc. Each table row shows name, source_location, row count, optional description, a 5-row CSV preview rendered as an HTML table, and a "Download CSV" link.
- "0 tables extracted" warning for docs that produced nothing (likely scanned PDFs).
- Scope-level "Re-extract tables" button with saving/done status.
- Mounted in `GeneralTab` (global), `FrontendsTab` (frontend tier), and `CompanyManagementPanel` (company tier) — exactly parallel to `RAGSection`.
- `api.ts` gains `listTables`, `reextractTables`, `tableCsvUrl` helpers + `TableCard` / `TableDocGroup` / `TablesForScope` types.
- 11 new i18n keys in EN + ES (`section_tables`, `tables_heading`, `tables_description`, `tables_reextract`, `tables_reextracting`, `tables_reextract_done`, `tables_empty`, `tables_summary`, `tables_doc_count`, `tables_doc_zero_warning`, `tables_rows`, `tables_download`). Other languages fall back to EN via `useT`'s existing fallback chain.

**Frontend citations:** `CBCopilot/src/frontend/src/components/CitationsPanel.tsx`

- `CitationSource` type extended with `kind`, `table_id`, `table_name`, `source_location`, `row_count`.
- When `kind === "table"`, the panel renders an amber "Table" badge + the location + row count. No download action — the CSV was already injected into the prompt.
- Dedup key updated to distinguish two tables from the same doc by `table_id`.
- 2 new i18n keys in EN + ES: `citations_table_badge`, `citations_table_rows`.

**Docs:**

- `docs/SPEC.md` — new §4.12 Structured Table Pipeline.
- `docs/architecture/decisions.md` — new ADR-009 covering rationale, alternatives considered, and trade-offs.
- `docs/STATUS.md` — Sprint 16 closed.
- `docs/CHANGELOG.md` — this entry.

### Acceptance checklist (Daniel post-repull)

1. Docker repull backend + frontend + admin images via Portainer.
2. In admin: confirm `rag_contextual_enabled` is `false` (runtime_overrides may still have it from a prior toggle — if so, toggle it OFF from the RAG Pipeline section).
3. Click **Wipe & Reindex All** (settings unchanged) — verifies Fase 0.b fix. Expected: one "Built Chroma chunks for scope g-p1/amcor: 1 files → 44 nodes" log line, BM25 "rebuilt retriever for scope g-p1/amcor (44 nodes)". `docker exec ... python -c "import chromadb; ...; print(col.count())"` returns 44.
4. Open admin → General → **Tables**. Should list extracted tables from the Amcor Lezo CBA with 5-row previews. Same at frontend tier and company tier.
5. Download one CSV via the "Download CSV" link — should return plain-text with the full table.
6. Open a chat, ask "dame la tabla salarial de Lezo". Expected: response includes the actual numbers from the CSV (no paraphrasing), and the sidepanel shows an amber "Table" badge entry alongside the document entries.
7. While a chat turn is mid-stream, open admin → Frontends tab. Should load instantly (Fase 0 concurrency).
8. Trigger "Re-extract tables" in the TablesSection. Should return within seconds and leave the total table count unchanged.

---

## Sprint 16 Fase 0 — Admin reindex no longer blocks the event loop (2026-04-24)

### Problem

During a Contextual Retrieval reindex Daniel noticed the entire backend freezing — the admin UI's Frontends tab returned nothing, the chat replied "waiting for slot", and `polling_loop` stopped ticking. Logs confirmed nothing was crashing; the request simply never progressed while the reindex ran.

Root cause: four of the five admin reindex endpoints in `api/v1/admin/rag.py` were declared `async def` but called the **sync** `rag_service.reindex_all_scopes()` / `rag_service.reindex_frontend_cascade()` / `rag_store.reindex()` directly inside the handler. That pins the FastAPI event loop on the current task until the reindex returns (minutes to hours with CR on), starving every other async task — admin routes, polling loop, sidecar pulls. Only `wipe_and_reindex_all` was already offloading correctly to a worker thread (Sprint 15 phase 6).

### Fix

All five reindex endpoints now offload the sync work to a thread via `asyncio.to_thread(...)`:

- `POST /admin/api/v1/rag/reindex`
- `POST /admin/api/v1/rag/reindex-all`
- `POST /admin/api/v1/rag/reindex-frontend-cascade/{frontend_id}`
- `POST /admin/api/v1/rag/wipe-and-reindex-all` (already done in Sprint 15; tidied up to use the module-level `asyncio` import)
- `POST /admin/api/v1/rag/settings/contextual` (both the happy path and the rollback branch)

The reindex still runs synchronously from the HTTP client's point of view — the admin still sees a spinner, the response still carries the per-scope stats — but the Python event loop is free to process other requests concurrently. Since the heavy inner work is mostly I/O-bound (HTTP calls to Ollama for embeddings + CR summaries), the GIL releases cleanly in the worker thread and the main thread has plenty of CPU for the chat path.

### Files touched

- `CBCopilot/src/backend/api/v1/admin/rag.py` — `import asyncio` at top, 4 new `await asyncio.to_thread(...)` wraps, 1 cleanup in the existing wipe handler.

### Validation (pending Daniel after repull)

- Trigger a long reindex (CR toggle or Wipe & Reindex All) and, while it's running:
  - Open Admin → Frontends — should list frontends immediately.
  - Send a chat message — should get a response (dependent on a non-CR inference slot being free; not on the reindex finishing).
  - Confirm `polling_loop` still ticks in backend logs.

### Why this is Sprint 16 Fase 0

Without this fix, Sprint 16's Structured Table Pipeline can't be validated end-to-end: every table-extractor reindex would lock the admin UI, making QA painful. Better to land it before the table code.

---

## Sprint 15 phase 3 — Editable RAG settings + close item I (2026-04-24)

Closes the pipeline drift discovered during phase 2 empirical investigation: `deployment_backend.json` had been pinning `rag_embedding_model` to the legacy `all-MiniLM-L6-v2` (384-dim) and `rag_chunk_size` to `512`, silently overriding Sprint 9's code defaults of `BAAI/bge-m3` (1024-dim) and `1024`. Daniel's deployment had been running a half-deployed Sprint 9 state — reranker updated, embedder not — without anyone noticing.

### Config drift fix

- `CBCopilot/config/deployment_backend.json`: `rag_embedding_model: all-MiniLM-L6-v2 → BAAI/bge-m3`, `rag_chunk_size: 512 → 1024`.

### Admin-editable RAG settings

Both changed values are now controlled from the admin panel RAG Pipeline section:
- **Embedding model**: dropdown, `BAAI/bge-m3` (default) vs `sentence-transformers/all-MiniLM-L6-v2`. Both are pre-downloaded in the Dockerfile so switching is instantaneous on disk; the wipe-and-reindex cost is the slow part.
- **Chunk size**: slider, 512 / 1024 / 1536 / 2048 tokens. 1024 is the default for CBAs; 1536/2048 recommended when large salary tables or annexes keep getting split.
- Reranker + retrieval strategy stay read-only (only one reranker pre-downloaded).

Editor UX: admin changes draft values, clicks Save → values update in-memory via `PATCH /admin/api/v1/rag/settings`. Save does NOT reindex — admin must click the destacado red "Wipe & Reindex All" button to actually apply the new settings against the corpus.

### Wipe & Reindex All

New `POST /admin/api/v1/rag/wipe-and-reindex-all` endpoint + UI button. Does:
1. Drops every in-memory cache: `_indexes` (LlamaIndex wrappers), `_bm25_cache` (Sprint 15 phase 2), `_embed_model`, `_reranker`.
2. Closes the Chroma client + `rm -rf /app/data/chroma/` entirely.
3. Calls `reindex_all_scopes()` to re-ingest every scope with the current settings.

Required after any embedding-model or chunk_size change (dim/bucketing changes break the existing collection). Synchronous; on a big corpus it can take several minutes. Queries against any scope return empty during the run — intended.

### Global reindex cascades

`RAGSection.onReindex` at the global tier now calls `reindexAllRAG()` instead of `reindexRAG(undefined, undefined)`. Rationale: global-tier settings (embedder, chunk size, Contextual Retrieval) apply to every scope, so rebuilding only the global scope would leave frontend + company scopes holding stale chunks. At other tiers `onReindex` still means "just this scope" — that semantic stays correct there.

### Validation allowlists (backend)

`rag_service.update_runtime_rag_settings()` validates:
- `chunk_size ∈ {512, 1024, 1536, 2048}` — rejects arbitrary values.
- `embedding_model ∈ {BAAI/bge-m3, sentence-transformers/all-MiniLM-L6-v2}` — rejects values whose weights aren't pre-downloaded by the Dockerfile.

### Files touched

Backend:
- `CBCopilot/config/deployment_backend.json` — two value changes
- `CBCopilot/src/backend/services/rag_service.py` — `wipe_chroma_and_reindex_all()`, `update_runtime_rag_settings()`, allowlists
- `CBCopilot/src/backend/api/v1/admin/rag.py` — PATCH `/rag/settings`, POST `/rag/wipe-and-reindex-all`

Admin:
- `CBCopilot/src/admin/src/api.ts` — `updateRAGSettings()`, `wipeAndReindexAll()` + types
- `CBCopilot/src/admin/src/sections/RAGPipelineSection.tsx` — rebuilt: editable dropdown + slider + Save + Wipe (destacado red)
- `CBCopilot/src/admin/src/sections/RAGSection.tsx` — `onReindex` cascades at global tier
- `CBCopilot/src/admin/src/i18n.ts` — 12 new keys in EN + ES

Docs:
- `docs/MILESTONES.md` — item I marked CLOSED with resolution notes
- `docs/CHANGELOG.md` — this entry

### Deploy + first-time use

1. Portainer re-pull backend + frontend.
2. Admin panel → General → RAG Pipeline → expand.
3. Verify current values: embedder should now say `BAAI/bge-m3`, chunk size `1024`.
4. (First time after this deploy) click **Wipe & Reindex All** — rebuilds every scope against the new settings. Expect minutes on big corpora.
5. After the run, test a query. Logs in OrbStack should show:
   - `chunker: ...  → N nodes (max=... mean=...)` during each scope's reindex
   - `Loaded embedding model BAAI/bge-m3` once (on first embed call post-wipe)
   - `rag.query scope=... returned=5 max_chunk=~4000 chars` at query time

### No regression of Sprint 15 phase 1/2 work

- MarkdownNodeParser + SentenceSplitter fix (phase 1): unchanged.
- BM25 retriever cache (phase 2, item H): unchanged. `wipe_chroma_and_reindex_all` calls `_invalidate_bm25_cache(None)` to drop the cache cleanly.
- Glossary bug fix (phase 2): unchanged.

---

## Sprint 15 — RAG chunker fix + observability (2026-04-24)

### Why this sprint

Daniel's post-Sprint-14 QA showed persistent 60-90 s TTFT even on a single-user single-CBA test, not fixed by any of the Sprint 14 work. Live diagnosis via `docker exec` on the OrbStack backend revealed:

- `prompt assembled: 133232 chars, 1 RAG chunks` for every turn
- System prompt stored on disk was 94% one section (`## Retrieved CBA / policy excerpts`: 125 204 chars)
- The CBA file itself is 127 196 chars
- Chroma's `cbc_chunks` collection had **one single embedding of 125 095 chars** for the entire CBA
- BGE-M3's `max_seq_length` is 8 192 tokens → that single chunk's embedding had been silently truncated to the first ~30% of the document
- At 200 CBAs this would scale linearly badly: each document reduced to a lossy first-30% embedding, no semantic granularity

### Root cause

`CBCopilot/src/backend/services/rag_service.py:257` — `md_parser = MarkdownNodeParser()` with no chunk-size cap. `MarkdownNodeParser` splits only on markdown headers and **does not honour `Settings.chunk_size=1024`**. A CBA structured with few top-level headings (or with ANEXO I as a huge section) emits as one giant node per document. HRDD Helper doesn't have this bug because its `rag_service` routes everything through `VectorStoreIndex.from_documents(..., chunk_size=...)` which always caps. CBC's Sprint 9 RAG overhaul introduced per-extension routing to preserve markdown header context — the intent was right, the implementation was asymmetric (caps for .pdf/.txt, no cap for .md).

### Fix — `rag_service._parse_nodes`

Pipe MarkdownNodeParser output through a second-pass `SentenceSplitter(chunk_size=1024, chunk_overlap=200)`. Header metadata is preserved on every sub-chunk by re-wrapping each header-node's text in a fresh `Document` carrying the parent's metadata, then re-splitting. Sprint 11 Phase B inline citations (that reference `header_path` metadata) continue to work unchanged.

Added a defensive WARNING log when any produced node exceeds 30 000 chars (~8 192 tokens) — should never fire post-fix, but catches regressions if someone rewires the chunker.

### Observability additions (Daniel explicitly asked)

Six new INFO log lines across the RAG pipeline so future regressions are diagnosable from OrbStack logs without dumping session JSONs:

- `rag_service._parse_nodes` — per-document: `chunker: {name} → N nodes (max={X} chars, min={Y} chars, mean={Z} chars)`. Warning variant fires if any node > 30 000 chars.
- `rag_service.query` — per-scope: `rag.query scope={key} q={first 50 chars}... fetch_k={F} rerank_top={R} returned={N} max_chunk={X} chars, mean={Y} chars`
- `rag_service.query_scopes` — aggregate: `rag.query_scopes n_scopes={N} total_chunks={M} total_chars={X}`
- `prompt_assembler.assemble` — per-section breakdown: `prompt_assembler: total={X} chars, N chunks used, sections: core=A guardrails=B role=C context=D glossary=E organizations=F rag=G`

### Empirical validation (run in OrbStack container against real CBA)

Exercised `_parse_nodes` with the real `CBA—Amcor_Flexibles—Lezo—Spain.md` (125 097 chars):

```
Live Settings.chunk_size=1024, chunk_overlap=200

[BEFORE FIX] MarkdownNodeParser alone → 1 nodes
  node #1: 125095 chars

[AFTER FIX] md + sentence-splitter → 45 nodes
  max=4070 chars, min=1183 chars, mean=3336 chars
  nodes >4500 chars (BGE-M3 risk): 0
  nodes >30000 chars (definite truncation): 0
  nodes with header metadata preserved: 45 / 45
```

No chunks exceed BGE-M3's cap; all 45 chunks carry both `file_name` and `header_path` metadata. Sprint 11 Phase B inline citations continue to work.

### Files touched

- `CBCopilot/src/backend/services/rag_service.py` — chunker fix in `_parse_nodes` + per-document log + BGE-M3 truncation warning + query/query_scopes observability logs.
- `CBCopilot/src/backend/services/prompt_assembler.py` — per-section size breakdown log in `assemble()`.

No changes to admin UI, config schema, Dockerfiles, dependencies. Session JSONs on disk don't need migration — the next turn's `assemble()` overwrites `session.system_prompt` with the new smaller prompt automatically.

### Expected effect after deploy + reindex

- First-question TTFT: 60-90 s → 20-30 s (prefill work drops 5-7×)
- Re-question TTFT: prefix cache works fully → ~3-10 s (matches Daniel's pre-Sprint-13 memory)
- Retrieval quality: ~120 granular embeddings per CBA vs 1 truncated embedding → dramatically better for questions referencing later sections
- 200-CBA scale: top-k=5 always returns 5 granular chunks regardless of corpus size

### Operational note — REINDEX REQUIRED

Existing Chroma indices on disk were built with the old chunker (1 giant chunk each). The fix changes future ingestions only. To benefit, admin must click "Reindex" per scope in the admin panel (existing Sprint 5 button). Without reindex, live queries keep returning the old 1-giant-chunk per document.

### Remaining audit items (plan documented in STATUS.md, not implemented)

A — Startup scan for oversized legacy chunks (diagnostic WARNING).
B — Admin "reindex needed" banner when legacy chunks detected.
C — `GET /admin/api/v1/rag/diagnostics` endpoint for per-scope chunk-size distribution.
D — `session_rag.get_chunks_for_files` force-injection size cap (user uploads).
E — Config guard if `rag_chunk_size` configured >8 192 tokens (BGE-M3 truncation risk).
F — Prompt stability across turns (pre-existing architectural; post-fix impact much lower).
G — Ollama preload of CBC's inference model (eliminates cold-load).

Each is ~1-hour work. All deferred — none block Sprint 15's user-visible win.

---

## Sprint 14 post-deploy follow-ups (2026-04-24, same day)

Four fixes landed in the hours after Sprint 14's main commit (`6e175e0`) went to Portainer. Daniel's live QA surfaced them in order; the log captures all four so the sprint closes cleanly.

### `a09607e` — Admin UI polarity fix

Sprint 13's checkbox label combined "Disable reasoning" (title) with "Enabled" (checkbox reusing the compression i18n key) — a double-negative that left admins unsure whether the model was actually thinking. Replaced with a `<select>` of OFF / ON under the neutral title "Thinking / Reasoning". OFF (default) keeps thinking off. The backend field `disable_thinking` stays as-is; the UI binding inverts (`checked={!cfg.disable_thinking}`) so the visible semantics read naturally. Renamed i18n keys: `llm_disable_thinking` → `llm_thinking_mode`, description updated. EN + ES.

Files: `admin/src/sections/LLMSection.tsx`, `admin/src/i18n.ts`.

### `5e75a78` — Diagnostic log + qwen3 scope for `/no_think`

Two related changes in `llm_provider.py`:

- **Scoped the `/no_think` suffix to qwen3 models only**, via a small `_is_qwen3_model(slot.model)` helper. Sprint 13 had been appending the suffix to the last user message for any thinking model; for gemma3-think, deepseek-r1 etc. this was literal user text polluting the prompt. (Superseded by `edc3a99` later — see below.)
- **Added a single INFO log line per outgoing LLM request**: provider, model, `num_ctx`, `disable_thinking`, whether `body["think"]=False` landed, whether the qwen3 suffix applied, whether the system-prompt hint was injected, message count. Visible in OrbStack container logs without any extra config — Daniel can read without pasting, and from this session I can `docker logs cbc-backend-cbc-backend-1` directly.

### `f6743b7` — Fire-and-forget tick dispatch (Sprint 14 regression fix)

Sprint 14's original implementation of `_process_frontend` did `await asyncio.gather(*msg_tasks)` inside the function, which meant the polling loop blocked until EVERY in-flight stream completed. A single 30 s turn froze every frontend's drain for 30 s. User-visible symptoms Daniel reported after live deploy:

- Device B sending mid-stream of Device A's turn: B queued invisibly until A finished.
- Backend completing the turn successfully (response visible in admin session log) but the user's chat showing "Algo salió mal" — `_push_chunk` for terminal events (`done`) could timeout silently under SSE contention, leaving the browser's EventSource to strike out on `onerror` after 3 consecutive errors.
- Perceived slowness overall: parallelism was paying the NP=4 memory cost without the concurrency benefit.

Fix:

- `_process_frontend` now uses `asyncio.create_task` + a module-level `_inflight_turns: set[asyncio.Task]` (strong refs via done-callback discard). Tick returns as soon as tasks are dispatched; the semaphore inside `_process_message_safe` still caps effective concurrency at `max_concurrent_turns`.
- `_push_chunk` retries terminal events (`done`/`error`/`cancelled`) once with 500 ms backoff. Non-terminal tokens continue to fail silently. Drop-log level raised from INFO to WARNING for terminal failures.
- Added diagnostic logs: `turn start (N msgs, inflight_turns=X)`, `first token after X.Xs`, `turn end (OK|ERROR|CANCELLED) elapsed=X.Xs ttft=Y.Ys chars=N tokens≈M`.

### `edc3a99` — Dropped `/no_think` user suffix entirely (prefix-cache killer)

Diagnosed live from the OrbStack logs surfaced by `f6743b7`'s new diagnostic lines. Re-question TTFT was 44-82 s instead of the ~10 s Daniel remembered pre-Sprint-13.

**Root cause:** Sprint 13's `_apply_no_think` appended ` /no_think` to the LAST user message only. Since session_store keeps user messages raw (no suffix persisted), each turn re-applies the suffix to whichever message is now the last user. On Ollama's KV cache:

- Turn 1: sends `[SYS][USER1+suffix]` → Ollama caches that prefix.
- Turn 2: sends `[SYS][USER1][ASS1][USER2+suffix]`. `USER1` at position 1 no longer has the suffix (it moved to `USER2`). Ollama's prefix match breaks right after `SYS` and re-prefills `USER1+ASS1+USER2` from scratch — 30-70 s of wasted prefill on every re-question at qwen3.6:35b / num_ctx=256000 on M3 Ultra.

**Fix:** removed `_NO_THINK_USER_SUFFIX`, `_is_qwen3_model`, and the `inject_qwen3_suffix` parameter entirely. `_apply_no_think` now only injects the system-prompt hint (idempotent across turns → prefix-cache safe). For Ollama, `body["think"] = False` is the authoritative switch and works for ANY thinking model Ollama serves (qwen3, deepseek-r1, gemma3-think, future families) — no per-model detection needed. For LM Studio, Daniel configures no-thinking in the LM Studio GUI directly; CBC sends nothing extra on that path.

Diagnostic log fields simplified accordingly (removed `qwen3_detected` and `qwen3_suffix_applied`).

Session_store schema unchanged — user messages have always been stored raw, so no migration.

Files across all four: `admin/src/sections/LLMSection.tsx`, `admin/src/i18n.ts`, `admin/src/api.ts`, `backend/services/llm_provider.py`, `backend/services/polling.py`, `backend/main.py`.

Expected effect after the follow-up re-pull:

- Re-question TTFT back to single digits (~10 s), matching pre-Sprint-13 performance.
- First-question TTFT unchanged (dominated by cold-load + full-prompt prefill — separate optimisation via preload.conf if/when Daniel wants).
- Universal coverage: any Ollama thinking model is suppressed by OFF; no per-model allowlist.
- Parallel chat turns actually parallel (no tick-level blocking).
- Backend completing + user seeing generic error should be rare or gone (terminal events retry on failure).

---

## Sprint 14 — Parallel polling + concurrency control (2026-04-24)

Direct follow-up to Sprint 13. Real parallelism in the backend polling loop, capped by an admin-configurable ceiling, with the Sprint 13 cancel watcher restructured to work under parallel turns. See `docs/architecture/decisions.md` ADR-008 for full rationale.

### What changed architecturally

- **Polling is no longer serial.** `_tick` now runs every enabled frontend in parallel via `asyncio.gather`; within each frontend, queued messages are processed in parallel too. Recovery / auth / document / upload handlers remain sequential per frontend — cheap, and parallelism matters for LLM work, not for disk I/O.
- **Global turn semaphore.** `polling._turn_semaphore` caps concurrent `_process_turn` executions backend-wide. Sized from the new `LLMConfig.max_concurrent_turns` field; re-created when the admin changes the value (tasks already holding the old semaphore drain naturally; new tasks acquire the new one).
- **Backend-level cancel watcher.** Sprint 13's per-turn `_watch_cancel` would race under parallel turns (first watcher to drain `/internal/cancellations` clears the set; sibling watchers see empty; cancels get lost). Replaced with a single `cancel_watcher_loop` sibling of `polling_loop` started from `main.py` lifespan. Populates module-level `_pending_cancellations: set[str]`; `_process_turn` reads the shared set via `cancel_check` and discards its token on completion.

### New admin control

Dropdown "Max concurrent turns (backend-wide)" in `LLMSection`, options **1 / 2 / 4 / 6**, default **4**. Warning text: "Must match OLLAMA_NUM_PARALLEL and LM Studio Parallel for aligned behaviour; excess turns otherwise queue inside the runtime without visible indicator." Global-only (same inheritance as `disable_thinking`, compression, routing).

### Ops changes (local Mac Studio only, not in the commit)

- `~/Library/LaunchAgents/com.ollama.server.plist`: `OLLAMA_NUM_PARALLEL` raised 2 → 4 (full bootout + bootstrap reload).
- `Ollama_UNI_Tools_Config.md`: histórico entry recording the change + memory implication (each slot reserves its own full `num_ctx`, so NP=4 costs ~4× the KV cache of NP=1 for the same loaded model).

### Concurrency audit (done at implementation time)

- `session_store` — disk + cache, per-session, safe for concurrent use across different sessions. Same session can't have two in-flight turns (UI locks input while streaming).
- `_fail_state` (circuit breaker in `llm_provider`) — GIL-atomic dict ops; benign miscounts possible under contention, accepted.
- `httpx.AsyncClient` — built for concurrent use across tasks.
- `_pending_cancellations` set — GIL-atomic add/discard/`in`; safe without explicit lock.

### Files touched

Backend:
- `CBCopilot/src/backend/services/polling.py` — `_pending_cancellations`, `_turn_semaphore` + `_ensure_turn_semaphore`, `_process_frontend`, `_process_message_safe` with semaphore gate, `cancel_watcher_loop`, `_tick` rewritten to gather over frontends, per-turn cancel logic replaced with shared-set read.
- `CBCopilot/src/backend/services/llm_config_store.py` — `max_concurrent_turns: Literal[1, 2, 4, 6] = 4` on `LLMConfig`.
- `CBCopilot/src/backend/main.py` — imports and starts `cancel_watcher_loop` alongside `polling_loop` in lifespan; cancels on shutdown.

Admin:
- `CBCopilot/src/admin/src/api.ts` — `max_concurrent_turns` on the `LLMConfig` interface.
- `CBCopilot/src/admin/src/i18n.ts` — `llm_max_concurrent_turns` + `llm_max_concurrent_turns_description` (EN + ES).
- `CBCopilot/src/admin/src/sections/LLMSection.tsx` — dropdown below the disable-thinking toggle.

Docs:
- `docs/architecture/decisions.md` — ADR-008.
- `docs/STATUS.md` + `docs/CHANGELOG.md` + `Ollama_UNI_Tools_Config.md` (ops log).
- `HRDD_Sprint14_port_prompt.md` (repo root, new) — handoff prompt for Claude-in-HRDD to replicate.

### Verification

- `python3 -m py_compile` clean on all modified backend files.
- `OLLAMA_NUM_PARALLEL=4` confirmed live (`ps eww` on `ollama serve`).
- Admin SPA + frontend SPA build via Portainer's re-pull on Daniel's side (deliberately not run locally per sprint-13 lessons-learned).

### Live-test checklist (Daniel's QA after re-pull)

1. Two users on same frontend send simultaneously → both start streaming in ~1 s (not 20+).
2. Five users → first four stream in parallel; fifth shows "en cola — 1 ahead".
3. Admin dropdown from 4 to 2 → next pair obeys new cap immediately (no restart).
4. Stop button on one of the parallel streams → only that one cancels.
5. Session-close summary triggers while another user's inference is mid-stream → both run in parallel.

### Known follow-ups (deferred)

- Per-frontend `max_concurrent_turns` override.
- Queue-inside-runtime indicator for when CBC cap > runtime cap.
- HRDD port: run `HRDD_Sprint14_port_prompt.md` in a Claude-in-HRDD session when Daniel is ready.

---

## Sprint 13 — Chat resilience & UX control (2026-04-24)

Three independent features that together let CBC users (and admins) recover gracefully from a wedged or slow LLM backend, plus a global toggle to suppress reasoning-mode output. Triggered by a real production crash where `qwen3.6-35b-a3b` running under LM Studio threw a Jinja-template error that left the chat UI permanently in "thinking" with no way out short of killing the chat.

### Feature 1 — "Esperando turno" indicator
- Sidecar: `GET /internal/queue/position/{session_token}` returns the position of the user's oldest pending chat message in the per-frontend queue. -1 = not in queue (already being processed or never enqueued).
- ChatShell: polls the new endpoint every 2 s while `isStreaming && !streamingText` (i.e. waiting for the first token); replaces the generic "Thinking…" bubble with `Waiting in queue — N ahead of you` when position > 0, or `Waiting for an available slot` at position 0. Drops the indicator on first token or stream end.
- Only fires when there's actual contention (multiple users on the same frontend send near-simultaneously).

### Feature 2 — Universal "disable reasoning / think" toggle
- New `disable_thinking: bool = True` field on `LLMConfig` (sibling of `compression` / `routing`, global only — same inheritance semantics as those). Defaults ON because qwen3 reasoning prelude is the single biggest hit on first-token latency in CBC's measurement.
- `llm_provider._build_body` now injects three nudges when the flag is on:
  - `"think": false` at the top level of the request body (Ollama-native, ignored by other providers).
  - ` /no_think` suffix on the last user message (qwen3 convention; Ollama and LM Studio both honour it via the model's chat template).
  - System-prompt hint `Respond directly. Do not output <think>...` injected into the existing system message (or prepended if none).
- New `_ThinkStripper` state machine post-processes the streamed tokens, dropping `<think>...</think>` blocks before they reach the SSE channel. Tag-split-across-chunks safe (verified with 9-test suite that includes char-by-char streaming).
- Admin UI: new checkbox "Disable reasoning / think mode" between the slot grid and the context-compression block in `LLMSection`. EN + ES translations wired (other 13 languages fall back to EN per Sprint 12 Phase B's pattern; Phase B's pending translator pass will pick them up).
- For models without a thinking mode (gemma, llama, mistral) every layer is a no-op.

### Feature 3 — Stop button + inactivity timeout + defensive UI reset
Three layers against the wedged-backend scenario:
- **Backend per-chunk inactivity timeout (60 s, `INACTIVITY_TIMEOUT`).** `stream_chat_one_slot` now wraps `aiter_lines()` with `asyncio.wait_for`. The connection-level `STREAM_TIMEOUT=300s` resets on every chunk and never fired in the qwen3.6 case; this new budget kills genuinely stalled streams in 60 s and lets the slot fallback chain try the next provider.
- **Cooperative cancel via per-turn watcher.** Sidecar accepts `POST /internal/chat/cancel/{session_token}` (sets a flag with TTL). `_process_turn` spawns a 1-s-tick `_watch_cancel` background task that polls the new `GET /internal/cancellations` endpoint (deliberately separate from `/internal/queue` so it can fire mid-stream instead of waiting for the next 2-s main poll). When the watcher sees this session in the drained set, it flips the local flag; `stream_chat_one_slot` checks it between chunks and raises `CancelledError`. Backend then emits a new `cancelled` SSE event and persists the partial assistant message so the conversation log keeps what the user already saw.
- **ChatShell Stop button.** Visible only during `isStreaming`, sits next to Send. Click = optimistic UI close (append `(cancelled)` to the partial reply, unlock input, close EventSource) + background `POST /internal/chat/cancel/{token}`. New `cancelled` SSE listener mirrors the cleanup so server-side cancels look the same to the user. Defensive `setQueuePosition(null)` + `setStopRequested(false)` reset added to every terminal-state handler (`done`, `error`, `cancelled`, `onerror` after 3 strikes) so the UI cannot get stuck on `isStreaming=true` forever even if the SSE connection dies dirty.

### Files touched

Backend:
- `CBCopilot/src/backend/services/llm_config_store.py` — `disable_thinking: bool = True` on `LLMConfig`.
- `CBCopilot/src/backend/services/llm_provider.py` — `INACTIVITY_TIMEOUT = 60.0`, `_apply_no_think`, `_ThinkStripper`, `cancel_check` plumbing through `stream_chat` and `stream_chat_one_slot`, `_build_body` reshaped for `disable_thinking`.
- `CBCopilot/src/backend/services/polling.py` — `CANCEL_POLL_INTERVAL = 1.0`, per-turn `_watch_cancel` task, `cancelled` SSE emission with partial-message persistence.

Sidecar:
- `CBCopilot/src/frontend/sidecar/main.py` — `_cancellations` dict + lock, `POST /internal/chat/cancel/{token}`, `GET /internal/cancellations`, `GET /internal/queue/position/{token}`, `cancelled` added to terminal-event set in `push_stream_chunk` + SSE generator.

Admin:
- `CBCopilot/src/admin/src/api.ts` — `disable_thinking: boolean` on `LLMConfig` interface.
- `CBCopilot/src/admin/src/i18n.ts` — `llm_disable_thinking` + `llm_disable_thinking_description` keys (EN + ES; rest fall back to EN).
- `CBCopilot/src/admin/src/sections/LLMSection.tsx` — checkbox between slot grid and compression block.

Frontend:
- `CBCopilot/src/frontend/src/i18n.ts` — `chat_stop`, `chat_cancelled_suffix`, `chat_queued`, `chat_queued_alone` (EN + ES; rest fall back to EN).
- `CBCopilot/src/frontend/src/components/ChatShell.tsx` — `queuePosition` + `stopRequested` state, queue-position polling effect, `stopStream` handler, Stop button next to Send (visible during streaming only), `cancelled` SSE listener, defensive resets in every terminal handler, queue indicator wired into the activity bubble.

### Verification

- `python3 -m py_compile` clean on all four modified backend files.
- 9-case unit suite for `_ThinkStripper` — single-chunk, multi-block, char-by-char split-tag, no-close-tag, edge cases.
- Backend Docker image builds clean (validates the admin SPA TypeScript build that bundles `LLMSection.tsx` + `api.ts`).
- Frontend Docker image builds clean (validates `ChatShell.tsx` + `i18n.ts`).

### Known follow-ups (deliberately deferred)

- LM Studio worker-zombie recovery (admin "Eject model" button calling `lms unload`) — separate sprint.
- Per-frontend `disable_thinking` override — currently global only; matches the inheritance pattern of `compression` / `routing`. Add to `LLMOverride` if a deployment ever needs it different per frontend.
- `num_ctx`-consistent loading per model in `llm_provider` to avoid Ollama reload thrashing — flagged during the Ollama-tuning conversation that triggered this sprint, captured for next time.

---

## Sprint 12 Phase B — Admin i18n wiring pass 1 (2026-04-21)

Continuation of Phase A. Replaced hardcoded English in the sections/panels that
had keys but weren't consuming them, and added ~200 new keys for the rest.
i18n-translator subagent handled translation; splice helper spliced results
back into the 14 non-EN dicts. Everything compiles (`tsc --noEmit` clean) and
falls back to EN for any slot a translator hasn't landed yet.

### Wired (consuming `t()` throughout)

- `sections/GlossarySection.tsx` — heading, count, download/upload, table
  headers, description, all error + success toasts.
- `sections/OrgsSection.tsx` — same shape as Glossary (heading, description,
  table headers, upload validation errors, success counter).
- `sections/GuardrailsSection.tsx` — description + explanation, threshold
  captions, pattern-count labels (singular/plural), user-trigger headings.
- `sections/LLMSection.tsx` — heading, provider description, slot-order
  labels + hints, compression block, summary-routing block, Save / Check
  health / Refresh providers buttons, loading state.
- `sections/SMTPSection.tsx` — everything: host/port/user/pass labels,
  description, STARTTLS toggle, admin-emails section, notification toggles,
  per-frontend override block, confirm dialogs, test-email button.
- `panels/CompanyManagementPanel.tsx` — companies heading, description,
  add button, display-name field, Compare-All badge, enabled toggle,
  show/hide content, delete, country-tags hint, empty-state message,
  added toast, remove confirm.
- `panels/PerFrontendLLMPanel.tsx` — override heading, inheriting-global
  badge, slot-count badge (singular/plural), description, Override
  checkbox label, Save / Refresh buttons, slot labels from shared pool.
- `panels/PerFrontendOrgsPanel.tsx` — override heading, inheriting badge,
  description, mode dropdown + values, preview block, explain texts per
  mode, download/upload buttons, upload-hint, show-count toggle, removal
  confirm + result, upload errors + success.
- `components/TranslationBundleControls.tsx` — heading, coverage counters
  (disclaimer / instructions with filled/total placeholders), source-lang
  label, Download / Upload / Auto-translate button labels incl. busy
  states, upload validation errors, tooltip for Auto-translate, help text.
- `FrontendsTab.tsx` — registered heading, register button, register
  helper text + form fields + placeholders, empty-state, per-row last-seen
  label, enabled toggle, Unregister button + confirm, registered-info
  toast.
- `SessionsTab.tsx` — title, filter pills, empty state, per-group session
  count (singular/plural), all 9 table columns, row-inline destroy
  button, flag-star titles, Compare-All cell label, em-dash fallback.
  Detail drawer: summary heading + Copy label + Copied state, Flag /
  Unflag / Destroy buttons, Survey section + all 14 `dt` labels
  (Frontend / Language / Country / Region / Name / anonymous / Email /
  none / Organisation / Position / Created / Last activity / Completed /
  Violations), initial-query label, uploads heading with count +
  download / copy-text buttons + feedback states, conversation heading.
  `timeAgo(iso, lang)` now localises via `tAdmin`.

### Not wired this pass (deferred to a later pass)

- `sections/RAGSection.tsx` + `sections/PromptsSection.tsx` — large
  surfaces with inline text that's densely coupled to resolution logic;
  deferred so this pass could land cleanly.
- `RegisteredUsersTab.tsx` — XLSX import / export, chip inputs, per-frontend
  list switcher, still on English.
- Minor leftovers: prompt-body editor strings (intentionally stay EN —
  prompt bodies are operator-authored content, not UI chrome).

### New translation keys + bundles

- Added ~200 keys to `AdminTranslationKeys` across three batches:
  Batch 1 — Glossary / Orgs / Guardrails / LLM / SMTP section bodies (90 keys).
  Batch 2 — Frontends tab body + Translation-bundle controls + Company /
  LLM / Orgs panels (59 keys).
  Batch 3 — Sessions tab body + detail drawer (49 keys).
- Delegated Batch 1 + Batch 2 to the i18n-translator subagent running in
  parallel (run-in-background). Splice helper read each subagent's
  transcript and inserted the 14 language fragments into the non-EN
  dicts (EN is hand-authored). `tsc --noEmit` clean throughout.
- Batch 3 (Sessions) — translator launched; splice will run when it
  lands. EN values are in place so the UI renders correctly in every
  language today via the built-in EN fallback.

### Fallback behaviour (no UI regression when a key is untranslated)

`AdminTranslations = Partial<Record<…>>` + the existing lookup
`DICTIONARIES[lang]?.[key] ?? EN[key] ?? key` means any key we add to EN
works in every language immediately; the translator pass just upgrades
the non-EN rendering from "EN fallback" to "native text". No runtime
errors, no missing-key crashes.

### Validation

- `cd CBCopilot/src/admin && npx tsc --noEmit` — exit 0 after every wiring batch.
- Manual smoke deferred — UI boot + language switch in the browser
  stays a Daniel check (iCloud + Portainer flow).

---

## Sprint 12 Phase A — Admin i18n + branded header (2026-04-21)

Transferring CBC to UNI affiliates means the admin is the first surface a
local operator opens — and imposing English on that surface is both a
friction wall and a cultural signal we don't want to send. This sprint
lays the admin-i18n foundation and delivers the chrome + the frequently
touched panels in 15 languages. Rest of the admin sections keep their
English labels for now (Phase B follow-up).

### Languages (15, G&P affiliate coverage)

EN, ES, DE, FR, IT, PT, NL, PL, HR, SV, AR, JA, TH, ID, TR. Picked for
G&P — KO dropped (no affiliates), ID added (Indonesia), TR added. RTL
for AR only.

### Branded header (HRDD parity)

New `Dashboard` layout copies HRDD's admin header style:
- `bg-uni-dark` (#1a1a2e) band with title + subtitle + language selector
  + logout on the top row.
- White tab strip beneath with `shadow-sm` to separate navigation from
  main content.
- `max-w-6xl mx-auto` for the main container so sections don't stretch
  edge-to-edge on wide screens.

`LoginPage` + `SetupPage` get the same dark-chip language selector so an
operator whose only shared language isn't English can switch before they
authenticate.

### i18n infrastructure (`src/admin/src/i18n.ts`)

- `AdminLangCode` union (15 langs), `ADMIN_LANGUAGES` metadata list,
  `ADMIN_RTL_LANGS = ['ar']`.
- `AdminTranslationKeys` union covering ~140 keys: header / tabs /
  login / setup / generic verbs (Save/Cancel/…) / section titles /
  branding defaults + translation controls / session settings fields /
  RAG docs + pipeline / sessions tab columns + filters / users
  (contacts) / cross-cutting confirms.
- EN source bundle + 14 translated dictionaries populated by the
  i18n-translator subagent in three parallel batches
  (ES/DE/FR/IT/PT → NL/PL/HR/SV/TR → AR/JA/TH/ID). Quality flagged as
  MVP pending native-speaker review before each affiliate handover.
- `AdminLangContext` provider lifted to `App.tsx` so login + setup
  share the same picker + `localStorage`-backed choice as the
  dashboard. `document.documentElement.{lang,dir}` sync'd on every
  change.
- `tAdmin(key, lang, vars)` supports `{placeholder}` interpolation for
  strings like `rag_pipeline_reindexed` ("Reindexed {count} scopes.").
  `useT()` hook returns `{ lang, t }` for the common component pattern.
- `loadStoredAdminLang` + `persistAdminLang` helpers for the
  localStorage + navigator-fallback flow.

### Wired this phase

- `App.tsx` — provider at the root + html lang/dir effect.
- `Dashboard.tsx` — full rewrite with new header + tabs, everything
  translated.
- `LoginPage.tsx` + `SetupPage.tsx` — dark-chip selector + all copy i18n'd.
- `AdminLanguageSelector.tsx` — new native-select picker.
- `panels/SessionSettingsPanel.tsx` — all fields, confirms, buttons, help
  text (including the Phase B CBA citations explainer). Numbers-only
  fields dropped their per-field help prose in favour of bundled labels
  so the translator didn't have to render long sentences three times per
  language.

### Not wired yet (Phase B follow-up)

BrandingSection + BrandingPanel, RAGSection + RAGPipelineSection,
PromptsSection, LLMSection, SMTPSection, GuardrailsSection, GlossarySection,
OrgsSection, SessionsTab detail drawer, RegisteredUsersTab body, FrontendsTab
body, all modal dialogs inside those. The keys exist in the bundle — each
component just needs a `const { t } = useT()` and literal replacements.

### Known limits

- Quality: translations are Claude-generated. Fine as MVP, but the admin
  is specifically a first-contact surface for affiliates — each language
  should get a native-speaker review before real handover.
- RTL: layout not yet audited for AR. The wrap (`<html dir="rtl">`)
  works; individual flex rows with absolute chevrons / action-button
  clusters may need manual checks. Queued for Phase B.
- No format localisation (dates/numbers) — intentional. dd/mm/yyyy or
  ISO is universal enough for the countries covered.

## Sprint 11 Phase B — Inline citations with page / article references (2026-04-21)

Phase A answered "which CBAs did the model draw on". Phase B answers
"where inside each document". Gated end-to-end by the
`cba_citations_enabled` session-setting flag (off by default, requires
`cba_sidepanel_enabled` on). Flag off → pipeline identical to Phase A.

### Chunk metadata

- `rag_service.Chunk` gains `page_label: str = ""` — populated from
  LlamaIndex's PDFReader metadata (preserved through `SentenceSplitter`
  and into Chroma).
- New `_citation_label_for(chunk)` helper in `prompt_assembler`:
  PDF page → multilingual article regex (`Art(?:ículo|icle|igo|icolo)?.?\s+N`
  covering ES / EN / PT / FR / IT) → annex regex (`Anexo / Annex / Allegato N`)
  → empty string. Used both at prompt-render time and when building the
  `sources` SSE payload.

### Prompt (gated by flag)

- `_render_chunks` now accepts `cite_inline`. When True it appends each
  chunk's locator to its heading (`### Source: foo.md (tier=company, p. 12)`)
  and tails a "Citation format" instruction block: the LLM must append
  `[filename, locator]` brackets immediately after the relevant sentence;
  no locator → just `[filename]`; do not invent locators.
- `polling._process_turn` reads the per-frontend setting, computes
  `cite_inline = cba_citations_enabled AND cba_sidepanel_enabled`, and
  passes it into `prompt_assembler.assemble(..., cite_inline=...)`.

### SSE / sources enrichment

- New `_chunk_citation_labels` aggregator in `prompt_assembler`. When
  Phase B is on, each `sources` entry gains a `labels: ["p. 14", "Art. 12"]`
  array listing every distinct locator hint shown to the LLM for that
  source. Off → entries stay as-is.
- `AssembledPrompt.sources` type widened from `list[dict[str, str]]` to
  `list[dict[str, Any]]`.
- TypeScript `CitationSource` interface gains `labels?: string[]`.

### React — citation chips + panel cross-link

- `injectCitationLinks(text)` regex-rewrites `[filename, locator]`
  occurrences into markdown links with a `#cite:` pseudo-scheme before
  the text hits ReactMarkdown. Fenced code blocks are skipped so code
  samples aren't chewed up.
- New `buildMarkdownComponents(onCitationClick)` in `ChatShell`: the `a`
  component intercepts `#cite:` hrefs and renders them as inline pills
  (`bg-uni-blue/10`). Regular links fall through to `target="_blank"`.
- `ChatShell.openCitation(filename)` opens the panel and bumps a
  `highlightedCitation` state (with a null-then-set cycle so identical
  repeat clicks still fire the effect).
- `CitationsPanel` accepts `highlightedFilename`, scrolls that entry
  into view and pulses it with a 1.6 s blue background animation. Also
  renders the `labels[]` chips ("p. 14", "Art. 12") under each entry so
  the user sees the locator coverage at a glance.

### Testing / known limits

- LLMs will occasionally forget the citation format or hallucinate a
  page number. Panel remains the ground truth; if this happens at rate,
  tighten the Citation format instruction.
- Article regex covers ES / EN / PT / FR / IT. Other languages fall
  back to no inline locator but still appear in the panel.
- Page metadata depends on LlamaIndex's PDF reader. When absent the
  article / annex regex takes over, so missing page labels aren't a
  hard failure.

### Deferred (not this sprint)

- Open PDF at the cited page — requires a viewer component.
- Composite citations ("see Arts. 12 and 14 of …").
- Locator patterns for non-Latin-script languages.

## Sprint 11 Phase A — CBA sidepanel + cascade reindex + polish (2026-04-21)

Phase A of the "CBA sidepanel" feature Daniel scoped right after Sprint 10
settled. Delivers the panel + downloads; Phase B (page / article citations
inline in responses) is intentionally deferred but the feature flag is
plumbed end-to-end so enabling it in the next sprint won't require config
schema changes.

### CBA sidepanel with citations + downloads

- **Toggle** `cba_sidepanel_enabled` on `SessionSettings` (per-frontend, default
  on). Disables the entire feature — no backend SSE events, no React panel,
  no button — when an operator doesn't want it.
- **Citation capture** in `prompt_assembler.assemble` — returns a new `sources`
  field with deduped `{scope_key, filename, tier}` for the chunks that
  actually made it into the prompt.
- **SSE event** `sources`: `polling._process_turn` emits it right before `done`
  with the JSON-encoded list. Sidecar relays unchanged (the SSE channel was
  already generic).
- **CitationsPanel** (`src/frontend/src/components/CitationsPanel.tsx`) — new
  component. Slide-over from the right on every viewport (320 px on mobile,
  384 px on desktop); semi-transparent backdrop, Escape + tap dismiss. List
  grows across the whole session deduped by (scope, filename). Per-entry
  download button runs the pull-inverse poll loop and triggers a browser
  download when the blob arrives. Tier badge (Global / Frontend / Company)
  helps the user place the source.
- **ChatShell integration** — listens for the `sources` SSE event, accumulates
  state, shows a "Documents" button with a count badge next to End session.
  Panel opens by default on `md+`, closed on mobile so the chat starts clean.

### Pull-inverse file downloads

- New sidecar endpoints: `POST /internal/document-request` queues a
  `{scope_key, filename}` and returns a request_id. `GET /internal/document/{id}`
  returns JSON `{status: "pending"}` until the bytes land, then streams the
  file. `POST /internal/document/{id}/result` is the backend push target;
  `POST .../error` surfaces fetch failures.
- `polling._handle_document_request` reads files from the matching
  `documents/` dir with path-traversal guards (only admin-curated content in
  the resolved scope is reachable; filename is treated as a bare basename).
- `document_requests` surfaced in `/internal/queue` alongside the other
  pull-inverse queues (recovery / auth / uploads). Sidecar still makes zero
  outbound HTTP.

### Phase B scaffolding (no behaviour yet)

- `cba_citations_enabled` on `SessionSettings` (default off). Plumbed through
  to `DeploymentConfig` and the admin UI as a dependent toggle that greys out
  when the parent sidepanel flag is off. Phase B (LLM instructed to emit
  `[filename, p. N]` / `[filename, Art. N]` references inline) will consume
  the flag in a follow-up sprint.

### Mobile table overflow

- `ChatShell`'s `Bubble` component now renders markdown through custom
  `components` that wrap `<table>` in an `overflow-x-auto` container and let
  `<pre>` scroll horizontally — tables in responses stay inside the 85%
  bubble width on mobile with a horizontal swipe instead of bleeding out.
- `min-w-0` added to the bubble flex child so it can shrink below intrinsic
  content width. Fix applies to assistant bubbles + summary bubble.

### Cascade reindex (admin UX)

- New backend helpers `reindex_frontend_cascade(fid)` + admin endpoints
  `/admin/api/v1/rag/reindex-all` + `/admin/api/v1/rag/reindex-frontend-cascade/{fid}`.
- Admin `RAGSection` gets a tier-aware second button next to the existing
  per-scope "Reindex":
  - Global tier → "Reindex everything" (confirm, then global + every
    frontend + every company).
  - Frontend tier → "Reindex frontend + companies" (confirm, global
    untouched).
  - Company tier → unchanged.

### Polish

- Admin RAG cascade-reindex confirm prompts + `RAGPipelineSection` (CR
  toggle UI) translated to English to match the rest of the admin panel.
  No logic change.

### Phase B backlog (for the next sprint)

- PDFReader metadata preservation (`page_label` in node metadata).
- Prompt change to make the LLM emit structured citations.
- Regex fallback to article number in the chunk text when no page is
  available (OCRed legacy CBAs).
- Panel cross-links: clicking a citation in the response jumps to that
  document in the panel.

## Sprint 10 — UX polish + pure pull-inverse + ChromaDB (2026-04-21)

Three focused upgrades shipped together off the back of the first real
deployment. All three were "blocking" in different ways: the chat UX made
the system feel broken, the auth relay was the last violation of the
pull-inverse contract that scoping CBC across two hosts depends on, and
the vector store choice was the next scaling cliff.

### A — Chat UX (port from HRDD)

- `ChatShell.tsx`: scroll guard via a `userScrolledUp` ref + `window` scroll
  listener. Auto-scroll fires only when the user is at the bottom; the
  moment they scroll up to read past content the shell stops yanking them
  down on every streamed token. Sending a new message resets the flag so
  they get pulled back to see the response.
- New activity bubble — pulsing blue dot + i18n `chat_thinking` label,
  shown when `isStreaming` and no token has arrived yet. Replaces the
  ambiguous grey-text "Thinking…". Same look HRDD has had since Sprint 6.

### B — Pull-inverse auth (last sidecar→backend call eliminated)

The auth relay (`request-code` / `verify-code`) was the only outbound HTTP
left in the sidecar. Refactored to the same queue + push-back pattern as
recovery and uploads:

- Backend `api/v1/auth.py`: extracted reusable `process_request_code` and
  `process_verify_code` from the HTTP endpoints. The endpoints stay as a
  thin wrapper for direct admin-shell debugging; the sidecar no longer
  calls them.
- Sidecar `main.py`: `POST /internal/auth/request-code` and `verify-code`
  now queue an `auth_request` in `/internal/queue`, returning immediately
  (`pending` / `verifying`). New `GET /internal/auth/status/{token}` for
  React polling. New `POST /internal/auth/{token}/result` for the
  backend's push-back. State machine: `none → pending|verifying →
  code_sent|verified|invalid_code|not_authorized|smtp_error|...`.
- Backend `polling.py`: new `_handle_auth_request` walks the drained
  `auth_requests` list, resolves via the new internal API, POSTs the
  result back to the sidecar.
- React `AuthPage.tsx`: replaces the blocking POST with a POST + 400 ms
  poll loop (20 s deadline) over the new `/status` endpoint.
- Sidecar: `import httpx` removed. `_backend_call` removed. The CBC
  frontend container now makes ZERO outbound HTTP calls. `CBC_BACKEND_URL`
  env var dropped from `docker-compose.frontend.yml`.

### C — ChromaDB migration (single collection, scope as metadata)

`SimpleVectorStore` had taken us as far as it could; it's brute-force
cosine search with one persisted JSON dir per scope. Swapped for an
embedded ChromaDB collection — HNSW-backed, native metadata filtering,
one persistent client + one collection at `/app/data/chroma/`.

- One collection (`cbc_chunks`) holds every chunk for every scope. Each
  node carries `scope_key` in metadata. Query-time `MetadataFilters`
  (`ExactMatchFilter(key="scope_key", value=...)`) keeps tier semantics
  — global / frontend / company queries stay isolated.
- BM25 retrieval now reads scope-filtered nodes back from Chroma via
  `collection.get(where={"scope_key": ...})` so the lexical channel
  stays scope-aware too.
- Dependencies: `chromadb>=0.5,<2.0`,
  `llama-index-vector-stores-chroma>=0.4`. Backend image grows ~150 MB
  for the chromadb stack (sqlite-backed, no separate server). Verified
  build clean locally.
- Migration: existing per-scope `rag_index/` JSON dirs are swept on the
  next reindex of each scope; old chunks ignored. First query against
  any scope after upgrade triggers a rebuild into Chroma. Admins who
  want it instant can run Reindex per scope or use the global "reindex
  all scopes" path.
- All Sprint 9 retrieval features (markdown chunker, BGE-M3, hybrid
  BM25+dense, cross-encoder rerank, optional Contextual Retrieval) ride
  on top unchanged.

### Operations

- Frontend stack no longer needs `CBC_BACKEND_URL`. Drop it from any
  Portainer stack envs you set when first wiring cross-host.
- Backend redeploy + per-scope reindex required (chunk vectors moved
  from `*.json` to Chroma collection). Same drill as Sprint 9.
- `INSTALL.md` notes about `CBC_BACKEND_URL` are now stale; will refresh
  in the next docs pass.

## Sprint 9 — RAG overhaul + HRDD-parity architecture hardening (2026-04-21)

Triggered by the first real deployment across two Docker hosts (backend on Mac Studio, frontends on Mac M4 over Tailscale) + an RAG stress test against the Amcor-Lezo CBA. Two distinct workstreams landed together because both were blocking real use.

### Architecture — restore HRDD's pull-inverse model

- **Compose files cleaned of `cbc-net`.** Both stacks now run on Docker's default bridge network. Backend and frontend live on different Docker hosts by design — a shared Docker network was conceptually wrong (networks don't span hosts). Backend polls registered frontend URLs over LAN / Tailscale / Bonjour, same as HRDD Helper. `container_name:` removed so Portainer stack-name prefixing lets multiple frontend stacks coexist on one host.
- **`CBC_BACKEND_URL`** exposed on the frontend compose as an optional env var for the one remaining sidecar→backend relay (auth). Empty default means same-host deployments keep working with service-name DNS over the implicit bridge; cross-host points it at the Tailscale / hostname of the backend.
- **Three pull-inverse refactors** that had drifted in Sprints 7/7.5:
  - **Guardrails thresholds**: backend pushes per poll cycle (`POST /internal/guardrails/thresholds`); sidecar caches to disk; ChatShell reads via `GET` with 2/5 fallback. No more sidecar→backend proxy call.
  - **Session recovery**: React `POST /internal/session/recover` queues a `recovery_request` token in `/internal/queue`. Backend polling loop drains, resolves against `session_store` (including the 410-past-window check), and `POST`s the result to `/internal/session/{token}/recovery-data`. SessionPage now polls every 400 ms with a 15 s deadline (`pending | found | not_found | expired`).
  - **Uploads**: React `POST /internal/upload/{token}` stores file to a sidecar tempdir + queues a notification in `/internal/uploads`. Backend polls, `GET`s each file, `session_rag.ingest_upload` into the session index, `DELETE`s the sidecar copy. SMTP admin-upload alert moved into the ingest path. Zero network magic between backend and frontend beyond polling.
- **Company list pull-inverse.** `company_registry` (backend) holds only admin-registered real companies. Backend polling pushes the list per poll (`_push_companies_if_needed`); admin CRUD invalidates via `polling.invalidate_companies_pushed(fid)`. Sidecar's `GET /internal/companies` serves the pushed cache, falling back to the image-shipped stub for first-boot only.
- **Compare All is a frontend concept, not a registered company.** The sidecar synthesises a fixed `_COMPARE_ALL_ENTRY` at list time and prepends it; drops any stray `is_compare_all` entries from the pushed list defensively. The routing (own `compare_all.md` prompt, combined RAG from every enabled company + frontend RAG + global RAG) was already correct in `resolvers.py`; this just separates the UI button from the company registry.
- **CompanySelectPage branded buttons.** All buttons use the primary colour; Compare All gets a ring accent + subtitle so it stands out as the cross-company option while the rest of the list stays visually consistent with the app's primary actions.
- **`docs/INSTALL.md`** rewritten to lead with pull-inverse architecture, document Portainer Repository + Web-editor modes, explain cross-host deployment with `CBC_BACKEND_URL`, and drop the old "create cbc-net on each host" step entirely.

### RAG overhaul

Retrieval stack rebuilt after the Amcor-Lezo CBA exposed that the system couldn't surface Annex I's salary tables (lines 1296-1335 of the source Markdown) even when asked to cite them literally.

- **Markdown-aware chunker + bigger chunks.** `_parse_nodes` routes `.md` through `MarkdownNodeParser` (keeps each header section contiguous — "ANEXO I" travels with its table rows); `.pdf` / `.txt` through `SentenceSplitter`. `CHUNK_SIZE` 512 → 1024, `CHUNK_OVERLAP` 50 → 100, `DEFAULT_TOP_K` 5 → 8. Hybrid retrieval via `QueryFusionRetriever` (reciprocal-rank fusion over vector + BM25), falls back to vector-only if BM25 isn't available.
- **Embedder swap**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, English-primary, 22M) → `BAAI/bge-m3` (1024-dim, 100+ languages natively, 568M). Single biggest quality lever for a multilingual CBA corpus (Spanish, Basque, French, Portuguese, Italian, etc.). Admin-configurable via `rag_embedding_model` in `deployment_backend.json`.
- **Cross-encoder reranker.** New post-processor stage after hybrid retrieval: fetch `rag_reranker_fetch_k=30` candidates, rerank with `BAAI/bge-reranker-v2-m3` (~568M params, multilingual) down to `rag_reranker_top_n=8` via `SentenceTransformerRerank`. Meaningful precision lift for queries where the first pass surfaces near-miss chunks. Admin-toggleable via `rag_reranker_enabled`.
- **Anthropic Contextual Retrieval toggle** (default off). `_contextualise_nodes` prepends an LLM-generated 1-2 sentence context line to each chunk at index time so embeddings carry document-level grounding. Uses the summariser slot through `llm_provider.chat`. Runtime toggle via `POST /admin/api/v1/rag/settings/contextual` that reindexes every scope in one shot (rolls the toggle back on failure). Off by default because the per-chunk LLM cost makes full reindex take minutes-to-hours on real corpora — with the markdown chunker + BGE-M3 + reranker already landed, CR is a reserved lever for when recall measurably lags.
- **Admin UI: new `RAGPipelineSection`** on the General tab. Shows embedder / reranker / chunk size as read-only info and exposes the Contextual Retrieval toggle with a clear warning that flipping it triggers a full corpus reindex.
- **Dockerfile.backend** pre-downloads BGE-M3 (~2.2 GB) + bge-reranker-v2-m3 (~568 MB) alongside MiniLM as a fallback. Image grows ~3 GB; first-query cold start stays instant and the container works air-gapped.

### Build fixes (Portainer hid the error behind Business-tier logs)

Reproduced the build locally to see the actual `pip` resolution errors Portainer was swallowing:

- **First deadlock**: `llama-index-core>=0.12,<0.15` was too broad — `llama-index-readers-file 0.4.x` pins core to `<0.13` but `llama-index-embeddings-huggingface 0.6+` needs `>=0.13`. Pip backtracked forever and aborted. Fix: bump the four `llama-index-*` pins to the 0.13/0.14 line together (`core>=0.13,<0.15`, `readers-file>=0.5`, `embeddings-huggingface>=0.6`, `retrievers-bm25>=0.5`).
- **Second deadlock**: new core line pulled `llama-index-workflows` which requires `pydantic>=2.11.5`; our pin was `pydantic==2.10.4`. Loosened to `>=2.11.5`.
- Added `build-essential` to `Dockerfile.backend` defensively — `python:3.11-slim` lacks gcc/g++ and `PyStemmer` (pulled transitively by BM25) needs a C compiler. Builds were failing on clean hosts without the toolchain.

Final installed versions for the record: `llama-index-core 0.14.20`, `readers-file 0.6.0`, `embeddings-huggingface 0.7.0`, `retrievers-bm25 0.7.1`, `pydantic 2.13.3`.

### Operations

- Existing indexes must be reindexed — 384-dim MiniLM vectors are not compatible with 1024-dim BGE-M3. Admin → Frontends → Company → Reindex, or let the file watcher pick up a touch on any doc.
- Contextual Retrieval is persisted in in-memory config only; to make it survive container restarts, edit `deployment_backend.json` and redeploy.
- ChromaDB as a vector-store migration captured in `docs/IDEAS.md` as the natural next upgrade when CBC crosses ~100+ companies with active docs.

## Sprint 8 — Polish, testing, deployment + full i18n (2026-04-20)

- **Full 31-language UI translation bundle** (HRDD parity): `src/frontend/src/i18n.ts` rewritten end-to-end. `LANGUAGES` grows from 5 to 31 entries (EN, ZH, HI, ES, AR, FR, BN, PT, RU, ID, DE, MR, JA, TE, TR, TA, VI, KO, UR, TH, IT, PL, NL, EL, UK, RO, HR, XH, SW, HU, SV). 82 keys translated per language. RTL declared for `ar, ur`. `t(key, lang)` falls back `lang → EN → key-name`. Translations generated by Claude flagged as MVP-quality pending native-speaker QA.
- **RTL rendering**: `App.tsx` sets `document.documentElement.lang` + `dir="rtl"|"ltr"` on every language change using the new `RTL_LANGS` constant — Arabic/Urdu flows right-to-left without per-component wiring.
- **Per-tier admin-editable translations** (D5=B): `Branding` model extended with `source_language`, `disclaimer_text_translations: dict[str,str]`, `instructions_text_translations: dict[str,str]`. Resolver rule: whichever tier owns the source text also owns the translations dict — translations cannot be overridden without also setting the source, so mismatches between a tier's source and a lower tier's translations never happen. Sidecar baseline extended with the same three fields; the merge keeps existing `{empty-string inherits, non-empty overrides}` semantics and treats empty dicts as passthroughs.
- **Translation bundle download / upload** (D2=C): new admin endpoints `GET/PUT /admin/api/v1/branding/defaults/translations` and `/frontends/{fid}/branding/translations`. Portable JSON shape `{source_language, disclaimer_text, instructions_text, disclaimer_text_translations, instructions_text_translations}`. Apply-to merges onto the existing record without clobbering logo/colors/titles. New reusable `admin/src/components/TranslationBundleControls.tsx` (source-lang picker, Download, Upload, coverage counters) mounted from BrandingSection + BrandingPanel.
- **LLM auto-translate** (D4=A): `POST /admin/api/v1/branding/defaults/auto-translate` and the per-frontend equivalent. New `services/branding_translator.py` walks every language ≠ `source_language` and for each empty slot calls `llm_provider.chat(slot="summariser")` with the new `prompts/translate.md` system prompt. Existing non-empty translations preserved. Failures per-language are logged and skipped — the endpoint returns `{disclaimer_filled, disclaimer_failed, instructions_filled, instructions_failed}` stats. Synchronous (30–60 s on a local summariser) — simpler than a background-job surface for an operation admins do rarely.
- **Frontend cascade**: new `pickBrandingText(source, source_language, translations, lang)` helper in `i18n.ts`. DisclaimerPage + InstructionsPage call it so user sees `translations[lang] → source → i18n default`. When an admin sets a custom disclaimer but hasn't translated for the user's language yet, the page shows the source text (with the correct `lang`/`dir` on the wrapper) rather than the i18n copy — keeps the experience consistent with admin intent.
- **`docs/INSTALL.md`**: first-deploy guide covering host setup, backend + frontend stacks, LLM provider choice (local / api with env-var key handling), SMTP, admin bootstrap, per-frontend config, content drop-in conventions, smoke test, upgrade, troubleshooting.
- **SPEC §7 rewritten**: now §7.1 Supported languages (full 31-lang list + RTL), §7.2 Translatable admin-editable text (tier rules + cascade), §7.3 Translation workflow (download/upload/auto-translate).
- Type-check clean on admin + frontend TS; Python AST parse clean across new/edited backend files.

## Sprint 7.5 — Guardrails review + enforcement (2026-04-20)

- **HRDD Sprint-16 enforcement pattern** (D3=A): `polling._process_turn` now **skips the LLM on any triggered turn**. The user's raw turn is persisted, guardrails fire, counter increments, and a fixed category-appropriate response is pushed as the assistant message. Once `violations >= guardrail_max_triggers`, the session is flagged + marked `completed`, the session-ended message is delivered, and subsequent turns would hit the same dead-end. No more "UI blocks but backend still answers" gap.
- **Pattern review** (kept HRDD patterns; one CBC tweak): `fired` dropped from the "workers from {group} are [verb]" discriminatory-framing pattern — legitimate CBA contract text uses `fired` routinely, so it was the one high-false-positive pattern. `deported|removed|eliminated` remain as the intent signal. All other HRDD patterns kept verbatim.
- **No new `fabrication` category** (D1=B): CBC's user population is authenticated trade-union delegates via the Contacts allowlist, and the `guardrails.md` prompt layer already instructs the LLM to refuse fabrication. If a delegate tries to jailbreak, that's on them — the runtime layer doesn't need the extra regex burden.
- **Thresholds** (D2=global): `guardrail_warn_at` added to `core/config.BackendConfig` (default 2). `guardrail_max_triggers` kept (default now 5, was 3). Both surfaced in `deployment_backend.json`. Per-frontend overrides deferred.
- **Sidecar → ChatShell** live thresholds: new public backend endpoint `GET /api/v1/guardrails/thresholds` returns `{warn_at, end_at}`; sidecar proxy `/internal/guardrails/thresholds` (with 2/5 fallback if the proxy call fails). ChatShell reads on mount; hardcoded `VIOLATION_WARN_AT` / `VIOLATION_END_AT` constants gone.
- **Admin viewer** (D4=A): new `GET /admin/api/v1/guardrails` returns `{categories, thresholds, sample_responses}` for the authed admin. New `sections/GuardrailsSection.tsx` read-only viewer mounted at the bottom of General tab — shows the per-category pattern catalogue, the two thresholds, and the localised responses the user sees on trigger vs session-end.
- **Test corpus** (D5=A): `docs/knowledge/guardrails-test-corpus.md` — paste-ready triggering + non-triggering samples per category, recovery check, and tuning notes. Known limitations documented (e.g. "ignore your previous instructions" doesn't match because of the double adjective).
- **SPEC §4.10 rewritten**: two-layer model (prompt + runtime) explicit, enforcement pattern specified, thresholds documented, per-frontend override deferral called out.
- Smoke: 5 triggered turns → `status=completed, flagged=true, violations=5, message_count=12`. Admin Sessions tab shows the session as ⚠️ completed + flagged. Public thresholds endpoint returns 2/5 as configured.

## SessionsTab polish — grouped by frontend + pinned summary + upload download/copy (2026-04-20)

- **One table per frontend**: sessions are bucketed by `frontend_id`, each group gets its own card with a header (frontend name + session count) and its own table. Global filter tabs (all / active / completed / flagged) still apply across every group.
- **Pinned Session summary in the detail drawer**: admin endpoint `GET /admin/api/v1/sessions/{token}` now returns `summary` at the top of the payload (the last `assistant_summary` message). Drawer renders it as the first section below the header, with a Copy-summary button and markdown rendering. The original summary bubble still appears in the conversation below for audit.
- **Download + Copy-text per upload**: new admin-authed endpoint `GET /admin/api/v1/sessions/{token}/uploads/{filename}` streams the raw file with path-traversal guards (`safe_filename` + `relative_to` check). `api.ts` gains `downloadSessionUpload(token, filename)` (fetch → blob → anchor-click) and `copySessionUploadText(token, filename)` (fetch → text → clipboard). Copy-text is only surfaced for `.txt` / `.md` uploads; Download is always available.
- Per-row feedback text ("Downloading…", "Saved", "Copied") appears next to the buttons and auto-clears after 2 s.

## Sprint 7 — Sessions & Lifecycle (2026-04-20)

- **Session lifecycle scanner** (`services/session_lifecycle.py`): 5-min background loop. Auto-closes sessions idle past `auto_close_hours`; rm -rf session trees that have been `completed` for longer than `auto_destroy_hours` (`=0` means never). `session_store.set_status("completed")` stamps `completed_at` to drive the destroy timer. Wired into `main.py` lifespan alongside polling + rag_watcher.
- **Real auth flow** (`api/v1/auth.py`): `POST /api/v1/auth/request-code` + `verify-code`. Contacts allowlist check (SPEC §4.11) when `auth_allowlist_enabled=true` (default, togglable in `deployment_backend.json` for bootstrap). SMTP send via `smtp_service.send_email` when configured; `dev_code` returned inline when SMTP offline so AuthPage bootstrap stays smooth (D7=A). 15-min TTL, one-shot codes, in-memory store. Sidecar `/internal/auth/*` rewritten as thin relays — the HRDD dev-stub generator is gone.
- **Session recovery** (`GET /api/v1/sessions/{token}/recover` + sidecar proxy + SessionPage button): replays the persisted conversation into the chat view (D1=B — no in-flight stream re-attach). Honours `session_resume_hours`; HTTP 410 past the window. SessionPage grows a "Resume existing session" path with token input + error handling (not-found / expired / network). ChatShell accepts `recoveryData`, skips the initial-query bubble when replaying, seeds violation count + session-ended state.
- **SMTP summary on close** (`polling._process_close`): after the inline summary streams, schedules a non-blocking `send_email` to `survey.email` when provided AND SMTP is configured. UI close-flow is unchanged if either precondition is missing.
- **SMTP admin alert on upload** (`api/v1/sessions/uploads.py`): fire-and-forget notification to `smtp_service.resolve_admin_emails(frontend_id)` when the user drops a file in chat. Gated by the `send_new_document_to_admin` toggle + SMTP configured.
- **Admin Sessions tab** (`admin/src/SessionsTab.tsx`): list with filter tabs (all / active / completed / flagged), 10-s auto-refresh, columns distilled from HRDD — Token, Frontend, Company, Country, Status, Msgs, Violations, Last activity, Flag, Destroy (dropped role/mode/report indicators per ADR-004/006). Detail drawer shows survey + conversation (markdown-rendered via react-markdown + remark-gfm) + uploads list + flag/destroy actions. Backend: `api/v1/admin/sessions.py` list/detail/flag/destroy.
- **Dashboard**: Sessions tab added between Frontends and Registered Users (4 tabs total).
- Deps: `email-validator>=2.0` in backend (for `pydantic.EmailStr`); `react-markdown` + `remark-gfm` in admin (for the detail drawer conversation view).

## Attachment-aware turns — force-include newly uploaded files (2026-04-20)

- **Bug fix** reported during Sprint 6B smoke: attaching a file + sending a vague text ("what do you think?") made the assistant respond as if no file was there, because semantic retrieval on the vague text didn't pull the file's chunks.
- Frontend now sends `attachments: [filename]` in the `/internal/chat` POST body when ready chips ride along with a turn.
- Sidecar `ChatMessage` model gains an `attachments: list[str] = []` field; the queued chat item carries the list to the backend.
- `session_store.add_message` accepts an optional `attachments` list and persists it alongside the message (both in memory cache + conversation.jsonl). `get_llm_messages` decorates the user content with `[The user attached this turn: foo.pdf]\n\n…` so the LLM sees a clear signal. Raw content on disk stays clean.
- `session_rag.get_chunks_for_files(token, filenames)` — iterates the session's LlamaIndex docstore and returns every chunk whose source matches one of the named files. Used for forced inclusion in the prompt context.
- `prompt_assembler.assemble` gains a `fresh_attachments` arg. When set, those files' chunks are force-injected (score = 1.0) into the RAG context independently of the semantic top-k query, and dedup'd against the normal session-RAG pass so we don't duplicate the same chunk.
- `polling._process_turn` accepts `attachments`, passes them to both `session_store.add_message` (for persistence + LLM content decoration) and `prompt_assembler.assemble` (for forced chunk inclusion).
- File-only turns supported: user drops a PDF without typing anything, backend seeds the text with `"Please examine the files I just attached: …"` so the LLM has a pivot.
- Verified end-to-end: vague turn with attached `draft_cba.txt` now produces a response that references the attached draft's provisions.

## Sprint 6B — React ChatShell + end-session + context compressor (2026-04-20)

- **Chat is live in the browser.** Survey submission now navigates into a real chat view: initial query appears instantly as the first user bubble, assistant response streams in, multi-turn works, End-session runs the summariser slot and drops an inline "Session summary" block with a Copy-to-clipboard button.
- `frontend/src/components/ChatShell.tsx` (~350 LoC, adapted from HRDD): EventSource subscription, ReactMarkdown + remark-gfm rendering, textarea auto-resize, Enter-to-send, attachment chips, End-session confirm modal, guardrails banner.
- `App.tsx` now has a `chat` phase (`placeholder` retired). `beforeunload` warning extends to the chat phase.
- i18n strings for all chat UI (send, thinking, end-confirm, summary, guardrail warning, attachment chips) in English; fallback for other languages until Sprint 8 translations.
- Backend `POST /internal/close-session` (sidecar) + `close`-type handler in `polling.py`: resolves `summary.md` via Sprint 4B resolver, runs the **summariser** slot, streams tokens through the existing SSE channel, marks session `status='completed'`. SMTP send is logged as a TODO for Sprint 7.
- Backend `GET /api/v1/sessions/{token}/status` — lightweight poll target for violation count + status (drives the chat UI banner + end-of-session lock).
- **Real context compressor** (`services/context_compressor.py`): progressive thresholds (`first_threshold + step_size * n`), keeps the last 4 turns verbatim, folds the older prefix into a single system summary via the **compressor** slot. Per-session cache (in-memory), cleared on `destroy_session`. Token estimate is `chars/4` — good enough to trigger at 20 k / 35 k / 50 k; the LLM has the final word on billing.
- `polling.py`'s `_process_turn` calls `context_compressor.compress_if_needed` right before the inference streamer.
- `session_store.destroy_session` additionally drops `context_compressor` + `session_rag` in-memory caches so the ADR-005 privacy wipe leaves nothing behind.
- **Guardrails UI**: ChatShell polls `/status` every 5 s; banner shows at `violations ≥ 2` (amber), red "session ended" state at `violations ≥ 5`. Thresholds are hard-coded in 6B — **Sprint 7.5 "Guardrails Review"** added to MILESTONES for a dedicated trigger-list tuning + admin-configurable thresholds.
- **File upload chips in chat**: drag-drop or button click routes files through the Sprint 5 sidecar `POST /internal/upload`. Chips show `uploading → ready → sent` states; ready chips ride along with the next turn and appear as file pills on the user bubble; session RAG picks them up automatically (Sprint 5 pipeline unchanged).
- `react-markdown` + `remark-gfm` added to frontend deps (matches HRDD).

## Sprint 6A — Backend chat engine + sidecar SSE (2026-04-20)

- **Full chat loop wired end-to-end** (curl-tested): survey POSTed to sidecar → backend polls → session initialised → initial_query injected as first user turn → prompt assembled with all 7 layers → LLM streams → tokens relayed to sidecar SSE queue → `curl -N` on the EventSource endpoint sees real tokens in real time, with responses citing the correct company-tier RAG sources.
- **`services/session_store.py`** — disk-backed per-token session (`session.json` + `conversation.jsonl`), in-memory cache, atomic writes, `destroy_session` rm-tree-all for ADR-005 auto-destroy. Tracks `guardrail_violations` + `initial_query_injected` counters.
- **`services/llm_provider.py`** — OpenAI-compatible streaming for lm_studio / ollama / api (anthropic|openai|openai_compatible). Per-slot circuit breaker (3 fails / 60 s → 300 s cooldown, lessons-learned §4). Fallback cascade per D3: every slot's chain is `[own, summariser, inference, compressor]` deduped — inference falls back `inference → summariser → compressor` (summariser typically the most capable for chat).
- **`services/prompt_assembler.py`** — 7-layer assembly over Sprint 4B resolvers + Sprint 5 RAG: core → guardrails → role (cba_advisor.md / compare_all.md) → context_template → glossary → organizations → RAG chunks. Compare All path skips company-tier prompts (§2.4). Session RAG queried alongside permanent scopes when a `session_token` is passed. Naive `{var}` substitution with derived `comparison_scope_line` + `identity_block` blocks (empty collapse so anonymous sessions don't leak blank lines).
- **`services/polling.py`** — replaces Sprint 4A's health-only loop. 2 s interval. Per frontend: health check, queue drain. Dispatches by message `type`: `survey` initialises the session + injects the initial query; `chat` runs the turn pipeline (guardrails → persist → assemble → stream → relay → persist assistant). Old `polling_loop.py` deleted; `main.py` swapped accordingly.
- **Sidecar SSE relay** (HRDD pattern): `POST /internal/chat` enqueues a chat turn; `POST /internal/stream/{token}/chunk` delivers backend-pushed events (`token` / `done` / `error`); `GET /internal/stream/{token}` is the EventSource endpoint with 30 s keepalive comments. One `asyncio.Queue` per session token (D1=A serial — second message queues behind first).
- **`services/guardrails.py`** — hate-speech + prompt-injection regex patterns copied verbatim from HRDD; CBC-themed localised responses (en/es/fr/de/pt) mentioning collective-bargaining research. Log-only in 6A; 6B adds the session-ended flow. Daniel flagged the trigger list for post-smoke tuning.
- **`services/context_compressor.py`** — stub only (import graph stable). Sprint 6B implements progressive-threshold summarisation using the compressor slot.
- **Template fix** mid-smoke: `context_template.md` uses `{comparison_scope_line}` + `{identity_block}` as optional blocks; the renderer now computes these from survey fields (Compare All → one-line scope; anonymous → empty identity block) and collapses blank lines.
- 6B remaining: React `ChatShell.tsx` (adapt HRDD), End-session button + user summary via the summariser slot, real context compressor, guardrails UI warning banner.

## Sprint 5 — RAG Engine + File Watcher (2026-04-20)

- **Real 3-tier RAG indexing** via LlamaIndex + `sentence-transformers/all-MiniLM-L6-v2`. `services/rag_service.py` keys an in-memory `VectorStoreIndex` cache by `scope_key` ("global" / "{fid}" / "{fid}/{slug}"), reuses Sprint 4B's `resolvers.resolve_rag_paths` shape so the Sprint 6 chat engine just calls `query_scopes(paths, query)`. Sprint 3's stub in `rag_store.py` is now a thin bridge: upload/delete invalidate the scope's cache, reindex delegates to the real service.
- **File watcher** (`services/rag_watcher.py`): single `watchdog.Observer` over `/app/data/`, scope detection from path, **per-scope 5s debounce**, write-event filter (`created/modified/deleted/moved` only — stops the feedback loop where the indexer's own file reads were scheduling rebuilds), iCloud/Office/vim/DS_Store filter per lessons-learned §8. Bulk 3-file drop → 1 rebuild; delete → 1 rebuild; `.icloud`/`.DS_Store`/`._*` ignored without a log entry. Started + stopped cleanly in `main.py` lifespan.
- **Session RAG** (`services/session_rag.py`): per-session index under `/app/data/sessions/{token}/{uploads,rag_index}/` (D3=A — one tree, clean rmtree on auto-destroy per ADR-005). Accepts `.pdf/.txt/.md/.docx` (`.docx` is session-only; admin RAG stays narrower). Full pipeline ships this sprint (D6=A): `POST /api/v1/sessions/{token}/upload` + `GET /uploads` + `DELETE /{token}`; sidecar `POST /internal/upload` relays multipart to `cbc-backend:8000` over `cbc-net`. Sprint 6 will wire the chat upload UI on top.
- **Document metadata + country auto-derive** (D1=A, D2=A). New `services/document_metadata.py` reads per-directory `metadata.json` mapping `filename → {country, language, document_type}`. Every reindex at a company scope calls `_sync_derived_country_tags` which aggregates unique country values and writes them back to the Company record. The `Sprint 5` placeholder note in the admin panel disappears: country chips are live. Admin UI: per-document mini-form in `RAGSection` at company tier (Country / Language / Document type) with Save on change.
- **Compare All filtering** (Sprint 4B resolver verified): `national` mode filters to companies whose derived `country_tags` match the user's country; `global` mode returns every enabled company. Company-level filter (not chunk-level) — per-SPEC §3.3.
- **Deps + Dockerfile** (D5=A): added `llama-index-core>=0.12,<0.15`, `llama-index-readers-file`, `llama-index-embeddings-huggingface`, `sentence-transformers`, `watchdog`, `docx2txt`. `Dockerfile.backend` installs `torch` CPU-only BEFORE `requirements.txt` (HRDD pattern — avoids ~5 GB CUDA bloat) and **pre-downloads** the embedding model weights so first chat query doesn't hit HuggingFace at runtime. Image grows ~90 MB; air-gapped friendly.
- **Lifespan**: `main.py` now starts `rag_watcher` and stops it cleanly alongside the existing polling loop.
- **Smoke-tested end-to-end** (all 13 acceptance criteria): indexed 3 global docs → 39 nodes, query returns ranked chunks with scope tagging; file watcher debounce + filter verified; metadata update → country_tags auto-update verified; session upload via sidecar → backend → queryable verified; Compare All with `national`/`global` scope verified.

## Per-frontend LLM: per-slot override mirroring the global UI (2026-04-19)

- Per-frontend `LLM` panel rebuilt to match the global LLM editor 1:1: providers status (LM Studio + Ollama) at top, then a slot card for each of `Inference`, `Compressor`, `Summariser`, with a single **Override** checkbox in the slot header.
  - Unchecked → slot shows the global value, all inputs disabled and the card greyed (`bg-gray-50` + `disabled:bg-gray-100`).
  - Checked → snapshots the global slot into the override, makes the inputs editable. Save persists the override.
- Compression and summary-routing always inherit from global at the frontend tier — not exposed in the per-frontend panel. (Easy to expose later if needed; for now the simpler 3-slot UX matches Daniel's spec.)
- Backend `LLMOverride` model is now per-slot optional: `{inference, compressor, summariser}` each `SlotConfig | None`. `null` = inherit. `resolve_llm_config(fid)` merges per slot. Save with all-None deletes the file (intent and disk stay in sync).
- Migration: legacy `llm_override.json` files (full LLMConfig with `compression` + `routing` blocks) load without error — the migration extracts just the three slots and drops the rest.
- Extracted `SlotEditor` and `ProviderCard` to `src/admin/src/components/llm/` so both the global `LLMSection` and the per-frontend panel share the same widget. `SlotEditor` gains a `disabled` prop (greys + freezes inputs and skips model auto-correction) and a `headerRight` slot (used to mount the per-frontend Override checkbox).
- Admin route `PUT /admin/api/v1/frontends/{fid}/llm` now accepts the `LLMOverride` shape; `GET` always returns one (no longer `null` — empty override means all slots inherited).

## Companies: alphabetical sort, drop sort_order (2026-04-19)

- Companies are now ordered automatically: **Compare All entries first, then alphabetical by display name** (case-insensitive). Sort applied in three places so wire order is canonical: backend `list_companies`, sidecar `/internal/companies`, plus a defensive sort on `CompanySelectPage` for any future endpoint that returns unsorted data.
- Dropped the `Company.sort_order` field everywhere — model, request schemas, admin UI input, frontend types. Existing `companies.json` entries with `sort_order` still load (Pydantic `extra="ignore"`); the field is dropped on next save.
- Cleaned the bundled sidecar `companies.json` to remove `sort_order`.
- Defaults reminder: `combine_frontend_rag` and `combine_global_rag` both default to `true`, so a brand-new company sees both Combine RAG checkboxes ticked unless the admin unticks them.

## Combine RAG: unified checkbox UX at frontend + company tiers (2026-04-19)

- Both RAG sections (frontend + company tier) now have a **Combine RAG** subsection at the top:
  - **Frontend RAG**: one checkbox `Global` — controls whether the cross-sector global RAG can be pulled into chat sessions served by this frontend.
  - **Company RAG**: two checkboxes `Frontend` + `Global` — opt the company in or out of each higher tier independently.
- Replaced the legacy 5-value `rag_mode` enum on `Company` with two booleans `combine_frontend_rag` / `combine_global_rag` (both default true). The five old values were already reducible to two bools — `inherit_X` and `combine_X` produced identical resolver behaviour. Migration handled in `company_registry.list_companies`: legacy entries are translated before Pydantic validates, so old `companies.json` entries don't get silently demoted to the True/True default.
- Replaced `RAGSettings.global_rag_mode: "combine"|"ignore"` with `RAGSettings.combine_global_rag: bool` (default true). Migration in `rag_settings_store.load`. Resolver `_frontend_is_standalone` now reads the bool directly.
- Dropped the per-company **RAG mode** dropdown from `CompanyManagementPanel` — that setting now lives next to the documents it controls inside `RAGSection`. The expanded company row is cleaner: just `Sort order`, then on expand the Prompts + RAG sections (with Combine RAG at the top).
- `RAGSection` props extended with optional `company` + `onCompanyChanged` so the company-tier subsection can save Combine settings via `updateCompany` without refetching.
- Resolver semantics unchanged on the wire — the same documents are returned for the same admin-intent. Just the field names and the UI changed.

## Session settings overhaul: drop inherit/null, move RAG-standalone into RAG section (2026-04-19)

- `SessionSettings` model rewritten: every field is concrete with a default — `auth_required: bool = True`, `disclaimer_enabled = True`, `instructions_enabled = True`, `compare_all_enabled = True`, `session_resume_hours = 48`, `auto_close_hours = 72`, `auto_destroy_hours = 0`. The previous `bool | None` / `int | None` "inherit" semantics are gone — admins always see a concrete value, defaults match the deployment_frontend.json baseline.
- `rag_standalone` removed from session settings entirely. New per-frontend `rag_settings_store.py` (`RAGSettings.global_rag_mode: "combine" | "ignore"`, defaults to `combine`). Resolver `_frontend_is_standalone` now reads from there.
- New admin routes `GET / PUT / DELETE /admin/api/v1/frontends/{fid}/rag-settings`. Backend-only — not pushed to the sidecar (sidecar doesn't need to know).
- `SessionSettingsPanel` rebuilt: numeric inputs with inline help (session resume / auto-close / auto-destroy each get a one-sentence explanation), boolean toggles as plain checkboxes (default ON, no 3-way "inherit / true / false"). "Remove override" button renamed → "Reset to defaults" (deletes the file, panel falls back to defaults).
- `RAGSection` at the **frontend tier** gains a "Global RAG mode" dropdown at the top with the same combine/ignore choice, plus a one-paragraph explanation of what each option means in resolution. Hidden at global and company tiers.
- Loader is forgiving: existing session_settings.json files with `null` values or the legacy `rag_standalone` key are cleaned (Nones dropped, unknown keys filtered) before validation, so old data doesn't error out — it just falls back to defaults for any field that was inherit-style before.

## Prompts: + summary.md, drop prompt_mode, hide compare_all/summary at company tier (2026-04-19)

- New canonical prompt **`summary.md`** — runs at session end, takes the full conversation, produces the user-facing summary that gets emailed out. Default content shipped at `src/backend/prompts/summary.md` and seeded into `/app/data/prompts/` on backend startup.
- Canonical prompt count is now 6 (core, guardrails, cba_advisor, compare_all, context_template, summary). Visible at all tiers except company, where compare_all (cross-company by definition) and summary (session-end, not company-scoped) are hidden — only core, guardrails, cba_advisor, context_template show on a company panel.
- Dropped `Company.prompt_mode` everywhere — pure dead storage, no logic ever read it. Prompts are winner-takes-all (company → frontend → global) per the resolver, and that's already correct without a mode flag. Removed from: `services/company_registry.py`, `api/v1/admin/companies.py` (Create + Update request models), admin `Company` interface, `CompanyManagementPanel` (Sort/Prompt/RAG was a 3-col grid → now 2-col Sort/RAG). Existing companies.json carrying the field still loads (Pydantic ignores extras); the field is dropped on the next save.

## Prompts UX: same menu at every tier, edit-and-save commits to the current tier (2026-04-19)

- `PromptsSection` rewritten. Same UX at global, frontend, and company tier — the canonical 5 prompts (`core.md`, `guardrails.md`, `cba_advisor.md`, `compare_all.md`, `context_template.md`) are always visible. The previous "list per-tier overrides only + arbitrary new-prompt form" model is gone.
- Each row shows a tier badge (gray/blue/purple ◆ when owned at the current tier) so the admin sees at a glance which prompts are inherited and which are owned here.
- Editor pane shows the *effective* content (whatever the resolver picks). Save always writes at the current tier — creating an override on the spot. "Remove this-tier override (revert to {parent})" appears only when the current tier owns the file.
- Company tier rule: only `cba_advisor.md` is editable per Daniel's spec. The other four show as read-only with an "Editable only at frontend / global tier" notice — UI hides save/remove and the textarea is disabled. Backend mirrors the rule: `PUT /admin/api/v1/frontends/{fid}/companies/{slug}/prompts/{name}` rejects non-`cba_advisor.md` writes with HTTP 400 so the rule isn't enforceable only client-side.
- Implementation: on tier change, parallel `previewPromptResolution` for all 5 prompts populates the resolution map. The "Preview resolution" button is gone — the always-visible tier badge replaced it.

## Company creation: display name only (slug auto-derived) (2026-04-19)

- Same refactor as the frontend-registration one, applied to companies. Add-company form now asks only for **Display name**; the slug (storage key under `/app/data/campaigns/{frontend_id}/companies/{slug}/`) is derived server-side by slugifying the name with `-2`, `-3`, … appended on collision.
- Backend: `company_registry._slugify` + `next_unique_slug` + `slug_for_name(frontend_id, name)`. `CreateCompanyRequest.slug` is now optional; the route auto-derives if absent.
- Admin UI: Slug input removed from the add-company form. Pressing Enter in the name field submits. The slug chip on each row stays — admins use it when navigating `/app/data/campaigns/{frontend_id}/companies/{slug}/` on disk for direct file work or debugging. Toast on add now reports the assigned slug for visibility.
- Internal callers (e.g. config restore) can still pass an explicit slug — the API just doesn't require it from admins.

## Frontend registration: URL + name only (frontend_id auto-derived) (2026-04-19)

- Admin's Register form now asks for **URL + display name** only. The internal `frontend_id` (the slug used to key `/app/data/campaigns/{frontend_id}/`) is derived by slugifying the name; collisions get `-2`, `-3`, … appended.
- Backend `RegisterRequest`: `frontend_id` removed; `name` now required. `frontend_registry.register(url, name, frontend_id=None)` — optional `frontend_id` arg lets internal callers restore state explicitly, but admins go through the UI which never sends it.
- Frontend containers are now fully anonymous: they don't need `CBC_FRONTEND_ID` either. The previous env-var injection still works for backwards compat (and remains useful if you want the sidecar's `/internal/config` to report a specific ID for diagnostics) but is no longer required for the backend to address the right config tree — the backend already knows which frontend it's polling because it's hitting that frontend's registered URL.
- Admin UI: list rows drop the inline `<code>frontend_id</code>` chip — display name is the user-facing identifier everywhere. Unregister confirm uses the display name and explains that disk config survives and can be reclaimed by re-registering with the same name.
- SPEC §4.9 + §9.1 rewritten to reflect the new model.

## Multi-frontend support: env-var identity override (2026-04-19)

- Sidecar now reads `CBC_FRONTEND_ID` from the container environment at startup and overrides the `frontend_id` field from the JSON baseline. With this, one image can be deployed N times by setting different env vars per container — no rebuild needed.
- Demo: spun up a second frontend (`graphical-am`) on port 8191 alongside the existing `packaging-eu` on 8190 using `docker run -e CBC_FRONTEND_ID=graphical-am -p 8191:80 -v cbc-frontend-graphical-am-data:/app/data --network cbc-net cbcopilot-cbc-frontend`. Both `/internal/config` endpoints return distinct `frontend_id` values; backend reaches both over `cbc-net` (`http://cbc-frontend` and `http://cbc-frontend-graphical-am`).
- SPEC §9.1 updated with the multi-frontend deployment recipe (the same recipe maps cleanly to a Portainer stack — one stack per frontend, env vars override identity + port + container/volume name).
- Compose files left untouched for backwards compatibility — first frontend still defaults to `packaging-eu` from the baked-in JSON.

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
