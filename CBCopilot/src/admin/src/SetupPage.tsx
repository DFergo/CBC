import { useState } from 'react'
import { setupAdmin } from './api'
import AdminLanguageSelector from './AdminLanguageSelector'
import { useT } from './i18n'

interface Props {
  onComplete: () => void
}

export default function SetupPage({ onComplete }: Props) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { t } = useT()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (password !== confirm) {
      setError(t('setup_passwords_dont_match'))
      return
    }
    if (password.length < 8) {
      setError(t('setup_password_too_short'))
      return
    }

    setLoading(true)
    try {
      await setupAdmin(password, confirm)
      onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('generic_error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <div className="flex justify-end p-4">
        <div className="bg-uni-dark rounded-lg px-2 py-1">
          <AdminLanguageSelector />
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-8 w-full max-w-md">
          <h2 className="text-2xl font-semibold text-gray-800 mb-2">{t('setup_title')}</h2>
          <p className="text-gray-500 text-sm mb-6">{t('header_subtitle')}</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('setup_password_label')}</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none transition-colors"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('setup_confirm_label')}</label>
              <input
                type="password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none transition-colors"
                required
              />
            </div>

            {error && <p className="text-uni-red text-sm">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '…' : t('setup_submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
