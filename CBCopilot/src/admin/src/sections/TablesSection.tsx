// Sprint 16 — Structured Table Pipeline admin view (compact, collapsible).
//
// Only mounted at the company tier (inside CompanyManagementPanel). Intent is
// "let the admin verify that tables got extracted from a CBA", not "browse
// tabular content". So by default the section renders collapsed with a
// "Tablas extraídas (N)" summary; expanding shows a flat list (one row per
// table) with name + source location + row count + a CSV download link.
// No 5-row previews — that made the page unusable once a company had more
// than a handful of CBAs.

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

  const total = data?.total_tables ?? 0

  return (
    <section className="bg-white rounded-lg shadow p-3">
      <details className="group">
        <summary className="flex items-center justify-between cursor-pointer list-none select-none">
          <div className="flex items-center gap-2">
            <span className="text-gray-400 group-open:rotate-90 transition-transform">▸</span>
            <h4 className="text-sm font-semibold text-gray-800">
              {t('tables_heading')}
            </h4>
            <span className="text-xs text-gray-500">
              ({t('tables_doc_count').replace('{n}', String(total))})
            </span>
          </div>
          <div className="flex items-center gap-2">
            {status && <span className="text-xs text-gray-500">{status}</span>}
            <button
              onClick={(e) => { e.preventDefault(); reextract() }}
              disabled={busy}
              className="px-2 py-1 text-xs border border-gray-300 text-gray-700 rounded disabled:opacity-50 hover:bg-gray-50"
            >
              {busy ? t('tables_reextracting') : t('tables_reextract')}
            </button>
          </div>
        </summary>

        <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
          {error && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">
              {error}
            </div>
          )}

          {!data && !error && (
            <p className="text-xs text-gray-400">{t('generic_loading')}</p>
          )}

          {data && total === 0 && (
            <p className="text-xs text-gray-500 italic">{t('tables_empty')}</p>
          )}

          {data && total > 0 && data.docs.map(doc => (
            <div key={doc.doc_name} className="text-xs">
              <p className="font-medium text-gray-700 mb-1">{doc.doc_name}</p>
              {doc.tables.length === 0 ? (
                <p className="text-amber-700 bg-amber-50 rounded px-2 py-1">
                  {t('tables_doc_zero_warning')}
                </p>
              ) : (
                <ul className="space-y-0.5 pl-3">
                  {doc.tables.map(tbl => (
                    <li key={tbl.id} className="flex items-baseline gap-2">
                      <span className="text-gray-800 truncate">{tbl.name}</span>
                      <span className="text-gray-400 shrink-0">·</span>
                      <span className="text-gray-500 truncate">{tbl.source_location}</span>
                      <span className="text-gray-400 shrink-0">·</span>
                      <span className="text-gray-500 shrink-0">
                        {t('tables_rows').replace('{n}', String(tbl.row_count))}
                      </span>
                      <a
                        href={tableCsvUrl({ frontendId, companySlug }, doc.doc_name, tbl.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-auto shrink-0 text-uni-blue hover:underline"
                      >
                        CSV
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </details>
    </section>
  )
}
