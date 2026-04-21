// Per-frontend session + feature settings (Sprint 4A).
// All fields are concrete (no inherit/null). Defaults match
// deployment_frontend.json baseline. RAG-related settings live in the RAG
// section of this tier — not here.
import { useEffect, useState } from 'react'
import {
  getFrontendSessionSettings,
  saveFrontendSessionSettings,
  deleteFrontendSessionSettings,
  SESSION_DEFAULTS,
} from '../api'
import type { FrontendSessionSettings } from '../api'

export default function SessionSettingsPanel({ frontendId }: { frontendId: string }) {
  const [settings, setSettings] = useState<FrontendSessionSettings>(SESSION_DEFAULTS)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    setStatus('')
    getFrontendSessionSettings(frontendId)
      .then(r => {
        setSettings(r.settings ? { ...SESSION_DEFAULTS, ...r.settings } : SESSION_DEFAULTS)
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

  const reset = async () => {
    if (!confirm('Reset session settings to defaults? The override file is deleted; the panel below shows the defaults.')) return
    try {
      await deleteFrontendSessionSettings(frontendId)
      setSettings(SESSION_DEFAULTS)
      setHasOverride(false)
      setDirty(false)
      setStatus('Reset to defaults')
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
          {hasOverride ? 'custom ◆' : 'defaults'}
          {status && <span className="ml-2 text-green-700">{status}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Per-frontend behaviour. Defaults are 48 / 72 / 0 hours and all toggles ON; change here to override for this deployment.
        RAG resolution settings live in the RAG section below.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="space-y-4">
        <NumField
          label="Session resume (hours)"
          help="How long after creating a session the user can come back with the same token and pick up where they left off. After this window the token stops working."
          value={settings.session_resume_hours}
          onChange={v => update({ session_resume_hours: v })}
        />
        <NumField
          label="Session auto-close (hours idle)"
          help="How long the session can stay idle before being marked complete. When it closes, the user-summary prompt runs and the summary is emailed (if the user provided their email)."
          value={settings.auto_close_hours}
          onChange={v => update({ auto_close_hours: v })}
        />
        <NumField
          label="Session auto-destroy (hours, 0 = never)"
          help="Privacy wipe. After the session closes, wait this many hours then delete the conversation, uploads, and any session-derived RAG. 0 = keep indefinitely."
          value={settings.auto_destroy_hours}
          onChange={v => update({ auto_destroy_hours: v })}
        />
      </div>

      <div className="mt-5 space-y-2">
        <BoolField label="Auth required (email verification)"
          value={settings.auth_required} onChange={v => update({ auth_required: v })} />
        <BoolField label="Disclaimer page enabled"
          value={settings.disclaimer_enabled} onChange={v => update({ disclaimer_enabled: v })} />
        <BoolField label="Instructions page enabled"
          value={settings.instructions_enabled} onChange={v => update({ instructions_enabled: v })} />
        <BoolField label='"Compare All" button visible on CompanySelectPage'
          value={settings.compare_all_enabled} onChange={v => update({ compare_all_enabled: v })} />
        <BoolField label="CBA sidepanel in chat (lists cited documents + download, click-to-highlight)"
          value={settings.cba_sidepanel_enabled} onChange={v => update({ cba_sidepanel_enabled: v })} />
        <div className={settings.cba_sidepanel_enabled ? '' : 'opacity-50 pointer-events-none'}>
          <BoolField
            label="Ask the LLM to cite page / article numbers in responses"
            value={settings.cba_citations_enabled}
            onChange={v => update({ cba_citations_enabled: v })}
          />
          <p className="text-[11px] text-gray-500 mt-0.5 ml-6">
            Only takes effect when the CBA sidepanel is on. When on, the prompt asks the LLM to
            append <code>[filename, p. N]</code> / <code>[filename, Art. N]</code> brackets inline;
            the UI renders them as clickable pills that jump to the matching document in the
            sidepanel. LLMs occasionally miss the format — the panel + downloads keep working
            regardless.
          </p>
        </div>
      </div>

      <div className="flex gap-2 mt-5">
        <button onClick={save} disabled={!dirty}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          Save + push
        </button>
        {hasOverride && (
          <button onClick={reset}
            className="text-sm border border-uni-red text-uni-red rounded-lg px-3 py-1.5 hover:bg-red-50">
            Reset to defaults
          </button>
        )}
      </div>
    </div>
  )
}

function NumField({ label, help, value, onChange }: { label: string; help: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-0.5">{label}</label>
      <p className="text-[11px] text-gray-500 mb-1.5">{help}</p>
      <input
        type="number"
        min={0}
        value={value}
        onChange={e => onChange(parseInt(e.target.value, 10) || 0)}
        className="w-32 border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
      />
    </div>
  )
}

function BoolField({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        onChange={e => onChange(e.target.checked)}
        className="rounded border-gray-300"
      />
      <span className="text-gray-700">{label}</span>
    </label>
  )
}
