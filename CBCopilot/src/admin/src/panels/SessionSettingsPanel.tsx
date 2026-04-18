import { useEffect, useState } from 'react'
import { getFrontendSessionSettings, saveFrontendSessionSettings, deleteFrontendSessionSettings } from '../api'
import type { FrontendSessionSettings } from '../api'

const EMPTY: FrontendSessionSettings = {
  auth_required: null,
  session_resume_hours: null,
  auto_close_hours: null,
  auto_destroy_hours: null,
  disclaimer_enabled: null,
  instructions_enabled: null,
  compare_all_enabled: null,
}

export default function SessionSettingsPanel({ frontendId }: { frontendId: string }) {
  const [settings, setSettings] = useState<FrontendSessionSettings>(EMPTY)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getFrontendSessionSettings(frontendId)
      .then(r => {
        setSettings(r.settings || EMPTY)
        setHasOverride(!!r.settings)
        setDirty(false)
      })
      .catch(e => setError(String(e)))
  }, [frontendId])

  const update = (patch: Partial<FrontendSessionSettings>) => {
    setSettings(s => ({ ...s, ...patch }))
    setDirty(true)
  }

  const save = async () => {
    setStatus('Saving…')
    setError('')
    try {
      await saveFrontendSessionSettings(frontendId, settings)
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
    if (!confirm('Remove session-settings override? This frontend will fall back to its deployment_frontend.json baseline.')) return
    try {
      await deleteFrontendSessionSettings(frontendId)
      setSettings(EMPTY)
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
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">Session settings + feature toggles</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? 'custom ◆' : 'using deployment_frontend.json baseline'}
          {status && <span className="ml-2 text-gray-600">{status}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Any field left empty or set to "inherit" uses the baseline from the frontend's <code>deployment_frontend.json</code>.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <NumField label="Session resume (hours)" value={settings.session_resume_hours}
          onChange={v => update({ session_resume_hours: v })} placeholder="48" />
        <NumField label="Auto-close (hours idle)" value={settings.auto_close_hours}
          onChange={v => update({ auto_close_hours: v })} placeholder="72" />
        <NumField label="Auto-destroy (hours, 0=never)" value={settings.auto_destroy_hours}
          onChange={v => update({ auto_destroy_hours: v })} placeholder="0" />
      </div>

      <div className="space-y-2">
        <BoolField label="Auth required (email verification)" value={settings.auth_required}
          onChange={v => update({ auth_required: v })} />
        <BoolField label="Disclaimer page enabled" value={settings.disclaimer_enabled}
          onChange={v => update({ disclaimer_enabled: v })} />
        <BoolField label="Instructions page enabled" value={settings.instructions_enabled}
          onChange={v => update({ instructions_enabled: v })} />
        <BoolField label='"Compare All" button visible on CompanySelectPage' value={settings.compare_all_enabled}
          onChange={v => update({ compare_all_enabled: v })} />
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

function NumField({ label, value, onChange, placeholder }: { label: string; value: number | null; onChange: (v: number | null) => void; placeholder?: string }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <input
        type="number"
        min={0}
        value={value ?? ''}
        placeholder={placeholder ? `inherit (${placeholder})` : 'inherit'}
        onChange={e => {
          const raw = e.target.value.trim()
          onChange(raw === '' ? null : parseInt(raw, 10))
        }}
        className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
      />
    </div>
  )
}

function BoolField({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean | null) => void }) {
  const display = value === null ? 'inherit' : value ? 'true' : 'false'
  return (
    <div className="flex items-center gap-3">
      <select
        value={display}
        onChange={e => {
          const v = e.target.value
          onChange(v === 'inherit' ? null : v === 'true')
        }}
        className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-28"
      >
        <option value="inherit">inherit</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
      <span className="text-sm text-gray-700">{label}</span>
    </div>
  )
}
