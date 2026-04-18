// Adapted from HRDDHelper/src/frontend/src/components/AuthPage.tsx
// Sprint 2 stub: sidecar returns the 6-digit code inline (dev_code) so the UI
// can display it in a dev banner. Real SMTP flow lands in Sprint 7.
import { useState } from 'react'
import { t } from '../i18n'
import type { LangCode } from '../types'

interface Props {
  lang: LangCode
  sessionToken: string
  onVerified: (email: string) => void
  onBack: () => void
}

const MAX_RETRIES = 3

export default function AuthPage({ lang, sessionToken, onVerified, onBack }: Props) {
  const [email, setEmail] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [devCode, setDevCode] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [retries, setRetries] = useState(0)

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const resp = await fetch('/internal/auth/request-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken, email }),
      })
      if (!resp.ok) throw new Error('Request failed')
      const data = await resp.json()
      if (data.status === 'code_sent') {
        setCodeSent(true)
        if (data.dev_code) setDevCode(data.dev_code)
      } else {
        setError('Unexpected response')
      }
    } catch {
      setError('Could not reach the server. Try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const resp = await fetch('/internal/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken, code }),
      })
      if (!resp.ok) throw new Error('Request failed')
      const data = await resp.json()
      if (data.status === 'verified') {
        onVerified(email)
      } else {
        const newRetries = retries + 1
        setRetries(newRetries)
        setError(newRetries >= MAX_RETRIES ? t('auth_max_retries', lang) : t('auth_invalid_code', lang))
      }
    } catch {
      setError('Could not reach the server. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('auth_title', lang)}</h2>

        {!codeSent ? (
          <form onSubmit={handleSendCode} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth_email_label', lang)}</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none transition-colors"
                required
              />
            </div>
            {error && <p className="text-uni-red text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {loading ? '...' : t('auth_send_code', lang)}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerify} className="space-y-4">
            {devCode && (
              <div className="bg-amber-100 border border-amber-300 rounded-lg p-3">
                <p className="text-xs font-semibold text-amber-900 uppercase tracking-wide">{t('auth_dev_banner', lang)}</p>
                <p className="text-xs text-amber-800 mt-1">{t('auth_dev_banner_note', lang)}</p>
                <p className="mt-2 text-center font-mono text-2xl font-bold text-amber-900 tracking-[0.3em]">{devCode}</p>
              </div>
            )}
            <p className="text-sm text-gray-600">{t('auth_code_sent_to', lang)} <strong>{email}</strong></p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth_code_label', lang)}</label>
              <input
                type="text"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder={t('auth_placeholder', lang)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-center text-2xl tracking-[0.5em] font-mono focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                maxLength={6}
                required
                autoFocus
                disabled={retries >= MAX_RETRIES}
              />
            </div>
            {error && <p className="text-uni-red text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading || retries >= MAX_RETRIES}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {loading ? '...' : t('auth_verify', lang)}
            </button>
            {retries >= MAX_RETRIES && (
              <p className="text-sm text-gray-500 text-center">{t('auth_contact_admin', lang)}</p>
            )}
          </form>
        )}
        {!codeSent && !loading && (
          <button
            onClick={onBack}
            className="w-full text-gray-500 text-sm hover:text-gray-700 mt-4"
          >
            &larr; {t('nav_back', lang)}
          </button>
        )}
      </div>
    </div>
  )
}
