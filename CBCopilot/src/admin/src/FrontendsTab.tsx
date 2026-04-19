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

const POLL_INTERVAL_MS = 10000  // refresh status every 10s

export default function FrontendsTab() {
  const [frontends, setFrontends] = useState<FrontendInfo[]>([])
  const [selected, setSelected] = useState<string>('')
  const [showRegister, setShowRegister] = useState(false)
  const [newFid, setNewFid] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

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
    if (!newFid.trim() || !newUrl.trim()) return
    setError('')
    try {
      await registerFrontend({ frontend_id: newFid.trim(), url: newUrl.trim(), name: newName.trim() })
      const fid = newFid.trim()
      setNewFid(''); setNewUrl(''); setNewName(''); setShowRegister(false)
      await reload()
      setSelected(fid)
      setInfo('Registered')
      setTimeout(() => setInfo(''), 2000)
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

  const removeFrontend = async (frontendId: string) => {
    if (!confirm(`Unregister frontend "${frontendId}"? Backend will stop polling it. Per-frontend config in /app/data/campaigns/${frontendId}/ is NOT deleted.`)) return
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
          <h2 className="text-lg font-semibold text-gray-800">Registered frontends</h2>
          <button
            onClick={() => setShowRegister(s => !s)}
            className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90"
          >
            {showRegister ? 'Cancel' : '+ Register frontend'}
          </button>
        </div>

        {error && <p className="text-uni-red text-sm mb-2">{error}</p>}
        {info && <p className="text-green-700 text-sm mb-2">{info}</p>}

        {showRegister && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-3">
            <p className="text-xs text-gray-600 mb-3">
              Register a frontend by providing the stable <code>frontend_id</code> from its <code>deployment_frontend.json</code>,
              the URL where its sidecar is reachable from this backend container, and an optional human-readable name.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">frontend_id</label>
                <input value={newFid} onChange={e => setNewFid(e.target.value)}
                  placeholder="packaging-eu"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">URL (sidecar reachable here)</label>
                <input value={newUrl} onChange={e => setNewUrl(e.target.value)}
                  placeholder="http://cbc-frontend"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Display name (optional)</label>
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="Packaging — Europe"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
              </div>
            </div>
            <button onClick={register} disabled={!newFid.trim() || !newUrl.trim()}
              className="mt-3 text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
              Register
            </button>
          </div>
        )}

        {frontends.length === 0 ? (
          <p className="text-sm text-gray-400 py-3">No frontends registered yet. Click "+ Register frontend" to add one.</p>
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
                  <div className="text-sm font-medium text-gray-800 truncate">
                    {fe.name} <code className="text-xs text-gray-400 font-mono ml-1">{fe.frontend_id}</code>
                  </div>
                  <div className="text-xs text-gray-500 truncate">{fe.url}</div>
                </div>
                <div className="text-xs text-gray-400 whitespace-nowrap">
                  {fe.last_seen ? `last seen ${new Date(fe.last_seen).toLocaleTimeString()}` : '—'}
                </div>
                <label onClick={e => e.stopPropagation()} className="flex items-center gap-1 text-xs">
                  <input type="checkbox" checked={fe.enabled}
                    onChange={e => toggleEnabled(fe.frontend_id, e.target.checked)} />
                  enabled
                </label>
                <button
                  onClick={e => { e.stopPropagation(); removeFrontend(fe.frontend_id) }}
                  className="text-xs text-uni-red hover:underline"
                >
                  Unregister
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
