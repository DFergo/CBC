// Sprint 12: HRDD-parity admin header — uni-dark band with title + logout +
// language selector on the top row, tabs as a nav strip directly beneath.
// Separation is visual (shadow + bg change) so the main content feels
// distinct from the navigation chrome.
//
// The dark header is deliberately heavier than CBC's previous pale version:
// it signals "this is an admin surface, not a user chat" the moment an
// affiliate operator opens it.
import { useState } from 'react'
import GeneralTab from './GeneralTab'
import FrontendsTab from './FrontendsTab'
import SessionsTab from './SessionsTab'
import RegisteredUsersTab from './RegisteredUsersTab'
import AdminLanguageSelector from './AdminLanguageSelector'
import { useT } from './i18n'

type Tab = 'general' | 'frontends' | 'sessions' | 'users'

interface Props {
  onLogout: () => void
}

export default function Dashboard({ onLogout }: Props) {
  const [tab, setTab] = useState<Tab>('general')

  return (
    <div className="min-h-screen bg-gray-100">
      <DashboardHeader onLogout={onLogout} />
      <DashboardTabs tab={tab} setTab={setTab} />
      <main className="max-w-6xl mx-auto p-6">
        {tab === 'general' && <GeneralTab />}
        {tab === 'frontends' && <FrontendsTab />}
        {tab === 'sessions' && <SessionsTab />}
        {tab === 'users' && <RegisteredUsersTab />}
      </main>
    </div>
  )
}

function DashboardHeader({ onLogout }: { onLogout: () => void }) {
  const { t } = useT()
  return (
    <header className="bg-uni-dark text-white shadow-md">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">{t('header_title')}</h1>
          <p className="text-xs text-white/60">{t('header_subtitle')}</p>
        </div>
        <div className="flex items-center gap-4">
          <AdminLanguageSelector />
          <button
            onClick={onLogout}
            className="text-sm bg-white/10 hover:bg-white/20 rounded-lg px-3 py-1.5 transition-colors"
          >
            {t('header_logout')}
          </button>
        </div>
      </div>
    </header>
  )
}

function DashboardTabs({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const { t } = useT()
  return (
    <nav className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-6xl mx-auto px-6 flex gap-6">
        <TabButton active={tab === 'general'} onClick={() => setTab('general')}>
          {t('tab_general')}
        </TabButton>
        <TabButton active={tab === 'frontends'} onClick={() => setTab('frontends')}>
          {t('tab_frontends')}
        </TabButton>
        <TabButton active={tab === 'sessions'} onClick={() => setTab('sessions')}>
          {t('tab_sessions')}
        </TabButton>
        <TabButton active={tab === 'users'} onClick={() => setTab('users')}>
          {t('tab_users')}
        </TabButton>
      </div>
    </nav>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`py-3 px-1 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-uni-blue text-uni-blue'
          : 'border-transparent text-gray-500 hover:text-gray-800'
      }`}
    >
      {children}
    </button>
  )
}
