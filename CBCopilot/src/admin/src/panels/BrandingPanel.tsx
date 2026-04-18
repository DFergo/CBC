import { useEffect, useState } from 'react'
import { getFrontendBranding, saveFrontendBranding, deleteFrontendBranding } from '../api'
import type { FrontendBranding } from '../api'

const EMPTY: FrontendBranding = { app_title: '', logo_url: '', primary_color: '', secondary_color: '' }

export default function BrandingPanel({ frontendId }: { frontendId: string }) {
  const [branding, setBranding] = useState<FrontendBranding>(EMPTY)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getFrontendBranding(frontendId)
      .then(r => {
        setBranding(r.branding || EMPTY)
        setHasOverride(!!r.branding)
        setDirty(false)
      })
      .catch(e => setError(String(e)))
  }, [frontendId])

  const update = (patch: Partial<FrontendBranding>) => {
    setBranding(b => ({ ...b, ...patch }))
    setDirty(true)
  }

  const save = async () => {
    setStatus('Saving…')
    setError('')
    try {
      await saveFrontendBranding(frontendId, branding)
      setHasOverride(true)
      setDirty(false)
      setStatus('Saved — pushed to sidecar')
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  const remove = async () => {
    if (!confirm('Remove branding override? This frontend will fall back to its deployment_frontend.json baseline.')) return
    try {
      await deleteFrontendBranding(frontendId)
      setBranding(EMPTY)
      setHasOverride(false)
      setDirty(false)
      setStatus('Override removed')
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-gray-700">Branding override</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? 'custom ◆' : 'using deployment_frontend.json baseline'}
          {status && <span className="ml-2 text-gray-600">{status}</span>}
        </span>
      </div>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">App title</label>
          <input type="text" value={branding.app_title} onChange={e => update({ app_title: e.target.value })}
            placeholder="CBC — Packaging EU"
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Logo URL</label>
          <input type="text" value={branding.logo_url} onChange={e => update({ logo_url: e.target.value })}
            placeholder="/assets/logo.png"
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Primary color</label>
          <input type="text" value={branding.primary_color} onChange={e => update({ primary_color: e.target.value })}
            placeholder="#1e40af"
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Secondary color</label>
          <input type="text" value={branding.secondary_color} onChange={e => update({ secondary_color: e.target.value })}
            placeholder="#f59e0b"
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <button onClick={save} disabled={!dirty}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          Save + push
        </button>
        {hasOverride && (
          <button onClick={remove}
            className="text-sm border border-uni-red text-uni-red rounded-lg px-3 py-1.5 hover:bg-red-50">
            Remove override
          </button>
        )}
      </div>
    </div>
  )
}
