import { useState } from 'react'
import GeneralTab from './GeneralTab'
import FrontendsTab from './FrontendsTab'
import RegisteredUsersTab from './RegisteredUsersTab'

type Tab = 'general' | 'frontends' | 'users'

interface Props {
  onLogout: () => void
}

export default function Dashboard({ onLogout }: Props) {
  const [tab, setTab] = useState<Tab>('general')

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-800">CBC Admin</h1>
          <p className="text-xs text-gray-500">Collective Bargaining Copilot</p>
        </div>
        <button
          onClick={onLogout}
          className="text-sm text-gray-600 hover:text-uni-red transition-colors"
        >
          Sign out
        </button>
      </header>

      <nav className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-6">
          <TabButton active={tab === 'general'} onClick={() => setTab('general')}>
            General
          </TabButton>
          <TabButton active={tab === 'frontends'} onClick={() => setTab('frontends')}>
            Frontends
          </TabButton>
          <TabButton active={tab === 'users'} onClick={() => setTab('users')}>
            Registered Users
          </TabButton>
        </div>
      </nav>

      <main className="p-6">
        {tab === 'general' && <GeneralTab />}
        {tab === 'frontends' && <FrontendsTab />}
        {tab === 'users' && <RegisteredUsersTab />}
      </main>
    </div>
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
