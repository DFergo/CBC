// Adapted from HRDDHelper/src/frontend/src/components/LanguageSelector.tsx
// Sprint 2: only EN available. Sprint 8 adds ES/FR/DE/PT.
import { LANGUAGES, t } from '../i18n'
import type { LangCode, BrandingConfig } from '../types'

interface Props {
  onSelect: (lang: LangCode) => void
  branding?: BrandingConfig
}

export default function LanguageSelector({ onSelect, branding }: Props) {
  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        {branding?.logo_url && (
          <div className="flex justify-center mb-4">
            <img src={branding.logo_url} alt={branding.app_title || 'CBC'} className="h-20" />
          </div>
        )}
        <h2 className="text-xl font-semibold text-gray-800 mb-1 text-center">{t('language_select_title', 'en')}</h2>
        <p className="text-sm text-gray-400 mb-6 text-center">{t('language_select_subtitle', 'en')}</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {LANGUAGES.map(lang => (
            <button
              key={lang.code}
              onClick={() => onSelect(lang.code)}
              className="flex flex-col items-center justify-center px-3 py-4 rounded-lg border border-gray-200 hover:border-uni-blue hover:bg-blue-50 transition-colors"
            >
              <span className="text-sm font-medium text-gray-800">{lang.nativeName}</span>
              <span className="text-xs text-gray-400 mt-0.5">{lang.name}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
