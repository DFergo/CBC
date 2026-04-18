// Adapted from HRDDHelper/src/frontend/src/components/SessionPage.tsx
// Sprint 2: only "new session" path. Recovery flow lands with backend coordination in Sprint 7.
import { useState } from 'react'
import { t } from '../i18n'
import { generateToken } from '../token'
import type { LangCode } from '../types'

interface Props {
  lang: LangCode
  onNewSession: (token: string) => void
  onBack: () => void
}

export default function SessionPage({ lang, onNewSession, onBack }: Props) {
  const [token, setToken] = useState('')

  const handleGenerate = () => {
    setToken(generateToken())
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('session_title', lang)}</h2>

        {!token ? (
          <div className="space-y-3">
            <button
              onClick={handleGenerate}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-3 font-medium transition-colors hover:opacity-90"
            >
              {t('session_new', lang)}
            </button>
            <button
              onClick={onBack}
              className="w-full text-gray-500 text-sm hover:text-gray-700"
            >
              &larr; {t('nav_back', lang)}
            </button>
          </div>
        ) : (
          <div className="text-center space-y-4">
            <p className="text-sm text-gray-500">{t('session_token_label', lang)}</p>
            <div className="bg-gray-50 rounded-lg px-6 py-4 border border-gray-200">
              <span className="text-2xl font-mono font-bold text-uni-blue tracking-wider">{token}</span>
            </div>
            <p className="text-sm text-gray-400">{t('session_token_save', lang)}</p>
            <button
              onClick={() => onNewSession(token)}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
            >
              {t('session_continue', lang)}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
