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
import { useT } from '../i18n'

export default function SessionSettingsPanel({ frontendId }: { frontendId: string }) {
  const [settings, setSettings] = useState<FrontendSessionSettings>(SESSION_DEFAULTS)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

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
    setStatus('…')
    setError('')
    try {
      await saveFrontendSessionSettings(frontendId, settings)
      setHasOverride(true)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  const reset = async () => {
    if (!confirm(t('confirm_destructive_action'))) return
    try {
      await deleteFrontendSessionSettings(frontendId)
      setSettings(SESSION_DEFAULTS)
      setHasOverride(false)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">{t('session_settings_title')}</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? t('branding_custom_badge') : '—'}
          {status && <span className="ml-2 text-green-700">{status}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        {t('session_settings_description')}
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="space-y-4">
        <NumField
          label={t('field_session_resume_hours')}
          value={settings.session_resume_hours}
          onChange={v => update({ session_resume_hours: v })}
        />
        <NumField
          label={t('field_auto_close_hours')}
          value={settings.auto_close_hours}
          onChange={v => update({ auto_close_hours: v })}
        />
        <NumField
          label={t('field_auto_destroy_hours')}
          value={settings.auto_destroy_hours}
          onChange={v => update({ auto_destroy_hours: v })}
        />
      </div>

      <div className="mt-5 space-y-2">
        <BoolField label={t('field_auth_required')}
          value={settings.auth_required} onChange={v => update({ auth_required: v })} />
        <BoolField label={t('field_disclaimer_enabled')}
          value={settings.disclaimer_enabled} onChange={v => update({ disclaimer_enabled: v })} />
        <BoolField label={t('field_instructions_enabled')}
          value={settings.instructions_enabled} onChange={v => update({ instructions_enabled: v })} />
        <BoolField label={t('field_compare_all_enabled')}
          value={settings.compare_all_enabled} onChange={v => update({ compare_all_enabled: v })} />
        <BoolField label={t('field_cba_sidepanel_enabled')}
          value={settings.cba_sidepanel_enabled} onChange={v => update({ cba_sidepanel_enabled: v })} />
        <div className={settings.cba_sidepanel_enabled ? '' : 'opacity-50 pointer-events-none'}>
          <BoolField
            label={t('field_cba_citations_enabled')}
            value={settings.cba_citations_enabled}
            onChange={v => update({ cba_citations_enabled: v })}
          />
          <p className="text-[11px] text-gray-500 mt-0.5 ml-6">
            {t('field_cba_citations_help')}
          </p>
        </div>
      </div>

      <div className="flex gap-2 mt-5">
        <button onClick={save} disabled={!dirty}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          {t('session_settings_save_push')}
        </button>
        {hasOverride && (
          <button onClick={reset}
            className="text-sm border border-uni-red text-uni-red rounded-lg px-3 py-1.5 hover:bg-red-50">
            {t('session_settings_reset_button')}
          </button>
        )}
      </div>
    </div>
  )
}

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
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
