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
  wipeAndReindexAll,
} from '../api'
import type { GlobalRAGSettings } from '../api'
import { useT } from '../i18n'

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
  const { t } = useT()

  const reload = async () => {
    setError('')
    try {
      const s = await getRAGSettings()
      setSettings(s)
      setDraftChunk(s.chunk_size)
      setDraftEmbed(s.embedding_model)
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
    setBusy(true)
    setStatus(t('rag_pipeline_saving'))
    try {
      await updateRAGSettings({
        chunk_size: draftChunk !== settings?.chunk_size ? draftChunk : undefined,
        embedding_model: draftEmbed !== settings?.embedding_model ? draftEmbed : undefined,
      })
      await reload()
      setStatus(t('rag_pipeline_settings_saved'))
      setTimeout(() => setStatus(''), 5000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    } finally {
      setBusy(false)
    }
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

              {/* Save settings */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={saveSettings}
                  disabled={busy || !dirty}
                  className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90 disabled:opacity-40"
                >
                  {t('rag_pipeline_save_settings')}
                </button>
                {dirty && (
                  <span className="text-[11px] text-amber-800">
                    {t('rag_pipeline_save_requires_wipe')}
                  </span>
                )}
              </div>

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
                  {t('rag_pipeline_wipe_button')}
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
            </>
          )}
        </div>
      )}
    </section>
  )
}
