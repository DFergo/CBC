// Tier-aware: omit both props for global, pass frontendId for frontend-level,
// pass frontendId+companySlug for company-level. Preview resolution (Sprint 4B)
// shows the stack of tiers that would feed a chat session.
import { useEffect, useRef, useState } from 'react'
import {
  listRAG, uploadRAG, deleteRAG, getRAGStats, reindexRAG,
  reindexAllRAG, reindexFrontendCascade,
  previewRAGResolution,
  getFrontendRAGSettings, saveFrontendRAGSettings,
  updateCompany,
  getDocMetadata, saveDocMetadata,
} from '../api'
import type { RAGDocument, RAGStats, RAGResolutionResponse, Company, DocMetadata, DocMetadataMap } from '../api'

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
  const [metadata, setMetadata] = useState<DocMetadataMap>({})
  const [editingMeta, setEditingMeta] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const tierLabel = companySlug ? 'company' : frontendId ? 'frontend' : 'global'
  const showFrontendCombine = tierLabel === 'frontend'
  const showCompanyCombine = tierLabel === 'company' && !!company
  const showMetadataEditor = tierLabel === 'company'

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
    setEditingMeta(null)
    refresh()
    if (showFrontendCombine && frontendId) {
      getFrontendRAGSettings(frontendId)
        .then(r => setCombineGlobalAtFrontend(r.settings.combine_global_rag))
        .catch(e => setError(e instanceof Error ? e.message : String(e)))
    }
    if (showMetadataEditor) {
      getDocMetadata(frontendId, companySlug)
        .then(r => setMetadata(r.metadata))
        .catch(e => setError(e instanceof Error ? e.message : String(e)))
    } else {
      setMetadata({})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId, companySlug])

  const updateMetadata = async (filename: string, patch: DocMetadata) => {
    if (!showMetadataEditor) return
    setError('')
    try {
      const r = await saveDocMetadata(filename, patch, frontendId, companySlug)
      setMetadata(prev => ({ ...prev, [filename]: r.metadata }))
      // Triggers backend re-derive of country_tags; trigger parent to reload company chips.
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

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

  // Cascade reindex. At global tier this rebuilds every scope in the deployment
  // (global + every frontend + every company). At frontend tier it rebuilds this
  // frontend + all its companies. Hidden at company tier — per-scope Reindex is
  // already the right button there.
  const onReindexCascade = async () => {
    const isGlobal = tierLabel === 'global'
    const warn = isGlobal
      ? 'This reindexes the ENTIRE corpus: global + every frontend + every company. On a large corpus it can take several minutes, and queries will return degraded results while it runs. Continue?'
      : `This reindexes the "${frontendId}" frontend + all its companies. Queries against this frontend will return degraded results while it runs. Continue?`
    if (!confirm(warn)) return
    setError('')
    setBusy(true)
    try {
      const r = isGlobal
        ? await reindexAllRAG()
        : await reindexFrontendCascade(frontendId!)
      // Refresh THIS section's stats so the admin sees the current tier update.
      await refresh()
      const errs = r.stats.filter(s => s.error)
      if (errs.length) {
        setError(`${r.scopes_reindexed - errs.length} / ${r.scopes_reindexed} scopes ok; ${errs.length} failed (check backend logs).`)
      }
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
        {tierLabel === 'global' && (
          <button
            onClick={onReindexCascade}
            disabled={busy}
            title="Rebuilds the global index AND every frontend / company under it."
            className="text-sm border border-amber-300 bg-amber-50 text-amber-900 rounded-lg px-3 py-2 hover:bg-amber-100 disabled:opacity-50"
          >
            Reindex everything
          </button>
        )}
        {tierLabel === 'frontend' && (
          <button
            onClick={onReindexCascade}
            disabled={busy}
            title="Rebuilds this frontend's index AND every company under it. Global is not touched."
            className="text-sm border border-amber-300 bg-amber-50 text-amber-900 rounded-lg px-3 py-2 hover:bg-amber-100 disabled:opacity-50"
          >
            Reindex frontend + companies
          </button>
        )}
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
        {docs.map(d => {
          const meta = metadata[d.name] || {}
          const isEditing = editingMeta === d.name
          const summary = [meta.country, meta.language, meta.document_type].filter(Boolean).join(' · ')
          return (
            <li key={d.name} className="px-3 py-2 text-sm">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <span className="font-medium text-gray-800">{d.name}</span>
                  <span className="ml-2 text-xs text-gray-400">{fmtSize(d.size)}</span>
                  {showMetadataEditor && summary && (
                    <span className="ml-2 text-[11px] text-gray-500 font-mono">{summary}</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {showMetadataEditor && (
                    <button
                      onClick={() => setEditingMeta(isEditing ? null : d.name)}
                      className="text-xs border border-gray-300 rounded px-2 py-0.5 hover:bg-gray-50"
                    >
                      {isEditing ? 'Hide metadata' : (summary ? 'Edit metadata' : '+ Add metadata')}
                    </button>
                  )}
                  <button onClick={() => onDelete(d.name)} disabled={busy} className="text-xs text-uni-red hover:underline disabled:opacity-50">
                    Delete
                  </button>
                </div>
              </div>
              {showMetadataEditor && isEditing && (
                <MetadataForm
                  current={meta}
                  onSave={patch => updateMetadata(d.name, patch)}
                />
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function MetadataForm({ current, onSave }: { current: DocMetadata; onSave: (patch: DocMetadata) => Promise<void> }) {
  const [country, setCountry] = useState(current.country || '')
  const [language, setLanguage] = useState(current.language || '')
  const [docType, setDocType] = useState(current.document_type || '')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState(0)

  const dirty =
    (country || '') !== (current.country || '') ||
    (language || '') !== (current.language || '') ||
    (docType || '') !== (current.document_type || '')

  const handleSave = async () => {
    setSaving(true)
    await onSave({ country: country.trim().toUpperCase(), language: language.trim().toLowerCase(), document_type: docType.trim() })
    setSaving(false)
    setSavedAt(Date.now())
    setTimeout(() => setSavedAt(0), 2000)
  }

  return (
    <div className="mt-2 ml-4 grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
      <div>
        <label className="block text-[11px] text-gray-500 mb-0.5">Country (ISO-2)</label>
        <input value={country} onChange={e => setCountry(e.target.value)}
          placeholder="AU"
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono uppercase" />
      </div>
      <div>
        <label className="block text-[11px] text-gray-500 mb-0.5">Language (ISO-2)</label>
        <input value={language} onChange={e => setLanguage(e.target.value)}
          placeholder="en"
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono lowercase" />
      </div>
      <div>
        <label className="block text-[11px] text-gray-500 mb-0.5">Document type</label>
        <select value={docType} onChange={e => setDocType(e.target.value)}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs">
          <option value="">—</option>
          <option value="cba">CBA</option>
          <option value="policy">Policy</option>
          <option value="code_of_conduct">Code of conduct</option>
          <option value="agreement">Agreement</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div>
        <button onClick={handleSave} disabled={!dirty || saving}
          className="text-xs bg-uni-blue text-white rounded-lg px-3 py-1 hover:opacity-90 disabled:opacity-50">
          {saving ? 'Saving…' : savedAt ? 'Saved' : 'Save'}
        </button>
      </div>
    </div>
  )
}
