// Per-frontend LLM override.
// Same UX as the global LLM section, with one extra checkbox per slot:
// - Unchecked → slot shows the global value, greyed out, read-only.
// - Checked  → slot becomes editable; on save the override JSON carries this
//              slot only (other slots stay null and continue inheriting).
//
// Compression and routing settings always inherit from global at the frontend
// tier (not exposed here).
import { useEffect, useState } from 'react'
import {
  getLLMConfig, getLLMDefaults, getProvidersStatus,
  getFrontendLLMOverride, saveFrontendLLMOverride,
  EMPTY_LLM_OVERRIDE,
} from '../api'
import type { LLMConfig, LLMOverride, SlotConfig, ProvidersStatus } from '../api'
import SlotEditor from '../components/llm/SlotEditor'
import ProviderCard from '../components/llm/ProviderCard'

const POLL_INTERVAL_MS = 15000

const SLOT_ORDER: { key: 'inference' | 'compressor' | 'summariser'; label: string; hint: string }[] = [
  { key: 'inference', label: 'Inference', hint: 'Main chat responses.' },
  { key: 'compressor', label: 'Compressor', hint: 'Lightweight model that folds older messages into a running summary at progressive thresholds.' },
  { key: 'summariser', label: 'Summariser', hint: 'Document summaries on injection + final conversation summary emailed to the user.' },
]

type SlotKey = 'inference' | 'compressor' | 'summariser'

export default function PerFrontendLLMPanel({ frontendId }: { frontendId: string }) {
  const [globalCfg, setGlobalCfg] = useState<LLMConfig | null>(null)
  const [defaults, setDefaults] = useState<{ lm_studio: string; ollama: string } | null>(null)
  const [providers, setProviders] = useState<ProvidersStatus | null>(null)
  const [override, setOverride] = useState<LLMOverride>(EMPTY_LLM_OVERRIDE)
  const [dirty, setDirty] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')

  const refreshProviders = async () => {
    try { setProviders(await getProvidersStatus()) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  useEffect(() => {
    setError('')
    setDirty(false)
    Promise.all([
      getLLMConfig(),
      getLLMDefaults(),
      getProvidersStatus(),
      getFrontendLLMOverride(frontendId),
    ])
      .then(([g, d, p, o]) => {
        setGlobalCfg(g)
        setDefaults(d)
        setProviders(p)
        setOverride(o.override)
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))

    const interval = window.setInterval(refreshProviders, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId])

  if (!globalCfg || !defaults) {
    return (
      <div className="border border-gray-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-1">LLM</h4>
        <p className="text-xs text-gray-400">Loading…</p>
      </div>
    )
  }

  const toggleSlot = (key: SlotKey, checked: boolean) => {
    setOverride(o => ({
      ...o,
      // Snapshot global into the override on enable; null on disable.
      [key]: checked ? { ...globalCfg[key] } : null,
    }))
    setDirty(true)
  }

  const updateSlot = (key: SlotKey, patch: Partial<SlotConfig>) => {
    setOverride(o => {
      if (!o[key]) return o  // safety: don't edit an inherited slot
      return { ...o, [key]: { ...o[key]!, ...patch } }
    })
    setDirty(true)
  }

  const save = async () => {
    setSaveStatus('Saving…')
    setError('')
    try {
      const r = await saveFrontendLLMOverride(frontendId, override)
      setOverride(r.override)
      setDirty(false)
      setSaveStatus('Saved')
      setTimeout(() => setSaveStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  const modelsForSlot = (slot: SlotConfig): string[] => {
    if (slot.provider === 'lm_studio') return providers?.lm_studio.models || []
    if (slot.provider === 'ollama') return providers?.ollama.models || []
    return []  // api: would need a per-slot health probe — skipped at this tier
  }

  const overriddenCount = Object.values(override).filter(Boolean).length

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">LLM</h4>
        <span className="text-xs text-gray-500">
          {overriddenCount === 0 ? 'inheriting global' : `${overriddenCount} slot${overriddenCount === 1 ? '' : 's'} overridden ◆`}
          {saveStatus && <span className="ml-2 text-green-700">{saveStatus}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Per-slot opt-in. Tick "Override" on any slot to take it off the global config and edit it for this frontend; leave unticked to inherit.
        Compression and summary-routing always come from the global config at the frontend tier.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <ProviderCard name="LM Studio" info={providers?.lm_studio} />
        <ProviderCard name="Ollama" info={providers?.ollama} />
      </div>

      {error && <p className="text-uni-red text-xs mb-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {SLOT_ORDER.map(({ key, label, hint }) => {
          const isOverridden = override[key] !== null
          const effective: SlotConfig = isOverridden ? override[key]! : globalCfg[key]
          return (
            <SlotEditor
              key={key}
              label={label}
              hint={hint}
              slot={effective}
              onChange={p => updateSlot(key, p)}
              defaults={defaults}
              availableModels={modelsForSlot(effective)}
              disabled={!isOverridden}
              headerRight={
                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isOverridden}
                    onChange={e => toggleSlot(key, e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  Override
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
          Save LLM override
        </button>
        <button
          onClick={refreshProviders}
          className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50"
        >
          Refresh providers
        </button>
      </div>
    </div>
  )
}
