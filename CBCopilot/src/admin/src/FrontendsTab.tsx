// Sprint 4B complete: registry + branding + session-settings + companies +
// per-frontend prompts + RAG + orgs + LLM override.
import { useEffect, useState } from 'react'
import { listFrontends, registerFrontend, updateFrontend, deleteFrontend } from './api'
import type { FrontendInfo } from './api'
import BrandingPanel from './panels/BrandingPanel'
import SessionSettingsPanel from './panels/SessionSettingsPanel'
import CompanyManagementPanel from './panels/CompanyManagementPanel'
import PerFrontendOrgsPanel from './panels/PerFrontendOrgsPanel'
import PerFrontendLLMPanel from './panels/PerFrontendLLMPanel'
import PromptsSection from './sections/PromptsSection'
import RAGSection from './sections/RAGSection'
import TablesSection from './sections/TablesSection'
import { useT } from './i18n'

const POLL_INTERVAL_MS = 10000  // refresh status every 10s

export default function FrontendsTab() {
  const [frontends, setFrontends] = useState<FrontendInfo[]>([])
  const [selected, setSelected] = useState<string>('')
  const [showRegister, setShowRegister] = useState(false)
  const [newUrl, setNewUrl] = useState('')
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const { t } = useT()

  const reload = async () => {
    try {
      const r = await listFrontends()
      setFrontends(r.frontends)
      setSelected(sel => {
        if (sel && r.frontends.some(f => f.frontend_id === sel)) return sel
        return r.frontends[0]?.frontend_id || ''
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    reload()
    const interval = window.setInterval(reload, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const register = async () => {
    if (!newUrl.trim() || !newName.trim()) return
    setError('')
    try {
      const r = await registerFrontend({ url: newUrl.trim(), name: newName.trim() })
      setNewUrl(''); setNewName(''); setShowRegister(false)
      await reload()
      setSelected(r.frontend.frontend_id)
      setInfo(t('frontends_registered_info', { name: r.frontend.name }))
      setTimeout(() => setInfo(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const toggleEnabled = async (frontendId: string, enabled: boolean) => {
    setError('')
    try {
      await updateFrontend(frontendId, { enabled })
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const removeFrontend = async (frontendId: string, displayName: string) => {
    if (!confirm(t('frontends_unregister_confirm', { name: displayName }))) return
    try {
      await deleteFrontend(frontendId)
      if (selected === frontendId) setSelected('')
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const selectedFrontend = frontends.find(f => f.frontend_id === selected)

  return (
    <div className="max-w-5xl space-y-4">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-800">{t('frontends_registered_title')}</h2>
          <button
            onClick={() => setShowRegister(s => !s)}
            className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90"
          >
            {showRegister ? t('generic_cancel') : t('frontends_register_button')}
          </button>
        </div>

        {error && <p className="text-uni-red text-sm mb-2">{error}</p>}
        {info && <p className="text-green-700 text-sm mb-2">{info}</p>}

        {showRegister && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-3">
            <p className="text-xs text-gray-600 mb-3">
              {t('frontends_register_helper')}
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('frontends_register_url_label')}</label>
                <input value={newUrl} onChange={e => setNewUrl(e.target.value)}
                  placeholder={t('frontends_register_url_placeholder')}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('frontends_register_name_label')}</label>
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder={t('frontends_register_name_placeholder')}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
              </div>
            </div>
            <button onClick={register} disabled={!newUrl.trim() || !newName.trim()}
              className="mt-3 text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
              {t('frontends_register_submit')}
            </button>
          </div>
        )}

        {frontends.length === 0 ? (
          <p className="text-sm text-gray-400 py-3">{t('frontends_empty')}</p>
        ) : (
          <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
            {frontends.map(fe => (
              <li
                key={fe.frontend_id}
                onClick={() => setSelected(fe.frontend_id)}
                className={`flex items-center gap-3 px-3 py-2 cursor-pointer ${selected === fe.frontend_id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
              >
                <StatusDot status={fe.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 truncate">{fe.name}</div>
                  <div className="text-xs text-gray-500 truncate">{fe.url}</div>
                </div>
                <div className="text-xs text-gray-400 whitespace-nowrap">
                  {fe.last_seen
                    ? t('frontends_last_seen', { time: new Date(fe.last_seen).toLocaleTimeString() })
                    : t('frontends_last_seen_never')}
                </div>
                <label onClick={e => e.stopPropagation()} className="flex items-center gap-1 text-xs">
                  <input type="checkbox" checked={fe.enabled}
                    onChange={e => toggleEnabled(fe.frontend_id, e.target.checked)} />
                  {t('frontends_enabled_toggle')}
                </label>
                <button
                  onClick={e => { e.stopPropagation(); removeFrontend(fe.frontend_id, fe.name) }}
                  className="text-xs text-uni-red hover:underline"
                >
                  {t('frontends_unregister')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedFrontend && (
        <div className="space-y-4">
          <BrandingPanel frontendId={selectedFrontend.frontend_id} />
          <SessionSettingsPanel frontendId={selectedFrontend.frontend_id} />
          <PromptsSection frontendId={selectedFrontend.frontend_id} />
          <RAGSection frontendId={selectedFrontend.frontend_id} />
          <TablesSection frontendId={selectedFrontend.frontend_id} />
          <PerFrontendOrgsPanel frontendId={selectedFrontend.frontend_id} />
          <PerFrontendLLMPanel frontendId={selectedFrontend.frontend_id} />
          <CompanyManagementPanel frontendId={selectedFrontend.frontend_id} />
        </div>
      )}
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  const color = status === 'online' ? 'bg-green-500' : status === 'offline' ? 'bg-red-500' : 'bg-gray-300'
  return <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${color}`} title={status} />
}
