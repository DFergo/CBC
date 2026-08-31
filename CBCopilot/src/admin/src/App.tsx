import { useEffect, useState } from 'react'
import { getAdminStatus, verifyToken } from './api'
import SetupPage from './SetupPage'
import LoginPage from './LoginPage'
import Dashboard from './Dashboard'
import {
  ADMIN_RTL_LANGS, AdminLangContext, loadStoredAdminLang, useT,
} from './i18n'
import type { AdminLangCode } from './i18n'

type Phase = 'loading' | 'setup' | 'login' | 'dashboard'

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  // Sprint 12: admin language lifted to the root so login + setup share the
  // same picker + localStorage-backed choice as the Dashboard. `<html dir>`
  // flips for AR — applied once here instead of once per top-level screen.
  const [lang, setLang] = useState<AdminLangCode>(() => loadStoredAdminLang())

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = ADMIN_RTL_LANGS.includes(lang) ? 'rtl' : 'ltr'
  }, [lang])

  useEffect(() => {
    checkState()
  }, [])

  async function checkState() {
    try {
      const { setup_complete } = await getAdminStatus()
      if (!setup_complete) {
        setPhase('setup')
        return
      }

      const token = localStorage.getItem('cbc_admin_token')
      if (token) {
        try {
          await verifyToken()
          setPhase('dashboard')
          return
        } catch {
          localStorage.removeItem('cbc_admin_token')
        }
      }

      setPhase('login')
    } catch {
      setPhase('login')
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('cbc_admin_token')
    setPhase('login')
  }

  return (
    <AdminLangContext.Provider value={{ lang, setLang }}>
      <PhaseView phase={phase} setPhase={setPhase} onLogout={handleLogout} />
    </AdminLangContext.Provider>
  )
}

function PhaseView({
  phase, setPhase, onLogout,
}: {
  phase: Phase
  setPhase: (p: Phase) => void
  onLogout: () => void
}) {
  const { t } = useT()
  switch (phase) {
    case 'loading':
      return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
          <p className="text-gray-400">{t('generic_loading')}</p>
        </div>
      )
    case 'setup':
      return <SetupPage onComplete={() => setPhase('login')} />
    case 'login':
      return <LoginPage onLogin={() => setPhase('dashboard')} />
    case 'dashboard':
      return <Dashboard onLogout={onLogout} />
  }
}
