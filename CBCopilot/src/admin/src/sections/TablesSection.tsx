// Sprint 16 — Structured Table Pipeline admin view.
//
// Tier-aware like RAGSection: omit both props for global, frontendId for
// frontend tier, frontendId+companySlug for company tier. Shows every table
// the extractor has stored for the scope grouped by source document, with
// a 5-row preview per table plus a download link for the full CSV. The
// "Re-extract" button triggers a full scope reindex (prose + tables) via
// /admin/api/v1/tables/reextract — useful for forcing a fresh pass after
// editing a document outside of the upload flow.

import { useEffect, useState } from 'react'
import { listTables, reextractTables, tableCsvUrl } from '../api'
import type { TablesForScope } from '../api'
import { useT } from '../i18n'

interface Props {
  frontendId?: string
  companySlug?: string
}

export default function TablesSection({ frontendId, companySlug }: Props) {
  const { t } = useT()
  const [data, setData] = useState<TablesForScope | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')

  const refresh = async () => {
    try {
      setError('')
      const res = await listTables(frontendId, companySlug)
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    refresh()
    // Reset per-scope state when the scope identity changes.
    setStatus('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId, companySlug])

  const reextract = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    setStatus(t('tables_reextracting'))
    try {
      const r = await reextractTables(frontendId, companySlug)
      setStatus(t('tables_reextract_done').replace('{n}', String(r.total_tables)))
      await refresh()
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="bg-white rounded-lg shadow p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">{t('tables_heading')}</h3>
          <p className="text-sm text-gray-500">{t('tables_description')}</p>
        </div>
        <div className="flex items-center gap-2">
          {status && <span className="text-sm text-gray-500">{status}</span>}
          <button
            onClick={reextract}
            disabled={busy}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
          >
            {busy ? t('tables_reextracting') : t('tables_reextract')}
          </button>
        </div>
      </header>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      {!data && !error && <p className="text-sm text-gray-400">{t('generic_loading')}</p>}

      {data && data.total_tables === 0 && (
        <p className="text-sm text-gray-500 italic">{t('tables_empty')}</p>
      )}

      {data && data.total_tables > 0 && (
        <div className="space-y-6">
          <p className="text-sm text-gray-600">
            {t('tables_summary')
              .replace('{tables}', String(data.total_tables))
              .replace('{docs}', String(data.doc_count))}
          </p>
          {data.docs.map(doc => (
            <div key={doc.doc_name} className="border border-gray-200 rounded-md">
              <div className="bg-gray-50 px-3 py-2 border-b border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800">{doc.doc_name}</h4>
                <p className="text-xs text-gray-500">
                  {t('tables_doc_count').replace('{n}', String(doc.tables.length))}
                </p>
              </div>
              <div className="divide-y divide-gray-100">
                {doc.tables.length === 0 && (
                  <div className="px-3 py-3 text-xs text-amber-700 bg-amber-50">
                    {t('tables_doc_zero_warning')}
                  </div>
                )}
                {doc.tables.map(tbl => (
                  <div key={tbl.id} className="px-3 py-3 space-y-2">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800">{tbl.name}</p>
                        <p className="text-xs text-gray-500">
                          {tbl.source_location} · {t('tables_rows').replace('{n}', String(tbl.row_count))}
                        </p>
                        {tbl.description && tbl.description !== tbl.name && (
                          <p className="text-xs text-gray-500 mt-1 italic">{tbl.description}</p>
                        )}
                      </div>
                      <a
                        href={tableCsvUrl({ frontendId, companySlug }, doc.doc_name, tbl.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 px-2 py-1 text-xs border border-gray-300 rounded text-gray-700 hover:bg-gray-50"
                      >
                        {t('tables_download')}
                      </a>
                    </div>
                    {tbl.preview_rows.length > 0 && (
                      <div className="overflow-x-auto">
                        <table className="min-w-full text-xs border-collapse">
                          <tbody>
                            {tbl.preview_rows.map((row, rIdx) => (
                              <tr
                                key={rIdx}
                                className={rIdx === 0 ? 'bg-gray-100 font-medium' : ''}
                              >
                                {row.map((cell, cIdx) => (
                                  <td
                                    key={cIdx}
                                    className="border border-gray-200 px-2 py-1 align-top whitespace-pre-wrap"
                                  >
                                    {cell}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
