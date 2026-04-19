// Adapted from HRDDHelper/src/frontend/src/components/DisclaimerPage.tsx
import { t } from '../i18n'
import type { LangCode, BrandingConfig } from '../types'

interface Props {
  lang: LangCode
  onAccept: () => void
  onBack: () => void
  branding?: BrandingConfig
}

export default function DisclaimerPage({ lang, onAccept, onBack, branding }: Props) {
  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6 max-h-[80vh] overflow-y-auto">
        {branding?.logo_url && (
          <div className="flex justify-center mb-4">
            <img src={branding.logo_url} alt={branding.app_title || 'CBC'} className="h-20" />
          </div>
        )}

        {branding?.disclaimer_text ? (
          <>
            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_title', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {branding.disclaimer_text}
            </div>
          </>
        ) : (
          <>
            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_what_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_what_body', lang)}
            </div>

            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_data_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_data_body', lang)}
            </div>

            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_legal_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_legal_body', lang)}
            </div>
          </>
        )}

        <button
          onClick={onAccept}
          className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
        >
          {t('disclaimer_accept', lang)}
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
