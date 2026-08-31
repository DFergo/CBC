// Per-frontend organizations override (SPEC §2.4 orgs_mode).
// Reuses the General tab's HRDD-style download/upload JSON pattern.
import { useEffect, useRef, useState } from 'react'
import {
  getFrontendOrgsOverride, saveFrontendOrgsOverride, deleteFrontendOrgsOverride,
  previewOrgsResolution,
} from '../api'
import type { FrontendOrgsOverride, OrgsResolutionResponse, Organization } from '../api'
import { downloadJSON } from '../utils'
import { useT } from '../i18n'

type Mode = 'inherit' | 'own' | 'combine'

export default function PerFrontendOrgsPanel({ frontendId }: { frontendId: string }) {
  const [mode, setMode] = useState<Mode>('inherit')
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [hasOverride, setHasOverride] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [preview, setPreview] = useState<OrgsResolutionResponse | null>(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const uploadRef = useRef<HTMLInputElement>(null)
  const { t } = useT()

  const reload = async () => {
    try {
      const r = await getFrontendOrgsOverride(frontendId)
      if (r.override) {
        setMode(r.override.mode)
        setOrgs(r.override.organizations)
        setHasOverride(true)
      } else {
        setMode('inherit')
        setOrgs([])
        setHasOverride(false)
      }
      setPreview(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId])

  const saveMode = async (newMode: Mode) => {
    setError('')
    try {
      const ov: FrontendOrgsOverride = { mode: newMode, organizations: orgs }
      await saveFrontendOrgsOverride(frontendId, ov)
      setMode(newMode)
      setHasOverride(true)
      setInfo(t('generic_saved'))
      setTimeout(() => setInfo(''), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const removeOverride = async () => {
    if (!confirm(t('orgs_override_remove_confirm'))) return
    try {
      await deleteFrontendOrgsOverride(frontendId)
      await reload()
      setInfo(t('orgs_override_removed'))
      setTimeout(() => setInfo(''), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setInfo('')
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      if (!Array.isArray(data.organizations)) {
        throw new Error(t('orgs_override_invalid_array'))
      }
      for (const o of data.organizations) {
        if (!o.name) throw new Error(t('orgs_override_missing_name', { snippet: JSON.stringify(o).slice(0, 80) }))
      }
      const ov: FrontendOrgsOverride = { mode: mode === 'inherit' ? 'own' : mode, organizations: data.organizations }
      await saveFrontendOrgsOverride(frontendId, ov)
      await reload()
      setInfo(t('orgs_override_uploaded', { count: data.organizations.length }))
      setTimeout(() => setInfo(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const runPreview = async () => {
    setError('')
    try {
      setPreview(await previewOrgsResolution(frontendId))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">{t('orgs_override_heading')}</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? t('branding_custom_badge') : t('orgs_override_inheriting')}
          {info && <span className="ml-2 text-green-700">{info}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        {t('orgs_override_description')}
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <label className="text-xs text-gray-500">{t('orgs_override_mode_label')}</label>
        <select
          value={mode}
          onChange={e => saveMode(e.target.value as Mode)}
          className="border border-gray-300 rounded-lg px-2 py-1 text-sm"
        >
          <option value="inherit">{t('orgs_override_mode_inherit')}</option>
          <option value="own">{t('orgs_override_mode_own')}</option>
          <option value="combine">{t('orgs_override_mode_combine')}</option>
        </select>

        <button onClick={runPreview} className="text-xs border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50">
          {t('orgs_override_preview')}
        </button>
        {hasOverride && (
          <button onClick={removeOverride} className="text-xs border border-uni-red text-uni-red rounded-lg px-3 py-1.5 hover:bg-red-50 ml-auto">
            {t('orgs_override_remove')}
          </button>
        )}
      </div>

      {preview && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs mb-3">
          <strong>{t('orgs_override_resolved_heading', { count: preview.count, mode: preview.mode })}</strong>
          <p className="text-gray-600 mt-1">
            {preview.mode === 'inherit' && t('orgs_override_explain_inherit')}
            {preview.mode === 'own' && t('orgs_override_explain_own')}
            {preview.mode === 'combine' && t('orgs_override_explain_combine')}
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <button
          onClick={() => downloadJSON({ organizations: orgs }, `orgs-${frontendId}.json`)}
          disabled={mode === 'inherit' && orgs.length === 0}
          className="text-xs border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50"
        >
          {t('generic_download_json')}
        </button>
        <label className="text-xs bg-uni-blue text-white rounded-lg px-3 py-1.5 font-medium hover:opacity-90 cursor-pointer">
          {t('generic_upload_json')}
          <input ref={uploadRef} type="file" accept=".json" onChange={handleUpload} className="hidden" />
        </label>
        <span className="text-xs text-gray-500">{t('orgs_override_upload_hint')}</span>
      </div>

      {orgs.length > 0 && (
        <>
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-uni-blue hover:underline mb-2">
            {expanded ? t('orgs_override_hide') : t('orgs_override_show_count', { count: orgs.length })}
          </button>
          {expanded && (
            <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-y-auto">
              {orgs.map((o, i) => (
                <li key={i} className="px-3 py-1.5 text-xs">
                  <span className="font-medium text-gray-800">{o.name}</span>
                  <span className="text-gray-500 ml-2">{o.type}</span>
                  <span className="text-gray-400 ml-2">{o.country}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
