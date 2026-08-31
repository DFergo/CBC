// Sprint 9: global RAG pipeline knobs.
// Sprint 15 phase 3: chunk_size + embedding_model are now editable from
// the admin (slider + dropdown). Reranker model stays read-only — only one
// is pre-downloaded in the Docker image. Changing chunk_size OR embedding_
// model requires wiping the Chroma collection (dim change / bucketing
// change) and re-ingesting every scope. The "Wipe & Reindex All" button
// does that synchronously.
import { useEffect, useState } from 'react'
import {
  getRAGSettings,
  toggleContextualRetrieval,
  updateRAGSettings,
  updateRAGTuning,
  wipeAndReindexAll,
} from '../api'
import type { GlobalRAGSettings, RAGTuning } from '../api'
import { useT } from '../i18n'

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
const EMBEDDING_MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: 'BAAI/bge-m3', label: 'BAAI/bge-m3 (1024-dim, multilingual)' },
  { value: 'sentence-transformers/all-MiniLM-L6-v2', label: 'all-MiniLM-L6-v2 (384-dim, legacy)' },
]

export default function RAGPipelineSection() {
  const [settings, setSettings] = useState<GlobalRAGSettings | null>(null)
  // Draft values — what the slider / dropdown are currently showing. Synced
  // to `settings` on load; applied to backend on Save.
  const [draftChunk, setDraftChunk] = useState<number>(1024)
  const [draftEmbed, setDraftEmbed] = useState<string>('BAAI/bge-m3')
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
  // "Settings staged but NOT yet applied". Persists across the save action
  // itself — only cleared by a successful Wipe & Reindex. Tells the admin
  // that their chunk_size / embedder change is written to backend config but
  // the corpus is still indexed at the previous values.
  const [pendingReindex, setPendingReindex] = useState(false)
  // Sprint 18 Fase 4 — admin-tunable retrieval + watcher knobs. Synced from
  // settings.tuning on load; applied via PATCH /admin/api/v1/rag/tuning.
  const [tuningDraft, setTuningDraft] = useState<RAGTuning>(DEFAULT_TUNING)
  const [tuningSaving, setTuningSaving] = useState(false)
  const [tuningSaved, setTuningSaved] = useState('')
  const [tuningError, setTuningError] = useState('')
  const { t } = useT()

  const reload = async () => {
    setError('')
    try {
      const s = await getRAGSettings()
      setSettings(s)
      setDraftChunk(s.chunk_size)
      setDraftEmbed(s.embedding_model)
      if (s.tuning) setTuningDraft(s.tuning)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { reload() }, [])

  const dirty = !!settings && (
    draftChunk !== settings.chunk_size || draftEmbed !== settings.embedding_model
  )

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
        embedding_model: draftEmbed !== settings?.embedding_model ? draftEmbed : undefined,
      })
      await reload()
      // Backend says any of these changed → admin must wipe+reindex to apply.
      // Keep that banner visible until the wipe finishes successfully.
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
        // Wipe succeeded → the "pending apply" banner from a prior Save
        // is no longer relevant. Clear it.
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
              {/* Editable: embedding model */}
              <div className="border border-gray-200 rounded-lg p-4">
                <label className="block">
                  <div className="text-xs text-gray-500 mb-1">{t('rag_pipeline_embedder')}</div>
                  <select
                    value={draftEmbed}
                    onChange={e => setDraftEmbed(e.target.value)}
                    disabled={busy}
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:opacity-50"
                  >
                    {EMBEDDING_MODEL_OPTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </label>
                <p className="text-[11px] text-gray-500 mt-1.5">
                  {t('rag_pipeline_embedder_hint')}
                </p>
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

              {/* Read-only: reranker + strategy */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_reranker')}</div>
                  <code className="text-sm text-gray-800">
                    {settings.reranker_enabled ? settings.reranker_model : '—'}
                  </code>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_strategy')}</div>
                  <div className="text-sm text-gray-800">Hybrid BM25 + vector + cross-encoder rerank</div>
                </div>
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

              {/* Sprint 15 phase 3 fix — persistent "pending apply" banner.
                  After the admin saves a chunk_size / embedder change, the
                  value is in backend config but the index is still at the
                  OLD settings. Keep this prominent until Wipe & Reindex
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
                    </div>
                  </div>
                </div>
              )}

              {/* Wipe & Reindex All — destructive, red */}
              <div className="border border-red-300 bg-red-50/40 rounded-lg p-4">
                <div className="text-sm font-semibold text-red-800 mb-1">
                  {t('rag_pipeline_wipe_title')}
                </div>
                <p className="text-[12px] text-red-800 mb-3">
                  {t('rag_pipeline_wipe_description')}
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
