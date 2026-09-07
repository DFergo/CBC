// Sprint 9: global RAG pipeline knobs.
// Sprint 15 phase 3: chunk_size is editable from the admin (slider).
// Sprint 20: embedding + reranker model selection now goes through a
// provider picker (local baked-in HuggingFace, or a generic OpenAI-
// compatible API — no specific vendor like oMLX is baked in as its own
// option; the model list is auto-detected from whatever the configured
// endpoint serves) instead of a plain model dropdown. This used to be a
// separate "Embedding & reranker provider" section — folded back in here
// per Daniel's feedback ("no tiene sentido meter una sección nueva", the
// admin expects ONE place for the embedder, not two). Local model choice
// still round-trips through the pre-existing `update_runtime_rag_settings`
// / chunk_size dim-change machinery (see `saveEmbedding` below for why);
// non-local providers go through `embedding_config_store` + the blue-green
// `reindex_all_scopes_into_new_collection` swap, which also transparently
// covers "just changed chunk_size or local model, same collection" since it
// falls back to a normal in-place reindex when the target collection name
// doesn't change.
import { useEffect, useState } from 'react'
import {
  deleteChromaCollection,
  getEmbeddingConfig,
  getRAGSettings,
  listChromaCollections,
  reindexToNewProvider,
  saveEmbeddingConfig,
  toggleContextualRetrieval,
  updateRAGSettings,
  updateRAGTuning,
  wipeAndReindexAll,
} from '../api'
import type {
  ChromaCollectionInfo,
  EmbeddingConfig,
  EmbeddingConfigResponse,
  EmbeddingSlotConfig,
  GlobalRAGSettings,
  RAGTuning,
  RerankerSlotConfig,
} from '../api'
import { useT } from '../i18n'
import EmbeddingSlotEditor from '../components/rag/EmbeddingSlotEditor'

// Sprint 18 Fase 4 — bounds for the tuning sliders. Mirror the backend's
// _TUNING_RANGES in rag_service.py; UI re-validation is just a UX nicety,
// the backend re-validates regardless.
const TUNING_BOUNDS: Record<keyof RAGTuning, { min: number; max: number; step: number }> = {
  top_k_floor: { min: 1, max: 40, step: 1 },
  top_k_ceil: { min: 5, max: 100, step: 5 },
  top_k_per_doc: { min: 1, max: 10, step: 1 },
  tables_top_k_floor: { min: 1, max: 20, step: 1 },
  tables_top_k_ceil_single: { min: 1, max: 30, step: 1 },
  tables_top_k_ceil_compare_all: { min: 1, max: 50, step: 1 },
  watcher_debounce_seconds: { min: 1, max: 600, step: 5 },
  watcher_max_hold_seconds: { min: 10, max: 3600, step: 30 },
  watcher_lock_replan_seconds: { min: 5, max: 600, step: 5 },
}

const DEFAULT_TUNING: RAGTuning = {
  top_k_floor: 5,
  top_k_ceil: 40,
  top_k_per_doc: 2,
  tables_top_k_floor: 2,
  tables_top_k_ceil_single: 6,
  tables_top_k_ceil_compare_all: 12,
  watcher_debounce_seconds: 30,
  watcher_max_hold_seconds: 300,
  watcher_lock_replan_seconds: 30,
}

const CHUNK_SIZE_OPTIONS = [512, 1024, 1536, 2048] as const
const LOCAL_EMBEDDING_MODELS = ['BAAI/bge-m3', 'sentence-transformers/all-MiniLM-L6-v2']
const LOCAL_RERANKER_MODELS = ['BAAI/bge-reranker-v2-m3']

