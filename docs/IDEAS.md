# CBC — Ideas Backlog

Feature ideas captured during development but not yet scoped into a sprint. Each entry shows when it was captured and, when known, a candidate sprint to land it in.

Statuses: `captured` → `triaged` → `planned` (→ Sprint N) → `shipped` / `rejected`.

---

## Chunking legal-aware — splits por "Art. N / Cláusula N / Article N / Section N"

**Captured:** 2026-04-29 (validation against external RAG-for-legal recommendations)
**Status:** captured
**Candidate sprint:** Sprint 19 (after Sprint 18 fases 1+2 validate).

**Symptom:** the current chunker (`rag_service._parse_nodes`, Sprint 15 fix) splits markdown via `MarkdownNodeParser → SentenceSplitter(chunk_size=1024)`. Inside one heading-section it slices by token count, which means a long Art. 23 about "Retribuciones" can land split across two chunks at an arbitrary sentence boundary. The user's question "¿qué dice el Art. 23 sobre el complemento nocturno?" then matches half the article, the LLM cites half the article, and the missing half of the rule never reaches the prompt.

CBAs across countries share a strong structural signal: every clause is numbered. The current chunker ignores it.

**Rationale:** external RAG-for-legal literature (Redis blog, arxiv 2504.16121, Milvus / Zilliz FAQs) all flag this as a high-leverage low-cost fix for legal corpora. Validated against our own corpus: every CBA in `g-p1/amcor/` (ES + FR + AU) uses one of:
- `Art. N` / `Artículo N`           (ES, FR, IT, AU collective agreements)
- `Article N`                       (FR formal)
- `Cláusula N` / `Clause N`         (ES, AU)
- `Section N`                       (AU NES, EN-language CBAs)
- `ANEXO N` / `Annexe N` / `Annex N` (annexes — should NOT split inside; treat as a top-level section)
- `N.N.N` numeric (e.g. `13.4.1`)   (AU enterprise agreements)

**Idea:**

Pre-pass regex on the document text that inserts chunk boundary markers before every clause start. Plug it in front of the existing `MarkdownNodeParser → SentenceSplitter` pipeline:

1. Detect clause headers with a robust regex covering the patterns above (case-insensitive, allow trailing dash / colon / period).
2. For each detected match, ensure a chunk boundary lands exactly there — so an artículo never gets split across chunks unless its body itself exceeds `chunk_size`, in which case the SentenceSplitter still applies (and the article-header metadata propagates to all sub-chunks).
3. Carry the clause id (`Art. 23`, `Section 13.4.1`) into chunk metadata so `cba_citations_enabled` (Sprint 11 phase B) renders accurate locator hints.

**Implementation sketch** (`CBCopilot/src/backend/services/rag_service.py:_parse_nodes`, ~40 lines new):

```python
_CLAUSE_HEADER_RE = re.compile(
    r"(?im)^\s*("
    r"Art\.?\s*\d+(?:\.\d+)*"           # Art. 23, Art 12.4
    r"|Art[íi]culo\s+\d+"                # Artículo 23
    r"|Article\s+\d+"                    # Article 23
    r"|Cl[áa]usula\s+\d+"                # Cláusula 23
    r"|Clause\s+\d+"                     # Clause 23
    r"|Section\s+\d+(?:\.\d+)*"          # Section 13.4.1
    r"|ANEXO\s+[IVX]+"                   # ANEXO I, II
    r"|Annexe?\s+[IVX\d]+"               # Annexe I / Annex 2
    r")\b[\.\s:\-—]*"
)

def _segment_by_clause(text: str) -> list[tuple[str, str]]:
    """Split a document text into (clause_id, body) tuples. Body extends from
    the clause header up to the next clause header (or EOF). Text before
    the first clause is yielded with clause_id=''."""
    ...
```

Each segment becomes its own pre-chunk that the existing splitter never crosses. If a single segment is longer than `chunk_size`, SentenceSplitter still applies inside, but **all sub-chunks inherit the clause_id metadata**.

