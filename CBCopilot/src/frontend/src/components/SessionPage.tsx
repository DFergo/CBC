// Adapted from HRDDHelper/src/frontend/src/components/SessionPage.tsx
// Sprint 7 (D5=A): adds a "Resume existing session" flow next to the
// original "Start a new session" button. On recovery success, the app skips
// the survey flow and lands directly in chat with the past conversation
// already replayed in the bubble list.
import { useState } from 'react'
import { t } from '../i18n'
import { generateToken } from '../token'
import type { LangCode, RecoveryData } from '../types'

interface Props {
  lang: LangCode
  onNewSession: (token: string) => void
  onResume: (data: RecoveryData) => void
  onBack: () => void
}

export default function SessionPage({ lang, onNewSession, onResume, onBack }: Props) {
  const [token, setToken] = useState('')
  const [mode, setMode] = useState<'choose' | 'resume'>('choose')
  const [resumeToken, setResumeToken] = useState('')
  const [resumeError, setResumeError] = useState('')
  const [resumeBusy, setResumeBusy] = useState(false)

  const handleGenerate = () => setToken(generateToken())

  const handleResume = async () => {
    const value = resumeToken.trim().toUpperCase()
    if (!value) return
    setResumeBusy(true)
    setResumeError('')
    try {
      // Pull-inverse: queue the recovery request on the sidecar. The backend
      // resolves it on its next poll (typically within 2s) and POSTs the
      // result back. We then poll the sidecar for the resolved status.
      const startRes = await fetch('/internal/session/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: value }),
      })
      if (!startRes.ok) {
        setResumeError(t('session_resume_error', lang))
        return
      }
      // Poll every 400ms for up to ~15s. Backend polling runs every 2s so
      // typical latency is 0–2s; we give it plenty of room before surfacing
      // the timeout as a generic error.
      const deadline = Date.now() + 15_000
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 400))
        const pollRes = await fetch(`/internal/session/${encodeURIComponent(value)}/recover`)
        if (pollRes.status === 404 || pollRes.status === 504) {
          setResumeError(t('session_resume_error', lang))
          return
        }
        if (!pollRes.ok) continue
        const body = (await pollRes.json()) as { status: string; data?: RecoveryData }
        if (body.status === 'pending') continue
        if (body.status === 'not_found') {
          setResumeError(t('session_resume_not_found', lang))
          return
        }
        if (body.status === 'expired') {
          setResumeError(t('session_resume_expired', lang))
          return
        }
        if (body.status === 'found' && body.data) {
          onResume(body.data)
          return
        }
      }
      setResumeError(t('session_resume_error', lang))
    } catch {
      setResumeError(t('session_resume_error', lang))
    } finally {
      setResumeBusy(false)
    }
  }

  // --- Render ---

  if (token) {
    return (
      <div className="max-w-4xl mx-auto mt-8 p-6">
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('session_title', lang)}</h2>
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
        </div>
      </div>
    )
  }

  if (mode === 'resume') {
    return (
      <div className="max-w-4xl mx-auto mt-8 p-6">
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('session_resume_title', lang)}</h2>
          <label className="block text-sm text-gray-600 mb-2">{t('session_resume_label', lang)}</label>
          <input
            value={resumeToken}
            onChange={e => setResumeToken(e.target.value.toUpperCase())}
            placeholder="ABCD-1234"
            autoFocus
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-center text-lg font-mono tracking-wider focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
          />
          {resumeError && <p className="text-uni-red text-sm mt-2">{resumeError}</p>}
          <div className="flex gap-2 mt-4">
            <button
              onClick={handleResume}
              disabled={resumeBusy || !resumeToken.trim()}
              className="flex-1 bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium hover:opacity-90 disabled:opacity-50"
            >
              {t('session_resume_button', lang)}
            </button>
            <button
              onClick={() => { setMode('choose'); setResumeError(''); setResumeToken('') }}
              disabled={resumeBusy}
              className="flex-1 border border-gray-300 text-gray-700 rounded-lg px-4 py-2.5 hover:bg-gray-50 disabled:opacity-50"
            >
              {t('session_resume_cancel', lang)}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('session_title', lang)}</h2>
        <div className="space-y-3">
          <button
            onClick={handleGenerate}
            className="w-full bg-uni-blue text-white rounded-lg px-4 py-3 font-medium transition-colors hover:opacity-90"
          >
            {t('session_new', lang)}
          </button>
          <button
            onClick={() => setMode('resume')}
            className="w-full border border-gray-300 text-gray-700 rounded-lg px-4 py-3 font-medium transition-colors hover:bg-gray-50"
          >
            {t('session_resume', lang)}
          </button>
          <button
            onClick={onBack}
            className="w-full text-gray-500 text-sm hover:text-gray-700 pt-2"
          >
            &larr; {t('nav_back', lang)}
          </button>
        </div>
      </div>
    </div>
  )
}