export default function RAGPipelineSection() {
  const [settings, setSettings] = useState<GlobalRAGSettings | null>(null)
  // Draft value — what the slider is currently showing. Synced to
  // `settings` on load; applied to backend on Save. (embedding_model moved
  // to the provider-based flow below, Sprint 20.)
  const [draftChunk, setDraftChunk] = useState<number>(1024)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  // HRDD-style inline feedback near the Save button. `saving` controls the
  // button label ("Saving…"); `saveSuccess` is a green pill that appears for
  // 3 s after a successful save. Separate from the header `status` so it's
  // visible right where the admin clicked.
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState('')
  // "Settings staged but NOT yet applied" — covers BOTH chunk_size changes
  // (legacy flow) AND embedding/reranker provider changes (Sprint 20 flow).
  // Either one clears this via the single "Reindex" button below, which
  // always calls the blue-green endpoint (safe no-op-collection-swap when
  // nothing about the embedder actually changed).
  const [pendingReindex, setPendingReindex] = useState(false)
  // Sprint 18 Fase 4 — admin-tunable retrieval + watcher knobs. Synced from
  // settings.tuning on load; applied via PATCH /admin/api/v1/rag/tuning.
  const [tuningDraft, setTuningDraft] = useState<RAGTuning>(DEFAULT_TUNING)
  const [tuningSaving, setTuningSaving] = useState(false)
  const [tuningSaved, setTuningSaved] = useState('')
  const [tuningError, setTuningError] = useState('')
  const { t } = useT()

  // --- Sprint 20 — embedding / reranker provider state ---
  const [embedRemote, setEmbedRemote] = useState<EmbeddingConfigResponse | null>(null)
  const [embedDraft, setEmbedDraft] = useState<EmbeddingConfig | null>(null)
  const [collections, setCollections] = useState<ChromaCollectionInfo[]>([])
  const [embedSaving, setEmbedSaving] = useState(false)
  const [embedSaveMsg, setEmbedSaveMsg] = useState('')
  const [embedError, setEmbedError] = useState('')
  const [reindexing, setReindexing] = useState(false)
  const [reindexMsg, setReindexMsg] = useState('')

  const reload = async () => {
    setError('')
    try {
      const s = await getRAGSettings()
      setSettings(s)
      setDraftChunk(s.chunk_size)
      if (s.tuning) setTuningDraft(s.tuning)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
    try {
      const cfg = await getEmbeddingConfig()
      setEmbedRemote(cfg)
      setEmbedDraft({ embedding: cfg.embedding, reranker: cfg.reranker })
      if (cfg.pending_reindex) setPendingReindex(true)
      const cols = await listChromaCollections()
      setCollections(cols.collections)
    } catch (e) {
      setEmbedError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { reload() }, [])

  const dirty = !!settings && draftChunk !== settings.chunk_size

  const embedDirty = !!embedRemote && !!embedDraft && JSON.stringify(embedDraft) !== JSON.stringify({
    embedding: embedRemote.embedding, reranker: embedRemote.reranker,
  })

  const patchEmbedding = (patch: Partial<EmbeddingSlotConfig>) => {
    setEmbedDraft(d => d && ({ ...d, embedding: { ...d.embedding, ...patch } as EmbeddingSlotConfig }))
  }
  const patchReranker = (patch: Partial<RerankerSlotConfig>) => {
    setEmbedDraft(d => d && ({ ...d, reranker: { ...d.reranker, ...patch } as RerankerSlotConfig }))
  }

  const handleToggle = async (next: boolean) => {
    if (!settings) return
    const warn = next
      ? t('rag_pipeline_contextual_enable_confirm')
      : t('rag_pipeline_contextual_disable_confirm')
    if (!confirm(warn)) return

    setBusy(true)
    setStatus(next ? t('rag_pipeline_enabling') : t('rag_pipeline_disabling'))
    setError('')
    try {
      const result = await toggleContextualRetrieval(next)
      setStatus(
        result.changed
          ? t('rag_pipeline_reindexed', { count: result.scopes_reindexed })
          : t('rag_pipeline_already_in_state'),
      )
      await reload()
      setTimeout(() => setStatus(''), 6000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  const saveSettings = async () => {
    setError('')
    setSaveSuccess('')
    setSaving(true)
    setBusy(true)
    try {
      const res = await updateRAGSettings({
        chunk_size: draftChunk !== settings?.chunk_size ? draftChunk : undefined,
      })
      await reload()
      if (res.requires_wipe_and_reindex) {
        setPendingReindex(true)
      }
      setSaveSuccess(t('generic_saved'))
      setTimeout(() => setSaveSuccess(''), 3000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
      setBusy(false)
    }
  }

  // Sprint 20 — single save button for both embedding + reranker slots.
  // When the embedding slot's provider is "local", the actual model value
  // is still owned by `backend_config.rag_embedding_model` (see
  // `rag_service._resolve_active_embedding_slot` — deliberate single-
  // source-of-truth decision so the local zero-config path never gets a
  // second place to configure the same value). We route that leg through
  // the pre-existing `updateRAGSettings` call FIRST, then always persist
  // `embedding_config_store` too (even for local) so its `provider` field
  // stays in sync — otherwise switching an admin from "api" back to
  // "local" here would update the model but leave the store still pointed
  // at "api", and `_resolve_active_embedding_slot` would keep routing
  // queries through the old remote provider.
  const saveEmbedding = async () => {
    if (!embedDraft) return
    setEmbedSaving(true)
    setEmbedError('')
    setEmbedSaveMsg('')
    try {
      if (embedDraft.embedding.provider === 'local') {
        const r = await updateRAGSettings({ embedding_model: embedDraft.embedding.model })
        if (r.requires_wipe_and_reindex) setPendingReindex(true)
      }
      const res = await saveEmbeddingConfig(embedDraft)
      setEmbedRemote(res)
      setEmbedDraft({ embedding: res.embedding, reranker: res.reranker })
      if (res.pending_reindex) setPendingReindex(true)
      setEmbedSaveMsg('Saved')
      setTimeout(() => setEmbedSaveMsg(''), 3000)
      await reload()
    } catch (e) {
      setEmbedError(e instanceof Error ? e.message : String(e))
    } finally {
      setEmbedSaving(false)
    }
  }

  const tuningDirty = !!settings?.tuning && (Object.keys(tuningDraft) as (keyof RAGTuning)[]).some(
    k => tuningDraft[k] !== settings.tuning?.[k],
  )

  const saveTuning = async () => {
    if (!settings?.tuning) return
    setTuningError('')
    setTuningSaved('')
    setTuningSaving(true)
    try {
      const patch: Partial<RAGTuning> = {}
      ;(Object.keys(tuningDraft) as (keyof RAGTuning)[]).forEach(k => {
        if (tuningDraft[k] !== settings.tuning?.[k]) patch[k] = tuningDraft[k]
      })
      const res = await updateRAGTuning(patch)
      setTuningDraft(res.applied)
      setTuningSaved(
        res.changed.length
          ? t('rag_tuning_saved').replace('{n}', String(res.changed.length))
          : t('rag_tuning_no_changes'),
      )
      await reload()
      setTimeout(() => setTuningSaved(''), 4000)
    } catch (e) {
      setTuningError(e instanceof Error ? e.message : String(e))
    } finally {
      setTuningSaving(false)
    }
  }

  const resetTuning = () => {
    setTuningDraft(DEFAULT_TUNING)
  }

  // Sprint 20 — this is now THE reindex button for chunk_size AND embedding/
  // reranker provider changes. `reindex_all_scopes_into_new_collection`
  // already handles both cases correctly: if the target (provider, model)
  // resolves to the SAME collection name that's already active (e.g. only
  // chunk_size changed, or the admin re-saved without changing provider),
  // it transparently falls back to a normal in-place reindex of the active
  // collection — no blue-green dance, no client.reset(), just fresh chunks.
  // If the target is a genuinely different collection (provider/model
  // swap), it builds the new one with zero downtime and swaps atomically.
  const doReindex = async () => {
    if (!confirm(
      'Reindex every scope (global + every frontend + every company) with the currently saved chunk size / ' +
      'embedding settings. If the embedding provider or model changed, this builds a brand-new vector ' +
      'collection in the background — chat keeps using the OLD collection until the rebuild finishes ' +
      'successfully, then queries switch over atomically. Can take minutes to hours depending on corpus size. ' +
      'Continue?',
    )) return
    setReindexing(true)
    setReindexMsg('Reindexing…')
    setError('')
    setEmbedError('')
    try {
      const r = await reindexToNewProvider()
      setReindexMsg(
        r.swapped
          ? `Swapped to ${r.collection} (${r.scopes_reindexed} scopes reindexed). Old collection ${r.old_collection} left on disk — purge it below once you're confident.`
          : `Reindexed ${r.scopes_reindexed} scopes (same collection).`,
      )
      setPendingReindex(false)
      await reload()
    } catch (e) {
      setEmbedError(e instanceof Error ? e.message : String(e))
      setReindexMsg('')
    } finally {
      setReindexing(false)
    }
  }

  const purgeCollection = async (name: string) => {
    if (!confirm(`Permanently delete Chroma collection "${name}"? This cannot be undone.`)) return
    setEmbedError('')
    try {
      await deleteChromaCollection(name)
      await reload()
    } catch (e) {
      setEmbedError(e instanceof Error ? e.message : String(e))
    }
  }

  // Full-wipe fallback — kept for corruption recovery / the rare case where
  // an admin wants to nuke every collection (including old provider
  // snapshots) and rebuild from scratch. Routine chunk_size / embedding
  // provider changes should use "Reindex" above instead, which is
  // non-destructive and reversible.
  const wipeAndReindex = async () => {
    const ok = confirm(t('rag_pipeline_wipe_confirm'))
    if (!ok) return
    setError('')
    setBusy(true)
    setStatus(t('rag_pipeline_wiping'))
    try {
      const r = await wipeAndReindexAll()
      const errs = r.stats.filter(s => s.error)
      if (errs.length) {
        setError(`${r.scopes_reindexed - errs.length} / ${r.scopes_reindexed} scopes ok; ${errs.length} failed (check backend logs).`)
      } else {
        setStatus(t('rag_pipeline_wipe_done', { count: r.scopes_reindexed }))
        setTimeout(() => setStatus(''), 8000)
        setPendingReindex(false)
      }
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between text-left"
        aria-expanded={expanded}
      >
        <div>
          <h3 className="text-lg font-semibold text-gray-800">{t('rag_pipeline_heading')}</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            {t('rag_pipeline_description')}
            {status && <span className="ml-2 text-green-700">{status}</span>}
          </p>
        </div>
        <span className={`text-gray-400 transition-transform ml-3 ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
      </button>

      {expanded && (
        <div className="mt-5 space-y-4">
          {error && <p className="text-uni-red text-sm">{error}</p>}
          {!settings && !error && <p className="text-sm text-gray-400">{t('generic_loading')}</p>}

          {settings && (
            <>
              {/* Sprint 20 — embedding + reranker, provider-first. Local
                  keeps the pre-Sprint-20 in-container HuggingFace weights;
                  "api" routes to any remote OpenAI-compatible server instead
                  (self-hosted or commercial — nothing vendor-specific baked in). */}
              {embedDraft && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <EmbeddingSlotEditor
                      kind="embedding"
                      label={t('rag_pipeline_embedder')}
                      hint={t('rag_pipeline_embedder_hint')}
                      slot={embedDraft.embedding}
                      onChange={patchEmbedding}
                      localModelOptions={LOCAL_EMBEDDING_MODELS}
                      disabled={embedSaving || reindexing}
                    />
                    {embedDraft.embedding.provider === 'local' && (
                      <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5 mt-1.5">
                        Se ejecuta dentro del contenedor sin aceleración GPU/Metal — la opción más lenta.
                        Si tienes un servidor de inferencia propio (self-hosted, p.ej. oMLX o vLLM) o una
                        API comercial, elige "API" arriba para acelerar embeddings y reranking.
                      </p>
                    )}
                  </div>
                  <div>
                    <EmbeddingSlotEditor
                      kind="reranker"
                      label={t('rag_pipeline_reranker')}
                      hint="Rescores retrieved candidates before they reach the prompt. Changing this takes effect on the next query — no reindex needed."
                      slot={embedDraft.reranker}
                      onChange={patchReranker}
                      localModelOptions={LOCAL_RERANKER_MODELS}
                      disabled={embedSaving || reindexing}
                    />
                    {embedDraft.reranker.provider === 'local' && (
                      <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5 mt-1.5">
                        Se ejecuta dentro del contenedor — la opción más lenta. "Enabled"/"Top N" no
                        aplican en local (se controlan por configuración de despliegue); cambia de
                        proveedor arriba para poder ajustarlos desde aquí.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {embedError && <p className="text-uni-red text-sm">{embedError}</p>}

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={saveEmbedding}
                  disabled={embedSaving || reindexing || !embedDirty}
                  className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90 disabled:opacity-40"
                >
                  {embedSaving ? t('generic_saving') : t('rag_pipeline_save_settings')}
                </button>
                {embedSaveMsg && <span className="text-xs text-green-700 font-medium">✓ {embedSaveMsg}</span>}
                {embedDirty && !embedSaving && (
                  <span className="text-[11px] text-amber-800">{t('rag_pipeline_save_requires_wipe')}</span>
                )}
              </div>

              {/* Editable: chunk size */}
              <div className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-baseline justify-between mb-1">
                  <div className="text-xs text-gray-500">{t('rag_pipeline_chunk_size')}</div>
                  <div className="text-sm font-mono text-gray-800">{draftChunk}{' tokens'}</div>
                </div>
                <input
                  type="range"
                  min={CHUNK_SIZE_OPTIONS[0]}
                  max={CHUNK_SIZE_OPTIONS[CHUNK_SIZE_OPTIONS.length - 1]}
                  step={512}
                  value={draftChunk}
                  disabled={busy}
                  onChange={e => setDraftChunk(parseInt(e.target.value, 10))}
                  className="w-full disabled:opacity-50"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-1 px-0.5">
                  {CHUNK_SIZE_OPTIONS.map(v => <span key={v}>{v}</span>)}
                </div>
                <p className="text-[11px] text-gray-500 mt-1.5">
                  {t('rag_pipeline_chunk_size_hint')}
                </p>
              </div>

              {/* Read-only: retrieval strategy */}
              <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_strategy')}</div>
                <div className="text-sm text-gray-800">Hybrid BM25 + vector + cross-encoder rerank</div>
              </div>

              {/* Save settings — HRDD-style inline feedback right next to
                  the button (saving state + green saved pill). */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={saveSettings}
                  disabled={busy || !dirty}
                  className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90 disabled:opacity-40"
                >
                  {saving ? t('generic_saving') : t('rag_pipeline_save_settings')}
                </button>
                {saveSuccess && (
                  <span className="text-xs text-green-700 font-medium">✓ {saveSuccess}</span>
                )}
                {dirty && !saving && (
                  <span className="text-[11px] text-amber-800">
                    {t('rag_pipeline_save_requires_wipe')}
                  </span>
                )}
              </div>

              {/* Sprint 15 phase 3 fix / Sprint 20 — persistent "pending
                  apply" banner covering chunk_size AND embedding/reranker
                  provider changes. Stays up until the Reindex button below
                  succeeds, so the admin can't think the change is live when
                  it isn't. */}
              {pendingReindex && (
                <div className="border-2 border-amber-400 bg-amber-50 rounded-lg p-4">
                  <div className="flex gap-3">
                    <span className="text-2xl">⚠️</span>
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-amber-900 mb-1">
                        {t('rag_pipeline_pending_apply_title')}
                      </div>
                      <p className="text-[12px] text-amber-900">
                        {t('rag_pipeline_pending_apply_body')}
                      </p>
                      <button
                        type="button"
                        onClick={doReindex}
                        disabled={reindexing}
                        className="mt-2 text-sm bg-amber-600 text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-40"
                      >
                        {reindexing ? 'Reindexing…' : 'Reindex'}
                      </button>
                      {reindexMsg && <p className="text-[12px] text-amber-900 mt-2">{reindexMsg}</p>}
                    </div>
                  </div>
                </div>
              )}

              {/* Sprint 20 — collections management. Old provider snapshots
                  from a previous blue-green swap stay on disk until purged
                  manually here. */}
              <details className="border border-gray-200 rounded-md">
                <summary className="cursor-pointer list-none select-none px-3 py-2 bg-gray-50 hover:bg-gray-100 rounded-t-md flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-800">Collections ({collections.length})</span>
                  <span className="text-xs text-gray-500">Old provider snapshots stay on disk until purged manually</span>
                </summary>
                <div className="p-3 space-y-2">
                  {collections.length === 0 && <p className="text-xs text-gray-400">No collections found.</p>}
                  {collections.map(c => (
                    <div key={c.name} className="flex items-center justify-between border border-gray-100 rounded px-2 py-1.5">
                      <div className="flex items-center gap-2">
                        <code className="text-xs">{c.name}</code>
                        {c.is_active_chunks && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">active chunks</span>}
                        {c.is_active_tables && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">active tables</span>}
                        <span className="text-[11px] text-gray-400">{c.chunk_count} items</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => purgeCollection(c.name)}
                        disabled={c.is_active_chunks || c.is_active_tables}
                        className="text-[11px] text-uni-red border border-red-200 rounded px-2 py-0.5 disabled:opacity-30 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              </details>

              {/* Wipe & Reindex All — destructive, full nuke including old
                  provider snapshots. Danger-zone fallback, not the routine
                  path (use "Reindex" above for that). */}
              <div className="border border-red-300 bg-red-50/40 rounded-lg p-4">
                <div className="text-sm font-semibold text-red-800 mb-1">
                  {t('rag_pipeline_wipe_title')}
                </div>
                <p className="text-[12px] text-red-800 mb-3">
                  {t('rag_pipeline_wipe_description')}
                  {' '}Also deletes every OTHER Chroma collection on disk, including old provider snapshots
                  kept for rollback — prefer "Reindex" above for routine chunk_size / provider changes.
                </p>
                <button
                  type="button"
                  onClick={wipeAndReindex}
                  disabled={busy}
                  className="text-sm bg-uni-red text-white rounded-lg px-3 py-2 hover:opacity-90 disabled:opacity-40"
                >
                  {busy && status.includes('Wip') ? t('rag_pipeline_wiping') : t('rag_pipeline_wipe_button')}
                </button>
              </div>

              {/* Contextual Retrieval toggle — unchanged from Sprint 9 */}
              <div className="border border-amber-200 bg-amber-50/40 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="text-sm font-semibold text-gray-800">{t('rag_pipeline_contextual_title')}</div>
                    <p className="text-xs text-gray-600 mt-0.5">
                      {t('rag_pipeline_contextual_description')}
                    </p>
                  </div>
                  <label className="flex items-center gap-2 ml-3">
                    <span className="text-xs text-gray-600">
                      {settings.contextual_enabled ? t('rag_pipeline_contextual_on') : t('rag_pipeline_contextual_off')}
                    </span>
                    <input
                      type="checkbox"
                      checked={settings.contextual_enabled}
                      disabled={busy}
                      onChange={e => handleToggle(e.target.checked)}
                      className="rounded border-gray-300 disabled:opacity-50"
                    />
                  </label>
                </div>
                <p className="text-[11px] text-amber-800">
                  {t('rag_pipeline_contextual_warning')}
                </p>
              </div>

              {/* Sprint 18 Fase 4 — Tuning avanzado (colapsado por defecto). */}
              <details className="border border-gray-200 rounded-md">
                <summary className="cursor-pointer list-none select-none px-3 py-2 bg-gray-50 hover:bg-gray-100 rounded-t-md flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-400 group-open:rotate-90 transition-transform">▸</span>
                    <span className="text-sm font-semibold text-gray-800">{t('rag_tuning_heading')}</span>
                  </div>
                  <span className="text-xs text-gray-500">{t('rag_tuning_subtitle')}</span>
                </summary>
                <div className="p-3 space-y-4">
                  <p className="text-xs text-gray-600">{t('rag_tuning_description')}</p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {(Object.keys(TUNING_BOUNDS) as (keyof RAGTuning)[]).map(key => {
                      const bounds = TUNING_BOUNDS[key]
                      const value = tuningDraft[key]
                      const labelKey = `rag_tuning_${key}` as Parameters<typeof t>[0]
                      const hintKey = `rag_tuning_${key}_hint` as Parameters<typeof t>[0]
                      return (
                        <div key={key} className="space-y-1">
                          <div className="flex items-baseline justify-between">
                            <label className="text-xs font-medium text-gray-700">{t(labelKey)}</label>
                            <span className="text-xs font-mono text-gray-800">{value}</span>
                          </div>
                          <input
                            type="range"
                            min={bounds.min}
                            max={bounds.max}
                            step={bounds.step}
                            value={value}
                            onChange={e => setTuningDraft({ ...tuningDraft, [key]: parseInt(e.target.value, 10) })}
                            disabled={tuningSaving}
                            className="w-full"
                          />
                          <p className="text-[10px] text-gray-500">{t(hintKey)}</p>
                        </div>
                      )
                    })}
                  </div>

                  {tuningError && (
                    <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">
                      {tuningError}
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2">
                    {tuningSaved && (
                      <span className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5">
                        {tuningSaved}
                      </span>
                    )}
                    <button
                      onClick={resetTuning}
                      disabled={tuningSaving}
                      className="px-3 py-1.5 text-xs border border-gray-300 text-gray-700 rounded disabled:opacity-50 hover:bg-gray-50"
                    >
                      {t('rag_tuning_reset')}
                    </button>
                    <button
                      onClick={saveTuning}
                      disabled={tuningSaving || !tuningDirty}
                      className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded disabled:opacity-50"
                    >
                      {tuningSaving ? t('generic_saving') : t('rag_tuning_save')}
                    </button>
                  </div>
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </section>
  )
}
