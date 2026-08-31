// Adapted from HRDDHelper/src/frontend/src/components/SurveyPage.tsx
// CBC fields per SPEC §3.4. Compare All adds a comparison_scope radio.
// Upload: file input visible but disabled (Sprint 5 wires actual upload).
import { useState } from 'react'
import { t } from '../i18n'
import type { LangCode, Company, SurveyData, ComparisonScope } from '../types'

interface Props {
  lang: LangCode
  company: Company
  prefillEmail?: string
  onSubmit: (data: SurveyData) => void
  onBack: () => void
}

const SCOPES: ComparisonScope[] = ['national', 'regional', 'global']

export default function SurveyPage({ lang, company, prefillEmail, onSubmit, onBack }: Props) {
  const [country, setCountry] = useState('')
  const [region, setRegion] = useState('')
  const [name, setName] = useState('')
  const [organization, setOrganization] = useState('')
  const [position, setPosition] = useState('')
  const [email, setEmail] = useState(prefillEmail || '')
  const [initialQuery, setInitialQuery] = useState('')
  const [scope, setScope] = useState<ComparisonScope>('national')
  const [uploadedFilename, setUploadedFilename] = useState<string>('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: SurveyData = {
      company_slug: company.slug,
      company_display_name: company.display_name,
      is_compare_all: !!company.is_compare_all,
      country,
      region,
      initial_query: initialQuery,
      ...(name && { name }),
      ...(organization && { organization }),
      ...(position && { position }),
      ...(email && { email }),
      ...(uploadedFilename && { uploaded_filename: uploadedFilename }),
      ...(company.is_compare_all && { comparison_scope: scope }),
    }
    onSubmit(data)
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-1">{t('survey_title', lang)}</h2>
        <p className="text-sm text-gray-500 mb-6">
          {t('survey_company_label', lang)}: <strong>{company.display_name}</strong>
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {company.is_compare_all && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('survey_comparison_scope', lang)}<span className="text-uni-red ml-0.5">*</span>
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {SCOPES.map(s => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setScope(s)}
                    className={`px-3 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                      scope === s
                        ? 'bg-uni-blue text-white border-uni-blue'
                        : 'border-gray-300 text-gray-700 hover:border-uni-blue hover:bg-blue-50'
                    }`}
                  >
                    {t(`scope_${s}` as 'scope_national' | 'scope_regional' | 'scope_global', lang)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_country', lang)}<span className="text-uni-red ml-0.5">*</span>
            </label>
            <input
              type="text"
              value={country}
              onChange={e => setCountry(e.target.value)}
              required
              placeholder="e.g. Germany"
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_region', lang)}<span className="text-uni-red ml-0.5">*</span>
            </label>
            <input
              type="text"
              value={region}
              onChange={e => setRegion(e.target.value)}
              required
              placeholder="e.g. North-Rhine Westphalia"
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_name', lang)}</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_position', lang)}</label>
              <input
                type="text"
                value={position}
                onChange={e => setPosition(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_organization', lang)}</label>
              <input
                type="text"
                value={organization}
                onChange={e => setOrganization(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_email', lang)}</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_initial_query', lang)}<span className="text-uni-red ml-0.5">*</span>
            </label>
            <textarea
              value={initialQuery}
              onChange={e => setInitialQuery(e.target.value)}
              rows={4}
              required
              placeholder="What do you want to compare or learn about?"
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none resize-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_upload_label', lang)}</label>
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md"
              onChange={e => setUploadedFilename(e.target.files?.[0]?.name || '')}
              className="w-full text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
            />
            <p className="mt-1 text-xs text-gray-400">{t('survey_upload_hint', lang)}</p>
          </div>

          <button
            type="submit"
            className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
          >
            {t('survey_submit', lang)}
          </button>
          <button
            type="button"
            onClick={onBack}
            className="w-full text-gray-500 text-sm hover:text-gray-700 mt-2"
          >
            &larr; {t('nav_back', lang)}
          </button>
        </form>
      </div>
    </div>
  )
}
