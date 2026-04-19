// Per-frontend branding override (Sprint 4A + Phase 3 collapsible UI).
// Pattern: single toggle "Override branding" — OFF collapses the card to just
// the title + description + toggle; ON expands the form with all branding
// fields (app title, org name, logo, colors, disclaimer, instructions).
// Empty fields are stripped on save and inherit the lower tier (global default
// → hardcoded baseline). Save also pushes the merged result to the sidecar.
import { useEffect, useState } from 'react'
import { getFrontendBranding, saveFrontendBranding, deleteFrontendBranding } from '../api'
import type { FrontendBranding } from '../api'

const EMPTY: FrontendBranding = {
  app_title: '', org_name: '', logo_url: '', primary_color: '', secondary_color: '',
  disclaimer_text: '', instructions_text: '',
}

export default function BrandingPanel({ frontendId }: { frontendId: string }) {
  const [branding, setBranding] = useState<FrontendBranding>(EMPTY)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    setStatus('')
    getFrontendBranding(frontendId)
      .then(r => {
        setBranding(r.branding ? { ...EMPTY, ...r.branding } : EMPTY)
        setHasOverride(!!r.branding)
        setDirty(false)
      })
      .catch(e => setError(String(e)))
  }, [frontendId])

  const update = (patch: Partial<FrontendBranding>) => {
    setBranding(b => ({ ...b, ...patch }))
    setDirty(true)
  }

  const enableOverride = async () => {
    setError('')
    try {
      await saveFrontendBranding(frontendId, EMPTY)
      setBranding(EMPTY)
      setHasOverride(true)
      setDirty(false)
      setStatus('Override enabled — fields below stack on top of the global default + baseline')
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const disableOverride = async () => {
    if (!confirm('Disable the per-frontend branding override? This frontend will inherit the global default + hardcoded baseline.')) return
    setError('')
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

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">Branding override</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? 'custom ◆' : 'inheriting global default + hardcoded baseline'}
          {status && <span className="ml-2 text-green-700">{status}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Per-frontend branding for this deployment. Each field stacks on top of the global default and the hardcoded baseline —
        leave a field empty to inherit it. The override below covers the app title shown in the header, the organisation name
        shown top-right and in the footer, the logo, the primary/secondary colours, and full custom disclaimer/instructions text
        that will replace the default i18n version when set.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <label className="flex items-center gap-2 text-sm mb-3">
        <input
          type="checkbox"
          checked={hasOverride}
          onChange={e => (e.target.checked ? enableOverride() : disableOverride())}
          className="rounded border-gray-300"
        />
        Override branding for this frontend
      </label>

      {hasOverride && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">App title</label>
              <input type="text" value={branding.app_title} onChange={e => update({ app_title: e.target.value })}
                placeholder="Collective Bargaining Copilot"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">App owner (header right + footer)</label>
              <input type="text" value={branding.org_name} onChange={e => update({ org_name: e.target.value })}
                placeholder="UNI Global Union"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">Logo URL</label>
              <input type="text" value={branding.logo_url} onChange={e => update({ logo_url: e.target.value })}
                placeholder="/assets/logo.png"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Primary color</label>
              <input type="text" value={branding.primary_color} onChange={e => update({ primary_color: e.target.value })}
                placeholder="#003087"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Secondary color</label>
              <input type="text" value={branding.secondary_color} onChange={e => update({ secondary_color: e.target.value })}
                placeholder="#E31837"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">
                Disclaimer text <span className="text-gray-400">(replaces the i18n disclaimer when set)</span>
              </label>
              <textarea
                value={branding.disclaimer_text}
                onChange={e => update({ disclaimer_text: e.target.value })}
                placeholder="Leave empty to inherit the default 3-section disclaimer."
                rows={6}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">
                Instructions text <span className="text-gray-400">(replaces the i18n instructions when set)</span>
              </label>
              <textarea
                value={branding.instructions_text}
                onChange={e => update({ instructions_text: e.target.value })}
                placeholder="Leave empty to inherit the default instructions."
                rows={6}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
              />
            </div>
          </div>

          <div className="flex gap-2 mt-4">
            <button onClick={save} disabled={!dirty}
              className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
              Save + push
            </button>
          </div>
        </>
      )}
    </div>
  )
}
