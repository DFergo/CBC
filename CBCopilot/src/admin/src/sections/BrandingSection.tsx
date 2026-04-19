// Global branding defaults (SPEC §5.1 Tab 1).
// Resolution: per-frontend override > global defaults > hardcoded sidecar baseline.
// Per-field merge — empty fields inherit the lower tier rather than blanking it.
// Saving here fans out immediately to every registered frontend that does NOT
// have its own per-frontend override.
//
// UI: collapsible card with chevron in the header. When the toggle is OFF, no
// global defaults exist and the card sits collapsed (title + description +
// toggle only). When the toggle is ON, the field form appears below; the
// chevron lets the admin collapse it back to clean up the General tab without
// disabling the override.
import { useEffect, useState } from 'react'
import { getBrandingDefaults, saveBrandingDefaults, deleteBrandingDefaults } from '../api'
import type { FrontendBranding } from '../api'

const EMPTY: FrontendBranding = {
  app_title: '', org_name: '', logo_url: '', primary_color: '', secondary_color: '',
  disclaimer_text: '', instructions_text: '',
}

export default function BrandingSection() {
  const [branding, setBranding] = useState<FrontendBranding>(EMPTY)
  const [hasDefaults, setHasDefaults] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  const reload = async () => {
    try {
      const r = await getBrandingDefaults()
      setBranding(r.defaults ? { ...EMPTY, ...r.defaults } : EMPTY)
      setHasDefaults(!!r.defaults)
      setExpanded(!!r.defaults)
      setDirty(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { reload() }, [])

  const update = (patch: Partial<FrontendBranding>) => {
    setBranding(b => ({ ...b, ...patch }))
    setDirty(true)
  }

  const enableDefaults = async () => {
    setError('')
    try {
      const r = await saveBrandingDefaults(EMPTY)
      setBranding(EMPTY)
      setHasDefaults(true)
      setExpanded(true)
      setDirty(false)
      setStatus(`Defaults enabled — ${r.pushed_to_frontends} frontend${r.pushed_to_frontends === 1 ? '' : 's'} updated. Fields below stack on top of the hardcoded baseline.`)
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const disableDefaults = async () => {
    if (!confirm('Disable global branding defaults? Frontends without their own override will fall back to the hardcoded baseline.')) return
    setError('')
    try {
      const r = await deleteBrandingDefaults()
      setBranding(EMPTY)
      setHasDefaults(false)
      setExpanded(false)
      setDirty(false)
      setStatus(`Removed — ${r.pushed_to_frontends} frontend${r.pushed_to_frontends === 1 ? '' : 's'} updated`)
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const save = async () => {
    setStatus('Saving…')
    setError('')
    try {
      const r = await saveBrandingDefaults(branding)
      setHasDefaults(true)
      setDirty(false)
      setStatus(`Saved — pushed to ${r.pushed_to_frontends} frontend${r.pushed_to_frontends === 1 ? '' : 's'} (those without their own override)`)
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <button
        type="button"
        onClick={() => hasDefaults && setExpanded(e => !e)}
        disabled={!hasDefaults}
        className="w-full flex items-center justify-between mb-1 text-left disabled:cursor-default"
        aria-expanded={expanded}
      >
        <h3 className="text-lg font-semibold text-gray-800">Branding defaults</h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {hasDefaults ? 'custom ◆' : 'using hardcoded baseline'}
            {status && <span className="ml-2 text-green-700">{status}</span>}
          </span>
          {hasDefaults && (
            <span className={`text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
          )}
        </div>
      </button>
      <p className="text-sm text-gray-500 mb-4">
        System-wide branding applied to every frontend without its own override. Per-frontend overrides (Frontends tab → Branding)
        always win, and any field left empty here inherits the hardcoded baseline. Saving pushes immediately to every registered
        frontend without an override.
      </p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <label className="flex items-center gap-2 text-sm mb-3">
        <input
          type="checkbox"
          checked={hasDefaults}
          onChange={e => (e.target.checked ? enableDefaults() : disableDefaults())}
          className="rounded border-gray-300"
        />
        Use custom branding defaults
      </label>

      {hasDefaults && expanded && (
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
              Save + push to frontends
            </button>
            <button onClick={() => setExpanded(false)}
              className="text-sm border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 hover:bg-gray-50">
              Collapse
            </button>
          </div>
        </>
      )}
    </section>
  )
}
