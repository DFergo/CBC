// Tier-aware: omit both props for global, pass frontendId for frontend-level,
// pass frontendId+companySlug for company-level. Preview resolution (Sprint 4B)
// shows the stack of tiers that would feed a chat session.
import { useEffect, useRef, useState } from 'react'
import {
  listRAG, uploadRAG, deleteRAG, getRAGStats, reindexRAG,
  previewRAGResolution,
  getFrontendRAGSettings, saveFrontendRAGSettings,
  updateCompany,
} from '../api'
import type { RAGDocument, RAGStats, RAGResolutionResponse, Company } from '../api'

interface Props {
  frontendId?: string
  companySlug?: string
  // Required when companySlug is set — drives the "Combine RAG" subsection at
  // company tier without RAGSection having to refetch the company itself.
  company?: Company
  onCompanyChanged?: () => void
}

export default function RAGSection({ frontendId, companySlug, company, onCompanyChanged }: Props) {
  const [docs, setDocs] = useState<RAGDocument[]>([])
  const [stats, setStats] = useState<RAGStats | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<RAGResolutionResponse | null>(null)
  const [combineGlobalAtFrontend, setCombineGlobalAtFrontend] = useState(true)
  const [combineSaving, setCombineSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const tierLabel = companySlug ? 'company' : frontendId ? 'frontend' : 'global'
  const showFrontendCombine = tierLabel === 'frontend'
  const showCompanyCombine = tierLabel === 'company' && !!company

  const refresh = async () => {
    try {
      const [{ documents }, s] = await Promise.all([
        listRAG(frontendId, companySlug),
        getRAGStats(frontendId, companySlug),
      ])
      setDocs(documents)
      setStats(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    setPreview(null)
    refresh()
    if (showFrontendCombine && frontendId) {
      getFrontendRAGSettings(frontendId)
        .then(r => setCombineGlobalAtFrontend(r.settings.combine_global_rag))
        .catch(e => setError(e instanceof Error ? e.message : String(e)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId, companySlug])

  const setFrontendCombineGlobal = async (next: boolean) => {
    if (!frontendId) return
    const previous = combineGlobalAtFrontend
    setCombineGlobalAtFrontend(next)
    setCombineSaving(true)
    setError('')
    try {
      await saveFrontendRAGSettings(frontendId, { combine_global_rag: next })
    } catch (e) {
      setCombineGlobalAtFrontend(previous)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCombineSaving(false)
    }
  }

  const setCompanyCombine = async (patch: Partial<Pick<Company, 'combine_frontend_rag' | 'combine_global_rag'>>) => {
    if (!frontendId || !companySlug) return
    setCombineSaving(true)
    setError('')
    try {
      await updateCompany(frontendId, companySlug, patch)
      onCompanyChanged?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCombineSaving(false)
    }
  }

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setError('')
    setBusy(true)
    try {
      await uploadRAG(f, frontendId, companySlug)
      if (fileRef.current) fileRef.current.value = ''
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (name: string) => {
    setError('')
    setBusy(true)
    try {
      await deleteRAG(name, frontendId, companySlug)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const onReindex = async () => {
    setError('')
    setBusy(true)
    try {
      const s = await reindexRAG(frontendId, companySlug)
      setStats(s)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const runPreview = async () => {
    if (!frontendId) return
    setError('')
    try {
      const r = await previewRAGResolution(frontendId, companySlug)
      setPreview(r)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const fmtSize = (n: number) => {
    if (n < 1024) return `${n} B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
    return `${(n / 1024 / 1024).toFixed(1)} MB`
  }

  const heading = tierLabel === 'global'
    ? 'Global RAG documents'
    : tierLabel === 'frontend'
    ? `Frontend RAG — ${frontendId}`
    : `Company RAG — ${frontendId} / ${companySlug}`

  const description = tierLabel === 'global'
    ? 'Cross-sector reference documents (e.g. negotiation analysis). Pulled in by any company that has the Global checkbox ticked under Combine RAG.'
    : tierLabel === 'frontend'
    ? 'Sector-wide documents. Companies pull these in when they have the Frontend checkbox ticked under Combine RAG. Compare All sessions always include them.'
    : 'Company-specific CBAs and policies. Always loaded for this company\'s chat sessions.'

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">{heading}</h3>
      <p className="text-sm text-gray-500 mb-3">{description}</p>

      {(showFrontendCombine || showCompanyCombine) && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-4">
          <div className="flex items-center justify-between mb-1">
            <h4 className="text-sm font-semibold text-gray-700">Combine RAG</h4>
            {combineSaving && <span className="text-xs text-gray-500">saving…</span>}
          </div>
          <p className="text-[11px] text-gray-500 mb-2">
            {showFrontendCombine
              ? 'Higher-tier RAG to include for this frontend\'s chat sessions. Uncheck Global to keep this frontend\'s sessions sealed off from the cross-sector documents.'
              : 'Higher-tier RAG to include for this company\'s chat sessions. Uncheck either tier to exclude its documents from this company\'s resolution.'}
          </p>
          <div className="flex flex-wrap gap-4 pl-1">
            {showCompanyCombine && (
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!company?.combine_frontend_rag}
                  disabled={combineSaving}
                  onChange={e => setCompanyCombine({ combine_frontend_rag: e.target.checked })}
                  className="rounded border-gray-300"
                />
                <span className="text-gray-700">Frontend</span>
              </label>
            )}
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={showCompanyCombine ? !!company?.combine_global_rag : combineGlobalAtFrontend}
                disabled={combineSaving}
                onChange={e => {
                  if (showCompanyCombine) setCompanyCombine({ combine_global_rag: e.target.checked })
                  else setFrontendCombineGlobal(e.target.checked)
                }}
                className="rounded border-gray-300"
              />
              <span className="text-gray-700">Global</span>
            </label>
          </div>
        </div>
      )}

      {stats && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 mb-4">
          <strong>{stats.document_count}</strong> documents, total {fmtSize(stats.total_size_bytes)}. {stats.note}
        </div>
      )}

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="flex gap-3 mb-4 flex-wrap items-center">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt,.md"
          onChange={onUpload}
          disabled={busy}
          className="text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
        />
        <button onClick={onReindex} disabled={busy} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50 disabled:opacity-50">
          Reindex
        </button>
        {frontendId && (
          <button onClick={runPreview} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">
            Preview resolution
          </button>
        )}
      </div>

      {preview && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs mb-4">
          <div className="mb-2">
            <strong>Effective stack</strong> for {companySlug ? `${frontendId} / ${companySlug}` : `frontend ${frontendId}`}:
            {preview.frontend_standalone && <span className="ml-2 text-gray-600">(standalone — global excluded)</span>}
          </div>
          {preview.paths.length === 0 ? (
            <p className="text-gray-500">Empty — no tiers resolved for this context.</p>
          ) : (
            <ul className="space-y-1">
              {preview.paths.map((p, i) => (
                <li key={i}>
                  <code className="text-blue-800">{p.tier}</code>
                  {p.scope_key && <span className="text-gray-500"> · {p.scope_key}</span>}
                  <span className="text-gray-600"> · {p.doc_count} docs</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-gray-500 mt-2">Total: {preview.total_docs} documents.</p>
        </div>
      )}

      <ul className="border border-gray-200 rounded-lg divide-y divide-gray-200">
        {docs.length === 0 && <li className="px-3 py-2 text-sm text-gray-400">No {tierLabel}-level documents.</li>}
        {docs.map(d => (
          <li key={d.name} className="flex items-center justify-between px-3 py-2 text-sm">
            <div>
              <span className="font-medium text-gray-800">{d.name}</span>
              <span className="ml-2 text-xs text-gray-400">{fmtSize(d.size)}</span>
            </div>
            <button onClick={() => onDelete(d.name)} disabled={busy} className="text-xs text-uni-red hover:underline disabled:opacity-50">
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