**Coste:** ~40 lines `_parse_nodes` + ~20 lines metadata propagation + tests with the live CBAs. Zero LLM calls. Re-embed needed (each chunk's text changes), so a Wipe & Reindex All to apply.

**Métrica de éxito:**

- Query "¿qué dice el Art. 23 sobre el complemento nocturno?" → exactly one chunk citing `Art. 23` lands at top-K, full body of the article reaches the prompt.
- Query "compara Art. 37 entre los CBAs" → up to N matches (one per CBA) where each has the exact `Art. 37` body, not adjacent fragments.
- Citation panel shows `[CBA Amcor Lezo, Art. 23]` consistently instead of paragraph-mid hints.

**No reemplaza el query rewriting cross-lingüe** del Sprint 18 fase 3 — son palancas complementarias. Chunking legal-aware mejora el recall **dentro** del idioma; query rewriting + glossary mejora el recall **entre** idiomas. Idealmente ambas.

**Lo que NO se hace en este sprint:**
- Embeddings legal-specific (XLM-RoBERTa fine-tuned). Coste de migración alto, evidencia incierta para CBAs sindicales (mezcla laboral-administrativo, no jurisprudencia). Re-evaluar si recall sigue cojeando tras chunking legal-aware + query rewriting.
- MLX para inferencia. Reescribir el path de `llm_provider` (Ollama HTTP → MLX in-process). 10-30 % más t/s pero coste de implementación alto. Sprint dedicado si lo priorizamos.
- RAGAS evaluation framework. Útil cuando hay >5 estrategias compitiendo. Por ahora 1 dev + validación manual cubren.
- Qdrant / Milvus. Chroma escala bien a este corpus; no hay caso de negocio.

---

## Recall en corpus grande — top-K dinámico, modo catálogo, query rewriting, watcher debounce

**Captured:** 2026-04-29 (post 23-doc upload to Amcor scope)
**Status:** captured
**Candidate sprint:** Sprint 18 — Recall en corpus grande.

**Symptoms observed by Daniel** subiendo 20+ archivos a Amcor (4 PDFs australianos + 19 .md franceses + 1 CBA español):

1. "Compara vacaciones en los convenios de Amcor" → respuesta cubre sólo España + 2 PDFs australianos. **15+ docs franceses ignorados**, pese a estar en disco.
2. "Lista los convenios de Francia en tu corpus" → enumera sólo 4 (de los 15+ presentes). El modelo admite que el retrieval es el problema, no el almacenamiento.
3. "Compara las subidas salariales pactadas" → respuesta dice "los fragmentos disponibles no contienen las cifras" cuando los CBAs SÍ contienen las tablas (+3% / +6% / etc.). Los datos están; el sistema no los recupera.
4. Última respuesta del chat sale **corrupta / truncada** ("permecia ( año que manta un día adonal de vacie..."). Coincide con un reindex que disparó mid-stream.
5. Subir 20 archivos en una tanda dispara **3 reindex completos del scope amcor** porque el debounce de 5 s no aguanta una sesión de upload del navegador. Cada pasada hace re-chunker + re-embed de los 20 archivos completos. ~30-60 s × 3 de trabajo redundante.

**Root causes diagnosed:**

- **`RAG_TOP_K_PER_SCOPE = 8` es estático.** Con 23 docs en el scope, 8 chunks no cubren ni el 30% del corpus. Los chunks que ganan el ranking son los que matchean más fuerte semánticamente con la query, lo que tiende a concentrar todo en 2-3 docs. El resto se vuelve invisible para el LLM aunque esté indexado.
- **Compare All no escala el top-K** con el número de docs activos. Hoy es la misma constante para 1 doc o 50 docs.
- **Queries de enumeración / catálogo se mandan al embedder.** "Lista qué docs tienes" no es una pregunta semántica, es una pregunta de inventario. El embedder devuelve los 8 chunks más parecidos a la query, no los 23 filenames del scope. Lo correcto es inyectar la lista completa de docs como metadato.
- **Queries comparativas multi-doc no se reescriben.** "Compara vacaciones España vs Francia vs Australia" se manda tal cual al embedder, una sola pasada. Una pasada no puede traer chunks de 3 jurisdicciones distintas con la misma puntuación. Hace falta query rewriting: descomponer en N sub-queries específicas (vacaciones España, vacaciones Francia, vacaciones Australia) y unir resultados.
- **Watcher debounce de 5 s es demasiado corto** para uploads masivos. Cada vez que un nuevo archivo llega tras los 5 s del último, dispara una pasada completa. Sin techo absoluto.
- **Reindex durante streaming corrompe la generación.** El `_build_locks` per-scope (Sprint 16) serializa builds, pero el chat sigue compitiendo por embedder + reranker. Si la query del chat es la siguiente en la cola del lock, el SSE puede llegar entrecortado.
- **Cross-lingüe es agravante, no causa primaria.** BGE-M3 es multilingüe por diseño y maneja ES↔FR↔EN razonablemente bien para vocabulario común. PERO el corpus de Daniel mezcla terminología técnico-legal sin equivalente directo: `enveloppe individuelle`, `prévoyance`, `astreinte`, `CSE`, `NAO`, `cadres / non-cadres` (FR) no tienen traducción literal en los docs ES o AU. Si la query española es genérica ("compara vacaciones") sin mencionar estos términos, BGE-M3 puntúa más alto los chunks que matchean "vacaciones" / "annual leave" literalmente, y los chunks franceses con jerga local quedan fuera del top-K aunque traten temas relacionados (descansos, permisos, congés). El cuello de botella sigue siendo el `top_k` bajo, pero idioma + jerga lo amplifica significativamente en este corpus en concreto.

**Idea — sprint candidate, deliverables:**

1. **Top-K dinámico.**
   - `RAG_TOP_K_PER_SCOPE` se vuelve función de `len(files_in_scope)`: `min(max(8, files * 2), 40)`. 1 doc = 8 chunks; 23 docs = 40 chunks (clamped).
   - Compare All: `top_k_total = min(num_active_companies * top_k_per_company, 50)`.
   - Tablas: misma fórmula con un cap más bajo (cards son cortas, podemos meter más).
   - Coste: prompt total puede pasar de 25k → 60-80k chars en queries Compare All amplias. Aceptable con num_ctx=130k de Ollama.

2. **Modo catálogo.**
   - Detectar intención por keyword (ES + EN): "lista", "qué docs", "enumera", "list", "what documents", "inventory".
   - Cuando detecta: inyectar una sección `## Documentos disponibles en esta sesión` con los filenames del scope agrupados por país (extraído del filename auto-detector que ya tenemos en `document_metadata`). Sin pasar por embedder.
   - El LLM enumera completo en vez de adivinar desde 8 chunks.

3. **Query rewriting para comparativas multi-doc + multi-idioma.**
   - Detectar intención: "compara", "compare", "diferencias entre", "vs", "across".
   - Pasar la query al `compressor` slot con un prompt: "descompón esta pregunta en N sub-queries, una por entidad detectable en el corpus, **y traduce / adapta cada sub-query al idioma y jerga técnica de los docs de esa entidad** (ES→ES para España, ES→FR para Francia, ES→EN para Australia)". El compressor recibe el listado de docs disponibles + sus filenames (que ya codifican país) para saber qué idiomas/jergas usar.
   - Hacer retrieval con cada sub-query traducida — cada una pega mejor con su sub-corpus en su idioma nativo. Unir chunks deduplicados.
   - Total chunks inyectados con cap.
   - Coste: 1 LLM call extra al compressor (~2-4 s en qwen3.5:9b). Recall mucho mejor en cross-lingüe — esta es la palanca que más mueve recall según la literatura (técnica conocida como "query expansion / multi-perspective retrieval").

3b. **Glossary cross-lingüe de términos técnico-legales.**
   - Diccionario en código (no LLM-generated) mapeando conceptos laborales sin traducción literal: `enveloppe individuelle ↔ subida individual / merit increase`, `prévoyance ↔ previsión social / superannuation`, `astreinte ↔ guardia / on-call`, `CSE ↔ comité de empresa / works council`, `NAO ↔ negociación anual / annual bargaining`, `cadres / non-cadres ↔ personal directivo / managerial staff`, `Long Service Leave ↔ permiso por larga antigüedad`, `Award ↔ convenio sectorial`, etc.
   - El query rewriter consulta este dict antes de embebir: si la query menciona "previsión social", expande con sus equivalentes franceses + ingleses. Si menciona "vacaciones", añade "congés annuels" + "annual leave" + "Long Service Leave".
   - Coste: ~80 entries hardcoded, mantenible. Cero LLM calls. Muy efectivo para este corpus específico (CBAs multilingüe). Reusa el patrón del country-from-filename detector de Sprint 16.

4. **Watcher debounce robusto.**
   - Subir el debounce de 5 s a **30 s**.
   - Añadir techo absoluto: si el debouncer lleva pendiente >5 minutos sin disparar, forzar el fire (evita que un upload sin fin pare el reindex para siempre).
   - Detectar lock sostenido: si `_build_locks[scope].locked()` está True cuando el debouncer va a disparar, posponer 30 s extra en lugar de encolarse.

5. **Proteger el chat durante reindex.**
   - Añadir un `is_reindexing(scope_key)` check al inicio de `query_scopes`. Si está activo, esperar máx N segundos al lock. Si supera el timeout, devolver chunks "stale" del cache anterior (Chroma sigue sirviendo lecturas durante un build mientras el delete/insert no haya pasado).
   - Mejor aún: MVCC trick — snapshot de la collection al inicio del turn, leer de ahí, ignorar los inserts en curso.

**Métrica de éxito:**

- "Lista los convenios de Francia que tengo en Amcor" → respuesta correcta con los 15+ filenames.
- "Compara vacaciones en los convenios de Amcor" → respuesta cubre los 23 docs (o reconoce explícitamente cuáles no tienen cláusula de vacaciones).
- "Compara subidas salariales pactadas" → respuesta incluye las cifras concretas de los 4 PDFs AU + los NAOs FR + el CBA ES.
- Subir 20 archivos seguidos → **un solo reindex** al final de la tanda, no tres.
- Mandar un chat 2 s después de subir un archivo nuevo → respuesta normal, no corrupta.

**Estimación gruesa:** ~280 líneas backend (top-K dinámico + catálogo + query rewriter con traducción + glossary cross-lingüe + watcher fix), ~50 líneas frontend (opcional toggle "modo comparativo") + tests. 1-2 días.

**Add-on (Daniel, 2026-04-30) — Top-K knobs editables desde admin RAG Pipeline.**

Tras Fase 1 los valores `_DYNAMIC_TOP_K_FLOOR=5`, `_DYNAMIC_TOP_K_CEIL=40`, `_DYNAMIC_TOP_K_PER_DOC=2`, `tables_top_k floor/ceil`, y el `LOCK_BUSY_REPLAN_SECONDS` / `MAX_DEBOUNCE_HOLD_SECONDS` / `DEBOUNCE_SECONDS` del watcher quedan hardcoded en código. Daniel quiere poder tunearlos desde `Admin → General → RAG Pipeline` para probar combinaciones calidad/velocidad sin redeploy.

Plan:
- Mover los 3 + 3 valores a `core/config.py` con defaults equivalentes (`rag_top_k_floor`, `rag_top_k_ceil`, `rag_top_k_per_doc`, `rag_tables_top_k_floor`, `rag_tables_top_k_ceil_compare_all`, `rag_watcher_debounce_seconds` ya existe — extender con `rag_watcher_max_hold_seconds` y `rag_watcher_lock_replan_seconds`).
- Añadir admin endpoint `PATCH /admin/api/v1/rag/settings` extendido (ya existe para chunk_size + embedding_model en Sprint 15) o uno nuevo `PATCH /admin/api/v1/rag/tuning`.
- Persistir vía `runtime_overrides_store` (ya tenemos el patrón Sprint 15).
- En la UI, sección colapsable nueva en `RAGPipelineSection.tsx`: "Tuning avanzado" con sliders para top-K (floor / ceil / per-doc factor), watcher debounce (5-120 s slider), y un botón "Reset to defaults". Sin necesidad de wipe-and-reindex porque estos cambios afectan el path de query, no la indexación.
- Coste: ~80 líneas backend, ~120 líneas admin UI + i18n, sin re-embed.

Un pre-requisito: validar primero que los defaults actuales funcionan en el caso 23-doc (Fase 1+2 ya en main). Si Daniel encuentra el sweet spot tunándolos a mano vía admin, se vuelve la fuente de la verdad y los hardcoded ya solo son defaults razonables.

---

## Modo cita textual — full-text search sobre los docs recuperados en la sesión

**Captured:** 2026-04-24 (post-Sprint-16 validation)
**Status:** captured
**Candidate sprint:** TBD — depende de cuántos usuarios pidan citas textuales en producción.

**Symptom seen by Daniel:** el RAG funciona bien (chunks relevantes en el prompt, generación correcta), pero cuando le pide al chat "dame la cita textual del artículo 23" el LLM responde "no tengo acceso al texto fuente, sólo a fragmentos". Comportamiento correcto del LLM — no debe inventar texto literal. Pero la información que el usuario pide SÍ existe en el corpus.

**Idea:** cuando el usuario pide explícitamente una cita textual, el backend salta el path RAG-generativo y entra en un modo extractivo:

1. Detectar intención. Heurística por keyword en el turno del usuario ("cita textual", "transcribe", "literal", "verbatim", "exact wording", "palabras exactas") o un toggle UI "modo cita".
2. Construir el conjunto de documentos que ya alimentaron el contexto RAG en esta sesión — disponible vía los `sources` que el prompt_assembler ya emite turno a turno (el sidepanel CBA ya los lista).
3. Backend nuevo helper, p. ej. `rag_store.find_textual_matches(scope_keys, doc_names, needle, max_chars=2000)` — abre cada doc en disco y hace búsqueda literal o regex sobre el texto completo. Devuelve fragmentos crudos con filename + offset/línea.
4. El prompt assembler inyecta los matches verbatim bajo una sección `## Cita textual solicitada` con instrucción al LLM: "el usuario pidió cita textual; transcribe verbatim los fragmentos siguientes y atribúyelos al documento del que vienen".

**Ventajas:**
- Cero re-indexación; usa los archivos que ya están en `/app/data/.../documents/`.
- Permite extracción exacta sin alucinaciones, con trazabilidad ("según artículo 23 del CBA Amcor Lezo, página X: '...'").
- Compatible con Compare All — busca en todos los CBAs activos.
- Funciona con tablas (busca dentro del .md con la tabla intacta) y con .pdf vía pdfplumber.extract_text.

**Riesgos / decisiones previas:**
- Intención mal detectada: si la heurística falla, el modo se activa cuando no toca y se llena el prompt. Mitigación: empezar con toggle UI explícito antes de auto-detect.
- Tamaño del corpus: una sesión con 50 CBAs cargados haría 50 lecturas + búsquedas por turno. OK con regex pre-compilado + cap de matches; mejor aún con cache LRU del texto crudo por doc.
- Coincidencias múltiples: si la query matchea 30 sitios en 5 docs, hay que rankear (proximidad a la pregunta semántica, score RAG) y truncar.
- Permisos: sólo docs del scope visible al usuario actual (mismo filtro que session_rag).

**Estimación:** ~150 líneas backend (helper + integración prompt_assembler + heurística), ~30 líneas frontend (toggle + i18n), ~50 líneas tests.

---

## ChromaDB as vector store (drop SimpleVectorStore when scale demands it)

**Captured:** 2026-04-21 (Sprint 9)
**Status:** **shipped** in Sprint 10C (2026-04-21). Single persistent Chroma collection at `/app/data/chroma/`, `scope_key` as metadata filter — one DB serves global / frontend / company tiers. HNSW + BM25 scope-aware + cross-encoder rerank all ride on top.
**Candidate sprint:** TBD — trigger on one of (100+ empresas con docs / latencia de query > 50 ms / consumo de RAM por multi-scope noticeable)
**Context:** Sprint 9 overhauled the RAG quality (BGE-M3 + rerank + optional Contextual Retrieval). Persistence + framework choice were reviewed in the same breath. LlamaIndex's default `SimpleVectorStore` persists fine on disk, but it's brute-force cosine search and each scope is a separate index file — that's fine for now, becomes a problem as CBC scales to 200+ CBAs across many frontends.

**Idea:** Migrate the vector store layer to **ChromaDB embedded** (no server) via `llama-index-vector-stores-chroma`. Three concrete wins:

1. HNSW indexing → sub-10 ms queries at 100k+ vectors instead of tens of ms with brute-force.
2. Native metadata filtering — let `scope_key` become a filter on one big collection rather than N separate indexes. Simplifies `rag_service._indexes` bookkeeping and cuts RAM use when many scopes are warm.
3. Drop-in replacement in LlamaIndex — swap `VectorStoreIndex(nodes)` for `VectorStoreIndex.from_vector_store(ChromaVectorStore(...))`. ~30 lines in `rag_service.py`.

**Open questions:**
- One collection with `scope_key` metadata, or one collection per frontend? Per-frontend gives natural multi-tenancy for when CBC runs N campaigns; single collection is simpler code.
- Migration from current `SimpleVectorStore` persist dirs — one-shot script that reads each scope's existing index and re-ingests into Chroma.
- Embedding re-compute not needed — we can read BGE-M3 vectors out of the old index and write them into Chroma directly.
- Backup story: Chroma stores SQLite + Parquet under the hood. Already volume-backed, so nothing new, but worth documenting in INSTALL.md.
- Qdrant (separate container, HNSW + better filtering + hybrid native) as the NEXT upgrade when CBC runs 500k+ vectors or multiple backend hosts.

**Prerequisite work:**
- Nothing — Sprint 9's BGE-M3 embeddings + hybrid retrieval already live comfortably in any vector store.
- Decision gate is measurement, not code readiness. Watch query latency + RAM as corpus grows; migrate when `SimpleVectorStore` hurts.

**Rejected alternatives (for context):**
- SQLite-vec: minimalism is its only selling point; gains over `SimpleVectorStore` for CBC are marginal and LlamaIndex integration is less mature.
- Qdrant today: overkill. Add the container dependency only when we genuinely outgrow Chroma embedded.

---

## LLM provider options: Ollama, LM Studio, API

**Captured:** 2026-04-18 (Sprint 3)
**Status:** planned → Sprint 3 (admin UI + config schema) and Sprint 6 (chat engine exercises all three); promoted via `/spec` on 2026-04-18. Spec landed in §4.7 + §5.1 (Tab 1 global + Tab 2 per-frontend override) + §4.9 + §8.3. Code: `llm_config_store.py` already supports all three provider types; `PerFrontendLLMPanel.tsx` exposes the override toggle in Sprint 4B.
**Candidate sprint:** 3 (LLM admin config UI) + 6 (chat engine actually uses it)
**Context:** SPEC §4.7 currently lists "LM Studio, Ollama (OpenAI-compatible API)". Both are local providers on `host.docker.internal`. The admin LLM tab should offer three distinct provider types: Ollama, LM Studio, and "API" (remote cloud providers — Anthropic, OpenAI, etc.) as separate, first-class options.

**Idea:** "la selección de llm incluir opciones ollama, lm studio y api." — admin's LLM configuration dropdown lets the user pick per slot (inference / summariser) between the two local runtimes and a remote cloud API, with whatever credentials / endpoint fields each option needs.

**Open questions:**
- Which cloud providers under "API"? Anthropic only, OpenAI only, both, or a generic "OpenAI-compatible endpoint" that also fits Groq / Together / Mistral?
- Where do API keys live? Env var at container start, admin-panel input (stored encrypted in config), or both?
- Can different slots use different providers (e.g. API for inference, local Ollama for summariser)? HRDD's LLM provider supports per-slot config, so yes in principle.
- Per-frontend LLM override (HRDD pattern) should still work for cloud API slots — confirm.
- Streaming: all three options must keep SSE streaming working end-to-end with the pull-inverse pattern.
- Cost tracking / rate limiting for remote API — in scope for v1.0 or defer?

**Prerequisite work:**
- Sprint 1 backend config already allows LM Studio / Ollama endpoints — schema will need an `api` provider block with `endpoint`, `api_key`, `model` fields
- Sprint 3 is building the LLM admin tab — easiest place to land this
- `llm_provider.py` (adapted from HRDD in Sprint 6) needs a third branch for remote API (auth headers, different error shapes)
- Security: API keys must not be committed or logged — extend secret-redaction pattern

---

## CBA sidepanel in chat — browse & download loaded agreements

**Captured:** 2026-04-18 (Sprint 2)
**Status:** **shipped** across Sprint 11 Phase A (sidepanel + downloads via pull-inverse) and Sprint 11 Phase B (inline `[filename, page/article]` citation pills with click-to-highlight, 2026-04-21). Gated per-frontend by `cba_sidepanel_enabled` + the separate `cba_citations_enabled` flag.
**Candidate sprint:** ~~6 (Chat Engine) or a new sprint between 6 and 8~~ — done in Sprint 11.
**Context:** Company buttons on CompanySelectPage originally showed inline country tags (e.g. `AU · US · DE · BR`). Daniel removed them: cluttered, and the information belongs somewhere more useful.

**Idea:** During chat, a side panel lists the CBAs loaded for the current company (for "Compare All" mode, all loaded CBAs filtered by comparison scope). Each entry shows country, language, document type, and a download button.

**Open questions:**
- Only company-scoped documents, or include frontend + global RAG too (subject to `rag_mode`)?
- Download the original file or a normalized text excerpt?
- Permission model — all users can download, or admin-only?
- Does download count as data egress we need to audit (logging + rate limit)?
- Does this replace, supplement, or sit alongside inline citations in chat responses?

**Prerequisite work already in place:**
- `country_tags` is still in the `Company` type + `companies.json` — Sprint 2 only removed the button display, not the data
- Sprint 5's RAG metadata (country, language, document_type) fits what the panel needs

---

<!-- Append new ideas above this line. Never delete; mark rejected instead. -->
