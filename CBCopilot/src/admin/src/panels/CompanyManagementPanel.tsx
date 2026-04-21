import { useEffect, useState } from 'react'
import { listCompanies, createCompany, updateCompany, deleteCompany } from '../api'
import type { Company } from '../api'
import PromptsSection from '../sections/PromptsSection'
import RAGSection from '../sections/RAGSection'
import { useT } from '../i18n'

export default function CompanyManagementPanel({ frontendId }: { frontendId: string }) {
  const [companies, setCompanies] = useState<Company[]>([])
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [newName, setNewName] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const { t } = useT()

  const reload = () => {
    listCompanies(frontendId)
      .then(r => setCompanies(r.companies))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(reload, [frontendId])

  const add = async () => {
    if (!newName.trim()) return
    setError('')
    try {
      const r = await createCompany(frontendId, { display_name: newName.trim() })
      setNewName('')
      reload()
      setInfo(t('companies_added', { slug: r.company.slug }))
      setTimeout(() => setInfo(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const patch = async (slug: string, patchBody: Partial<Company>) => {
    setError('')
    try {
      await updateCompany(frontendId, slug, patchBody)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const remove = async (slug: string) => {
    if (!confirm(t('companies_remove_confirm', { slug }))) return
    setError('')
    try {
      await deleteCompany(frontendId, slug)
      if (expanded === slug) setExpanded(null)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-gray-700">{t('companies_heading')}</h4>
        <span className="text-xs text-gray-500">{t('companies_total', { count: companies.length })}{info && <span className="ml-2">— {info}</span>}</span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        {t('companies_description')}
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="flex flex-wrap items-end gap-2 mb-4 pb-3 border-b border-gray-100">
        <div className="flex-1 min-w-[14rem]">
          <label className="block text-xs text-gray-500 mb-1">{t('companies_display_name')}</label>
          <input value={newName} onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newName.trim()) add() }}
            placeholder="Amcor" className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <button onClick={add} disabled={!newName.trim()}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          {t('companies_add_button')}
        </button>
      </div>

      {companies.length === 0 ? (
        <p className="text-sm text-gray-400">{t('companies_empty')}</p>
      ) : (
        <div className="space-y-2">
          {companies.map(c => (
            <div key={c.slug} className={`border border-gray-200 rounded-lg p-3 text-sm ${c.enabled ? '' : 'opacity-60'}`}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-gray-800">{c.display_name}</span>
                  <code className="text-xs text-gray-400">{c.slug}</code>
                  {c.is_compare_all && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">{t('companies_compare_all')}</span>}
                </div>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={c.enabled} onChange={e => patch(c.slug, { enabled: e.target.checked })} />
                    {t('companies_enabled')}
                  </label>
                  {!c.is_compare_all && (
                    <button
                      onClick={() => setExpanded(expanded === c.slug ? null : c.slug)}
                      className="text-xs border border-gray-300 rounded px-2 py-0.5 hover:bg-gray-50"
                    >
                      {expanded === c.slug ? t('companies_hide_content') : t('companies_show_content')}
                    </button>
                  )}
                  <button onClick={() => remove(c.slug)} className="text-xs text-uni-red hover:underline">{t('companies_delete')}</button>
                </div>
              </div>
              <div className="mt-2">
                <div className="flex items-center justify-between">
                  <label className="block text-[11px] text-gray-500">{t('companies_country_tags')}</label>
                  <span className="text-[10px] text-gray-400 italic">{t('companies_country_tags_hint')}</span>
                </div>
                {(c.country_tags || []).length === 0 ? (
                  <p className="text-xs text-gray-400">{t('companies_country_tags_empty')}</p>
                ) : (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(c.country_tags || []).map(t => (
                      <span key={t} className="inline-block px-2 py-0.5 bg-gray-100 border border-gray-200 rounded text-[11px] font-mono text-gray-700">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {expanded === c.slug && !c.is_compare_all && (
                <div className="mt-4 pt-4 border-t border-gray-100 space-y-4">
                  <PromptsSection frontendId={frontendId} companySlug={c.slug} />
                  <RAGSection
                    frontendId={frontendId}
                    companySlug={c.slug}
                    company={c}
                    onCompanyChanged={reload}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
