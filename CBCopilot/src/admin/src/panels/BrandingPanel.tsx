// Per-frontend branding override (Sprint 4A + Phase 3 collapsible UI).
// Pattern: single toggle "Override branding" — OFF collapses the card to just
// the title + description + toggle; ON expands the form with all branding
// fields (app title, org name, logo, colors, disclaimer, instructions).
// Empty fields are stripped on save and inherit the lower tier (global default
// → hardcoded baseline). Save also pushes the merged result to the sidecar.
import { useEffect, useState } from 'react'
import {
  getFrontendBranding, saveFrontendBranding, deleteFrontendBranding,
  getFrontendTranslations, putFrontendTranslations, autoTranslateFrontend,
} from '../api'
import type { FrontendBranding, TranslationBundle } from '../api'
import TranslationBundleControls from '../components/TranslationBundleControls'
import { useT } from '../i18n'

const EMPTY: FrontendBranding = {
  app_title: '', org_name: '', logo_url: '', primary_color: '', secondary_color: '',
  disclaimer_text: '', instructions_text: '',
  source_language: 'en',
  disclaimer_text_translations: {},
  instructions_text_translations: {},
}

export default function BrandingPanel({ frontendId }: { frontendId: string }) {
  const [branding, setBranding] = useState<FrontendBranding>(EMPTY)
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

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
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const disableOverride = async () => {
    if (!confirm(t('confirm_destructive_action'))) return
    setError('')
    try {
      await deleteFrontendBranding(frontendId)
      setBranding(EMPTY)
      setHasOverride(false)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const save = async () => {
    setStatus('…')
    setError('')
    try {
      await saveFrontendBranding(frontendId, branding)
      setHasOverride(true)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">{t('branding_defaults_heading')}</h4>
        <span className="text-xs text-gray-500">
          {hasOverride ? t('branding_custom_badge') : t('branding_baseline_badge')}
          {status && <span className="ml-2 text-green-700">{status}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        {t('branding_defaults_description')}
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <label className="flex items-center gap-2 text-sm mb-3">
        <input
          type="checkbox"
          checked={hasOverride}
          onChange={e => (e.target.checked ? enableOverride() : disableOverride())}
          className="rounded border-gray-300"
        />
        {t('branding_enable_defaults')}
      </label>

      {hasOverride && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('branding_app_title')}</label>
              <input type="text" value={branding.app_title} onChange={e => update({ app_title: e.target.value })}
                placeholder="Collective Bargaining Copilot"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('branding_app_owner')}</label>
              <input type="text" value={branding.org_name} onChange={e => update({ org_name: e.target.value })}
                placeholder="UNI Global Union"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">{t('branding_logo_url')}</label>
              <input type="text" value={branding.logo_url} onChange={e => update({ logo_url: e.target.value })}
                placeholder="/assets/logo.png"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('branding_primary_color')}</label>
              <input type="text" value={branding.primary_color} onChange={e => update({ primary_color: e.target.value })}
                placeholder="#003087"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('branding_secondary_color')}</label>
              <input type="text" value={branding.secondary_color} onChange={e => update({ secondary_color: e.target.value })}
                placeholder="#E31837"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono" />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">
                {t('branding_disclaimer_text')} <span className="text-gray-400">({t('branding_disclaimer_hint')})</span>
              </label>
              <textarea
                value={branding.disclaimer_text}
                onChange={e => update({ disclaimer_text: e.target.value })}
                rows={6}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">
                {t('branding_instructions_text')} <span className="text-gray-400">({t('branding_instructions_hint')})</span>
              </label>
              <textarea
                value={branding.instructions_text}
                onChange={e => update({ instructions_text: e.target.value })}
                rows={6}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
              />
            </div>
          </div>

          <TranslationBundleControls
            sourceLanguage={branding.source_language || 'en'}
            onSourceLanguageChange={code => update({ source_language: code })}
            disclaimerTranslations={branding.disclaimer_text_translations || {}}
            instructionsTranslations={branding.instructions_text_translations || {}}
            disabled={dirty || (!branding.disclaimer_text && !branding.instructions_text)}
            onDownload={() => getFrontendTranslations(frontendId)}
            onUpload={async (bundle: TranslationBundle) => {
              const r = await putFrontendTranslations(frontendId, bundle)
              setBranding({ ...EMPTY, ...r.branding })
              setDirty(false)
            }}
            onAutoTranslate={async () => {
              const r = await autoTranslateFrontend(frontendId)
              setBranding({ ...EMPTY, ...r.branding })
              setDirty(false)
              setStatus(`Auto-translated: +${r.stats.disclaimer_filled} disclaimer, +${r.stats.instructions_filled} instructions. ${r.stats.disclaimer_failed + r.stats.instructions_failed} failures.`)
              setTimeout(() => setStatus(''), 6000)
            }}
            filenameStem={`cbc-translations-${frontendId}`}
          />

          <div className="flex gap-2 mt-4">
            <button onClick={save} disabled={!dirty}
              className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
              {t('session_settings_save_push')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
