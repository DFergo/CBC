// Adapted from HRDDHelper/src/frontend/src/components/InstructionsPage.tsx
// CBC has a single user profile — no role-based variants.
import { t } from '../i18n'
import type { LangCode, BrandingConfig } from '../types'

interface Props {
  lang: LangCode
  onContinue: () => void
  onBack: () => void
  branding?: BrandingConfig
}

export default function InstructionsPage({ lang, onContinue, onBack, branding }: Props) {
  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        {branding?.logo_url && (
          <div className="flex justify-center mb-4">
            <img src={branding.logo_url} alt={branding.app_title || 'CBC'} className="h-20" />
          </div>
        )}
        <h2 className="text-xl font-semibold text-gray-800 mb-4">{t('instructions_title', lang)}</h2>
        <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
          {t('instructions_body', lang)}
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 mb-4">
          {t('instructions_no_reload', lang)}
        </div>
        <button
          onClick={onContinue}
          className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
        >
          {t('instructions_continue', lang)}
        </button>
        <button
          onClick={onBack}
          className="w-full text-gray-500 text-sm hover:text-gray-700 mt-2"
        >
          &larr; {t('nav_back', lang)}
        </button>
      </div>
    </div>
  )
}
