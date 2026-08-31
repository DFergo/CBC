// Adapted from HRDDHelper/src/frontend/src/components/AuthPage.tsx
// Sprint 10B: pull-inverse — React POSTs to the sidecar to queue an auth
// action and then polls /internal/auth/status/{token} for the result that
// the backend pushes back when its polling loop resolves the request.
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
const POLL_INTERVAL_MS = 400
const POLL_DEADLINE_MS = 20_000

interface AuthStatus {
  status: string
  email?: string
  dev_code?: string
  detail?: string
}

async function pollAuthStatus(
  sessionToken: string,
  pendingStatuses: ReadonlyArray<string>,
): Promise<AuthStatus> {
  const deadline = Date.now() + POLL_DEADLINE_MS
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
    try {
      const r = await fetch(`/internal/auth/status/${encodeURIComponent(sessionToken)}`)
      if (!r.ok) continue
      const body = (await r.json()) as AuthStatus
      if (!pendingStatuses.includes(body.status)) {
        return body
      }
    } catch {
      // sidecar transient hiccup — keep polling until deadline
    }
  }
  return { status: 'timeout' }
}

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
      const queued = await fetch('/internal/auth/request-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken, email, language: lang }),
      })
      if (!queued.ok) throw new Error('Request failed')
      const result = await pollAuthStatus(sessionToken, ['none', 'pending'])
      if (result.status === 'code_sent') {
        setCodeSent(true)
        if (result.dev_code) setDevCode(result.dev_code)
      } else if (result.status === 'not_authorized') {
        setError(t('auth_contact_admin', lang))
      } else if (result.status === 'timeout') {
        setError(t('session_resume_error', lang))
      } else {
        setError(t('chat_error', lang))
      }
    } catch {
      setError(t('session_resume_error', lang))
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const queued = await fetch('/internal/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken, code, language: lang }),
      })
      if (!queued.ok) throw new Error('Request failed')
      const result = await pollAuthStatus(sessionToken, ['none', 'verifying'])
      if (result.status === 'verified') {
        onVerified(result.email || email)
      } else if (result.status === 'invalid_code') {
        const newRetries = retries + 1
        setRetries(newRetries)
        setError(newRetries >= MAX_RETRIES ? t('auth_max_retries', lang) : t('auth_invalid_code', lang))
      } else if (result.status === 'timeout') {
        setError(t('session_resume_error', lang))
      } else {
        setError(t('chat_error', lang))
      }
    } catch {
      setError(t('session_resume_error', lang))
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
