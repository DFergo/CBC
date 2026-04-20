// Sprint 9: global RAG pipeline knobs. Read-only info on embedder + reranker
// (rebuild the image to swap those), plus a runtime toggle for Contextual
// Retrieval that triggers a full reindex of every scope on change.
import { useEffect, useState } from 'react'
import { getRAGSettings, toggleContextualRetrieval } from '../api'
import type { GlobalRAGSettings } from '../api'

export default function RAGPipelineSection() {
  const [settings, setSettings] = useState<GlobalRAGSettings | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

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
    const verb = next ? 'Activar' : 'Desactivar'
    const warn = next
      ? 'Activar Contextual Retrieval reindexa TODO el corpus y llama al LLM summariser una vez por chunk. En un corpus grande esto puede tardar horas y durante ese tiempo las consultas devolverán resultados degradados. ¿Continuar?'
      : 'Desactivar Contextual Retrieval reindexa todo el corpus sin la línea de contexto prepuesta. Va rápido, pero las consultas durante el reindex se degradan. ¿Continuar?'
    if (!confirm(warn)) return

    setBusy(true)
    setStatus(`${verb}ando y reindexando…`)
    setError('')
    try {
      const result = await toggleContextualRetrieval(next)
      setStatus(
        result.changed
          ? `Reindexados ${result.scopes_reindexed} scopes.`
          : 'Ya estaba en ese estado.',
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
          <h3 className="text-lg font-semibold text-gray-800">RAG pipeline</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            Embedder, reranker, y Contextual Retrieval. Aplica a todos los scopes.
            {status && <span className="ml-2 text-green-700">{status}</span>}
          </p>
        </div>
        <span className={`text-gray-400 transition-transform ml-3 ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
      </button>

      {expanded && (
        <div className="mt-5 space-y-4">
          {error && <p className="text-uni-red text-sm">{error}</p>}
          {!settings && !error && <p className="text-sm text-gray-400">Cargando…</p>}

          {settings && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">Embedder</div>
                  <code className="text-sm text-gray-800">{settings.embedding_model}</code>
                  <p className="text-[11px] text-gray-500 mt-1">
                    Cambiar este modelo requiere editar <code>deployment_backend.json</code> y
                    reconstruir la imagen Docker (los pesos se pre-descargan).
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">Reranker</div>
                  <code className="text-sm text-gray-800">
                    {settings.reranker_enabled ? settings.reranker_model : 'disabled'}
                  </code>
                  <p className="text-[11px] text-gray-500 mt-1">
                    Se fetchean {settings.reranker_fetch_k} candidatos (BM25 + dense), se rerankean
                    a {settings.reranker_top_n}.
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">Chunk size</div>
                  <div className="text-sm text-gray-800">{settings.chunk_size} tokens</div>
                </div>
                <div className="border border-gray-200 rounded-lg p-3 bg-gray-50/60">
                  <div className="text-xs text-gray-500 mb-0.5">Retrieval estrategia</div>
                  <div className="text-sm text-gray-800">Hybrid BM25 + vector + cross-encoder rerank</div>
                </div>
              </div>

              <div className="border border-amber-200 bg-amber-50/40 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="text-sm font-semibold text-gray-800">Contextual Retrieval</div>
                    <p className="text-xs text-gray-600 mt-0.5">
                      Anthropic (2024): antes de embebir cada chunk, el summariser LLM genera una
                      línea de contexto que lo sitúa en el documento. Mejora recall en documentos
                      con muchas tablas / referencias cruzadas.
                    </p>
                  </div>
                  <label className="flex items-center gap-2 ml-3">
                    <span className="text-xs text-gray-600">
                      {settings.contextual_enabled ? 'activo' : 'desactivado'}
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
                  ⚠ Activar/desactivar reindexa TODO el corpus. Con CR activo, cada chunk gasta una
                  llamada al summariser → minutos u horas según volumen. Durante el reindex las
                  consultas del chat devuelven resultados degradados.
                </p>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
