// Sprint 9: global RAG pipeline knobs. Read-only info on embedder + reranker
// (rebuild the image to swap those), plus a runtime toggle for Contextual
// Retrieval that triggers a full reindex of every scope on change.
import { useEffect, useState } from 'react'
import { getRAGSettings, toggleContextualRetrieval } from '../api'
import type { GlobalRAGSettings } from '../api'
import { useT } from '../i18n'

export default function RAGPipelineSection() {
  const [settings, setSettings] = useState<GlobalRAGSettings | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

  const reload = async () => {
    setError('')
    try {
      setSettings(await getRAGSettings())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { reload() }, [])

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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_embedder')}</div>
                  <code className="text-sm text-gray-800">{settings.embedding_model}</code>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_reranker')}</div>
                  <code className="text-sm text-gray-800">
                    {settings.reranker_enabled ? settings.reranker_model : '—'}
                  </code>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_chunk_size')}</div>
                  <div className="text-sm text-gray-800">{settings.chunk_size}</div>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">{t('rag_pipeline_strategy')}</div>
                  <div className="text-sm text-gray-800">Hybrid BM25 + vector + cross-encoder rerank</div>
                </div>
              </div>

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
