// Adapted from HRDDHelper/src/frontend/src/App.tsx
// Sprint 2: full page flow, placeholder instead of ChatShell at the end.
import { useState, useEffect, useCallback } from 'react'
import { t } from './i18n'
import type { Phase, LangCode, DeploymentConfig, SurveyData, Company } from './types'
import LanguageSelector from './components/LanguageSelector'
import DisclaimerPage from './components/DisclaimerPage'
import SessionPage from './components/SessionPage'
import AuthPage from './components/AuthPage'
import InstructionsPage from './components/InstructionsPage'
import CompanySelectPage from './components/CompanySelectPage'
import SurveyPage from './components/SurveyPage'
import ChatShell from './components/ChatShell'

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [lang, setLang] = useState<LangCode>('en')
  const [config, setConfig] = useState<DeploymentConfig | null>(null)
  const [sessionToken, setSessionToken] = useState('')
  const [verifiedEmail, setVerifiedEmail] = useState('')
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null)
  const [survey, setSurvey] = useState<SurveyData | null>(null)

  useEffect(() => {
    fetchConfig()
  }, [])

  const navigateTo = useCallback((next: Phase) => {
    window.history.pushState({ phase: next }, '', '')
    setPhase(next)
  }, [])

  useEffect(() => {
    const onPopState = (e: PopStateEvent) => {
      if (e.state?.phase) setPhase(e.state.phase)
      else setPhase('language')
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (phase === 'survey' || phase === 'chat') e.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [phase])

  async function fetchConfig() {
    try {
      const res = await fetch('/internal/config')
      if (res.ok) setConfig(await res.json())
    } catch {
      // Use defaults
    }
    setPhase('language')
  }

  const handleLanguage = (selected: LangCode) => {
    setLang(selected)
    navigateTo(config?.disclaimer_enabled === false ? 'session' : 'disclaimer')
  }

  const handleDisclaimer = () => navigateTo('session')

  const handleNewSession = (token: string) => {
    setSessionToken(token)
    if (config?.auth_required) navigateTo('auth')
    else if (config?.instructions_enabled === false) navigateTo('company_select')
    else navigateTo('instructions')
  }

  const handleAuth = (email: string) => {
    setVerifiedEmail(email)
    if (config?.instructions_enabled === false) navigateTo('company_select')
    else navigateTo('instructions')
  }

  const handleInstructions = () => navigateTo('company_select')

  const handleCompanySelect = (company: Company) => {
    setSelectedCompany(company)
    navigateTo('survey')
  }

  const handleSurvey = async (data: SurveyData) => {
    setSurvey(data)
    try {
      await fetch('/internal/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_token: sessionToken,
          survey: data,
          language: lang,
        }),
      })
    } catch {
      // Silent — chat UI still renders so the user isn't blocked
    }
    navigateTo('chat')
  }

  const goBack = {
    disclaimer: () => navigateTo('language'),
    session: () => navigateTo(config?.disclaimer_enabled === false ? 'language' : 'disclaimer'),
    auth: () => navigateTo('session'),
    instructions: () => navigateTo(config?.auth_required ? 'auth' : 'session'),
    company_select: () => navigateTo(
      config?.instructions_enabled === false
        ? (config?.auth_required ? 'auth' : 'session')
        : 'instructions'
    ),
    survey: () => navigateTo('company_select'),
  }

  const branding = config?.branding
  const showFooter = phase !== 'loading' && phase !== 'chat'

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-uni-blue text-white px-6 py-3 shadow-md flex items-center justify-between">
        <div className="flex items-center gap-3">
          {branding?.logo_url && (
            <img
              src={branding.logo_url}
              alt={branding.org_name || 'CBC'}
              className="h-8 brightness-0 invert"
            />
          )}
          <h1 className="text-xl font-semibold">{branding?.app_title || 'Collective Bargaining Copilot'}</h1>
        </div>
        <span className="text-sm opacity-75">{branding?.org_name || 'UNI Global Union'}</span>
      </header>

      <main className="flex-1">
        {phase === 'loading' && (
          <div className="flex items-center justify-center mt-20">
            <p className="text-gray-400">{t('loading', lang)}</p>
          </div>
        )}

        {phase === 'language' && (
          <LanguageSelector onSelect={handleLanguage} branding={branding} />
        )}

        {phase === 'disclaimer' && (
          <DisclaimerPage lang={lang} onAccept={handleDisclaimer} onBack={goBack.disclaimer} branding={branding} />
        )}

        {phase === 'session' && (
          <SessionPage lang={lang} onNewSession={handleNewSession} onBack={goBack.session} />
        )}

        {phase === 'auth' && (
          <AuthPage lang={lang} sessionToken={sessionToken} onVerified={handleAuth} onBack={goBack.auth} />
        )}

        {phase === 'instructions' && (
          <InstructionsPage lang={lang} onContinue={handleInstructions} onBack={goBack.instructions} branding={branding} />
        )}

        {phase === 'company_select' && config && (
          <CompanySelectPage lang={lang} config={config} onSelect={handleCompanySelect} onBack={goBack.company_select} />
        )}

        {phase === 'survey' && selectedCompany && (
          <SurveyPage
            lang={lang}
            company={selectedCompany}
            prefillEmail={verifiedEmail}
            onSubmit={handleSurvey}
            onBack={goBack.survey}
          />
        )}

        {phase === 'chat' && survey && (
          <ChatShell lang={lang} sessionToken={sessionToken} survey={survey} branding={branding} />
        )}
      </main>

      {showFooter && (
        <footer className="text-center text-xs text-gray-400 py-3 space-y-1">
          <p>{t('footer_disclaimer', lang)}</p>
          <p>© 2026 {branding?.org_name || 'UNI Global Union'}</p>
        </footer>
      )}
    </div>
  )
}
