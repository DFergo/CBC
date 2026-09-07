// Per-frontend LLM override.
// Same UX as the global LLM section, with one extra checkbox per slot:
// - Unchecked → slot shows the global value, greyed out, read-only.
// - Checked  → slot becomes editable; on save the override JSON carries this
//              slot only (other slots stay null and continue inheriting).
//
// Compression and routing settings always inherit from global at the frontend
// tier (not exposed here). Connections are managed globally (LLMSection); this
// panel only lets a frontend pick a different connection/model per slot.
import { useEffect, useState } from 'react'
import {
  getLLMConfig, getLLMDefaults, getConnections, getConnectionsStatus,
  getFrontendLLMOverride, saveFrontendLLMOverride,
  EMPTY_LLM_OVERRIDE,
} from '../api'
import type { LLMConfig, LLMOverride, SlotConfig, SlotName, LLMConnection, ConnectionsStatus } from '../api'
import SlotEditor from '../components/llm/SlotEditor'
import { useT } from '../i18n'
import type { AdminTranslationKeys } from '../i18n'

const POLL_INTERVAL_MS = 15000

const SLOT_ORDER: { key: SlotName; labelKey: AdminTranslationKeys; hintKey: AdminTranslationKeys }[] = [
  { key: 'inference', labelKey: 'llm_slot_inference', hintKey: 'llm_slot_inference_hint' },
  { key: 'compressor', labelKey: 'llm_slot_compressor', hintKey: 'llm_slot_compressor_hint' },
  { key: 'summariser', labelKey: 'llm_slot_summariser', hintKey: 'llm_slot_summariser_hint' },
  { key: 'translation', labelKey: 'llm_slot_translation', hintKey: 'llm_slot_translation_hint' },
]

export default function PerFrontendLLMPanel({ frontendId }: { frontendId: string }) {
  const [globalCfg, setGlobalCfg] = useState<LLMConfig | null>(null)
  const [defaults, setDefaults] = useState<{ lm_studio: string; ollama: string } | null>(null)
  const [connections, setConnections] = useState<LLMConnection[]>([])
  const [status, setStatus] = useState<ConnectionsStatus | null>(null)
  const [override, setOverride] = useState<LLMOverride>(EMPTY_LLM_OVERRIDE)
  const [dirty, setDirty] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

  const refreshStatus = async () => {
    try { setStatus(await getConnectionsStatus()) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  useEffect(() => {
    setError('')
    setDirty(false)
    Promise.all([
      getLLMConfig(),
      getLLMDefaults(),
      getConnections(),
      getConnectionsStatus(),
      getFrontendLLMOverride(frontendId),
    ])
      .then(([g, d, conns, st, o]) => {
        setGlobalCfg(g)
        setDefaults(d)
        setConnections(conns)
        setStatus(st)
        setOverride(o.override)
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))

    const interval = window.setInterval(refreshStatus, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId])

  if (!globalCfg || !defaults) {
    return (
      <div className="border border-gray-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-1">{t('llm_override_heading')}</h4>
        <p className="text-xs text-gray-400">{t('generic_loading')}</p>
      </div>
    )
  }

  const toggleSlot = (key: SlotName, checked: boolean) => {
    setOverride(o => ({
      ...o,
      // Snapshot global into the override on enable; null on disable.
      [key]: checked ? { ...globalCfg[key] } : null,
    }))
    setDirty(true)
  }

  const updateSlot = (key: SlotName, patch: Partial<SlotConfig>) => {
    setOverride(o => {
      if (!o[key]) return o  // safety: don't edit an inherited slot
      return { ...o, [key]: { ...o[key]!, ...patch } }
    })
    setDirty(true)
  }

  const save = async () => {
    setSaveStatus(t('generic_saving'))
    setError('')
    try {
      const r = await saveFrontendLLMOverride(frontendId, override)
      setOverride(r.override)
      setDirty(false)
      setSaveStatus(t('generic_saved'))
      setTimeout(() => setSaveStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  const overriddenCount = Object.values(override).filter(Boolean).length

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">{t('llm_override_heading')}</h4>
        <span className="text-xs text-gray-500">
          {overriddenCount === 0
            ? t('llm_override_inheriting')
            : overriddenCount === 1
              ? t('llm_override_count_one', { count: overriddenCount })
              : t('llm_override_count_other', { count: overriddenCount })}
          {saveStatus && <span className="ml-2 text-green-700">{saveStatus}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        {t('llm_override_description')}
      </p>

      {error && <p className="text-uni-red text-xs mb-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-3">
        {SLOT_ORDER.map(({ key, labelKey, hintKey }) => {
          const isOverridden = override[key] !== null
          const effective: SlotConfig = isOverridden ? override[key]! : globalCfg[key]
          return (
            <SlotEditor
              key={key}
              label={t(labelKey)}
              hint={t(hintKey)}
              slot={effective}
              onChange={p => updateSlot(key, p)}
              connections={connections}
              status={status}
              disabled={!isOverridden}
              headerRight={
                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isOverridden}
                    onChange={e => toggleSlot(key, e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  {t('llm_override_label')}
                </label>
              }
            />
          )
        })}
      </div>

      <div className="flex gap-2 mt-4">
        <button
          onClick={save}
          disabled={!dirty}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
        >
          {t('llm_override_save')}
        </button>
        <button
          onClick={refreshStatus}
          className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50"
        >
          {t('llm_override_refresh_providers')}
        </button>
      </div>
    </div>
  )
}
