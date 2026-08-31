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
import {
  getBrandingDefaults, saveBrandingDefaults, deleteBrandingDefaults,
  getDefaultsTranslations, putDefaultsTranslations, autoTranslateDefaults,
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

export default function BrandingSection() {
  const [branding, setBranding] = useState<FrontendBranding>(EMPTY)
  const [hasDefaults, setHasDefaults] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

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
      await saveBrandingDefaults(EMPTY)
      setBranding(EMPTY)
      setHasDefaults(true)
      setExpanded(true)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const disableDefaults = async () => {
    if (!confirm(t('branding_disable_confirm'))) return
    setError('')
    try {
      await deleteBrandingDefaults()
      setBranding(EMPTY)
      setHasDefaults(false)
      setExpanded(false)
      setDirty(false)
      setStatus(t('generic_saved'))
      setTimeout(() => setStatus(''), 4000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const save = async () => {
    setStatus('…')
    setError('')
    try {
      await saveBrandingDefaults(branding)
      setHasDefaults(true)
      setDirty(false)
      setStatus(t('generic_saved'))
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
        <h3 className="text-lg font-semibold text-gray-800">{t('branding_defaults_heading')}</h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {hasDefaults ? t('branding_custom_badge') : t('branding_baseline_badge')}
            {status && <span className="ml-2 text-green-700">{status}</span>}
          </span>
          {hasDefaults && (
            <span className={`text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
          )}
        </div>
      </button>
      <p className="text-sm text-gray-500 mb-4">
        {t('branding_defaults_description')}
      </p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <label className="flex items-center gap-2 text-sm mb-3">
        <input
          type="checkbox"
          checked={hasDefaults}
          onChange={e => (e.target.checked ? enableDefaults() : disableDefaults())}
          className="rounded border-gray-300"
        />
        {t('branding_enable_defaults')}
      </label>

      {hasDefaults && expanded && (
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
            onDownload={getDefaultsTranslations}
            onUpload={async (bundle: TranslationBundle) => {
              await putDefaultsTranslations(bundle)
              await reload()
            }}
            onAutoTranslate={async () => {
              const r = await autoTranslateDefaults()
              setStatus(`Auto-translated: +${r.stats.disclaimer_filled} disclaimer, +${r.stats.instructions_filled} instructions. ${r.stats.disclaimer_failed + r.stats.instructions_failed} failures.`)
              setTimeout(() => setStatus(''), 6000)
              await reload()
            }}
            filenameStem="cbc-translations-global"
          />

          <div className="flex gap-2 mt-4">
            <button onClick={save} disabled={!dirty}
              className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
              {t('branding_save_push')}
            </button>
            <button onClick={() => setExpanded(false)}
              className="text-sm border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 hover:bg-gray-50">
              {t('branding_collapse')}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
