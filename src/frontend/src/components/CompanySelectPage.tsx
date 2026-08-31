// NEW component — replaces HRDD's RoleSelectPage.
// SPEC §3.2: vertical column of wide buttons, "Compare All" first, companies alphabetical.
import { useEffect, useState } from 'react'
import { t } from '../i18n'
import type { LangCode, Company, DeploymentConfig } from '../types'

interface Props {
  lang: LangCode
  config: DeploymentConfig
  onSelect: (company: Company) => void
  onBack: () => void
}

export default function CompanySelectPage({ lang, config, onSelect, onBack }: Props) {
  const [companies, setCompanies] = useState<Company[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/internal/companies')
      .then(r => r.json())
      .then(data => {
        const list: Company[] = (data.companies || []).filter((c: Company) => c.enabled !== false)
        // Backend already orders Compare All first + alphabetical, but we re-sort here
        // in case a future endpoint returns unsorted data.
        list.sort((a, b) => {
          if (a.is_compare_all && !b.is_compare_all) return -1
          if (!a.is_compare_all && b.is_compare_all) return 1
          return a.display_name.localeCompare(b.display_name)
        })
        const filtered = config.compare_all_enabled === false
          ? list.filter(c => !c.is_compare_all)
          : list
        setCompanies(filtered)
      })
      .catch(() => setError('Failed to load companies'))
  }, [config.compare_all_enabled])

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-1">{t('company_select_title', lang)}</h2>
        <p className="text-sm text-gray-500 mb-6">{t('company_select_subtitle', lang)}</p>

        {error && <p className="text-uni-red text-sm mb-4">{error}</p>}

        {!companies ? (
          <p className="text-gray-400 text-sm">{t('loading', lang)}</p>
        ) : companies.length === 0 ? (
          <p className="text-gray-500 text-sm">No companies configured for this deployment.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {companies.map(c => (
              <button
                key={c.slug}
                onClick={() => onSelect(c)}
                className={`w-full rounded-lg px-6 py-4 text-left font-medium transition-all border-2 bg-uni-blue text-white hover:opacity-90 ${
                  c.is_compare_all
                    ? 'border-white/40 ring-2 ring-uni-blue/30 shadow-md'
                    : 'border-uni-blue hover:shadow-md'
                }`}
              >
                <span className="text-base">{c.display_name}</span>
                {c.is_compare_all && (
                  <span className="block text-xs text-white/80 font-normal mt-1">
                    {t('company_select_subtitle', lang)}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        <button
          onClick={onBack}
          className="w-full text-gray-500 text-sm hover:text-gray-700 mt-6"
        >
          &larr; {t('nav_back', lang)}
        </button>
      </div>
    </div>
  )
}
