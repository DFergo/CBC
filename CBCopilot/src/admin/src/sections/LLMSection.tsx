// SPEC §4.7 + §5.1.
// Three slots (inference / compressor / summariser), each configurable independently.
// Endpoint auto-fills on provider change via /admin/api/v1/llm/defaults.
// Top-level context-compression settings + two summary-routing toggles (3 positions each).
// Top indicator panel polls /providers every 15s (HRDD pattern).
// Model field is a <select> when models are available (HRDD-style: auto-corrects
// to the first available if the saved model isn't in the fetched list). Falls
// back to a text <input> when the list is empty (e.g. API slot before Check health).
import { useEffect, useState } from 'react'
import {
  getLLMConfig, saveLLMConfig, checkLLMHealth, getLLMDefaults, getProvidersStatus,
} from '../api'
import type {
  LLMConfig, SlotConfig, SlotName,
  CompressionSettings, RoutingToggles, LLMHealth, ProvidersStatus,
} from '../api'
import SlotEditor from '../components/llm/SlotEditor'
import ProviderCard from '../components/llm/ProviderCard'
import { useT } from '../i18n'
import type { AdminTranslationKeys } from '../i18n'

const SLOT_ORDER: { key: 'inference' | 'compressor' | 'summariser'; labelKey: AdminTranslationKeys; hintKey: AdminTranslationKeys }[] = [
  { key: 'inference', labelKey: 'llm_slot_inference', hintKey: 'llm_slot_inference_hint' },
  { key: 'compressor', labelKey: 'llm_slot_compressor', hintKey: 'llm_slot_compressor_hint' },
  { key: 'summariser', labelKey: 'llm_slot_summariser', hintKey: 'llm_slot_summariser_hint' },
]

const SLOT_OPTIONS: SlotName[] = ['inference', 'compressor', 'summariser']

const POLL_INTERVAL_MS = 15000

export default function LLMSection() {
  const [cfg, setCfg] = useState<LLMConfig | null>(null)
  const [defaults, setDefaults] = useState<{ lm_studio: string; ollama: string } | null>(null)
  const [providers, setProviders] = useState<ProvidersStatus | null>(null)
  const [health, setHealth] = useState<LLMHealth | null>(null)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')
  const { t } = useT()

  const refreshProviders = async () => {
    try {
      setProviders(await getProvidersStatus())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    Promise.all([getLLMConfig(), getLLMDefaults(), getProvidersStatus()])
      .then(([c, d, p]) => { setCfg(c); setDefaults(d); setProviders(p) })
      .catch(e => setError(String(e)))

    const interval = window.setInterval(refreshProviders, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [])

  const updateSlot = (which: 'inference' | 'compressor' | 'summariser', patch: Partial<SlotConfig>) => {
    setCfg(c => c ? { ...c, [which]: { ...c[which], ...patch } } : c)
  }

  const updateCompression = (patch: Partial<CompressionSettings>) => {
    setCfg(c => c ? { ...c, compression: { ...c.compression, ...patch } } : c)
  }

  const updateRouting = (patch: Partial<RoutingToggles>) => {
    setCfg(c => c ? { ...c, routing: { ...c.routing, ...patch } } : c)
  }

  const save = async () => {
    if (!cfg) return
    setSaveStatus(t('generic_saving'))
    setError('')
    try {
      const saved = await saveLLMConfig(cfg)
      setCfg(saved)
      setSaveStatus(t('generic_saved'))
      setTimeout(() => setSaveStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  const runHealth = async () => {
    setError('')
    setHealth(null)
    try {
      setHealth(await checkLLMHealth())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!cfg || !defaults) {
    return (
      <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">{t('llm_heading')}</h3>
        <p className="text-sm text-gray-400">{t('generic_loading')}</p>
      </section>
    )
  }

  // Map from slot config to models available for that slot (populates datalist)
  const modelsForSlot = (slot: SlotConfig, slotKey: 'inference' | 'compressor' | 'summariser'): string[] => {
    if (slot.provider === 'lm_studio') return providers?.lm_studio.models || []
    if (slot.provider === 'ollama') return providers?.ollama.models || []
    // api — comes from per-slot health probe (requires key env var + Check health click)
    return health?.[slotKey]?.models || []
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-lg font-semibold text-gray-800">{t('llm_heading')}</h3>
        {saveStatus && <span className="text-xs text-gray-500">{saveStatus}</span>}
      </div>
      <p className="text-sm text-gray-500 mb-4">
        {t('llm_description')}
      </p>

      {/* Top indicator: LM Studio + Ollama live status + model count */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        <ProviderCard name="LM Studio" info={providers?.lm_studio} />
        <ProviderCard name="Ollama" info={providers?.ollama} />
      </div>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {SLOT_ORDER.map(({ key, labelKey, hintKey }) => (
          <SlotEditor
            key={key}
            label={t(labelKey)}
            hint={t(hintKey)}
            slot={cfg[key]}
            onChange={p => updateSlot(key, p)}
            health={health?.[key]}
            defaults={defaults}
            availableModels={modelsForSlot(cfg[key], key)}
          />
        ))}
      </div>

      {/* Sprint 13 / Sprint 14 fix — Thinking / Reasoning toggle. Semantics
          expressed as ON/OFF on the switch to match the adjacent dropdown
          and avoid the double-negative confusion of "disable thinking". OFF
          is the default and keeps reasoning out of the chat; ON lets the
          model emit its <think> prelude. Applies across all slots regardless
          of provider. Backend field stays `disable_thinking` (inverted here). */}
      <div className="mt-6 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_thinking_mode')}</h4>
          <select
            value={cfg.disable_thinking ? 'off' : 'on'}
            onChange={e => setCfg(c => c ? { ...c, disable_thinking: e.target.value === 'off' } : c)}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value="off">OFF</option>
            <option value="on">ON</option>
          </select>
        </div>
        <p className="text-xs text-gray-500">
          {t('llm_thinking_mode_description')}
        </p>
      </div>

      {/* Sprint 14 — Max concurrent turns. Backend-wide cap on parallel chat
          turns; must align with the runtime's Parallel setting. */}
      <div className="mt-4 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_max_concurrent_turns')}</h4>
          <select
            value={cfg.max_concurrent_turns}
            onChange={e => setCfg(c => c ? { ...c, max_concurrent_turns: parseInt(e.target.value, 10) as 1 | 2 | 4 | 6 } : c)}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={4}>4</option>
            <option value={6}>6</option>
          </select>
        </div>
        <p className="text-xs text-gray-500">
          {t('llm_max_concurrent_turns_description')}
        </p>
      </div>

      {/* Context compression */}
      <div className="mt-6 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_context_compression')}</h4>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={cfg.compression.enabled}
              onChange={e => updateCompression({ enabled: e.target.checked })}
              className="rounded border-gray-300"
            />
            {t('llm_context_enabled')}
          </label>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          {t('llm_context_description')}
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_context_first_threshold')}</label>
            <input
              type="number"
              min={1000}
              value={cfg.compression.first_threshold}
              onChange={e => updateCompression({ first_threshold: parseInt(e.target.value, 10) })}
              disabled={!cfg.compression.enabled}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_context_step_size')}</label>
            <input
              type="number"
              min={500}
              value={cfg.compression.step_size}
              onChange={e => updateCompression({ step_size: parseInt(e.target.value, 10) })}
              disabled={!cfg.compression.enabled}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-400"
            />
          </div>
        </div>
      </div>

      {/* Summary routing */}
      <div className="mt-4 border border-gray-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-1">{t('llm_summary_routing')}</h4>
        <p className="text-xs text-gray-500 mb-3">
          {t('llm_summary_routing_description')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_document')}</label>
            <select
              value={cfg.routing.document_summary_slot}
              onChange={e => updateRouting({ document_summary_slot: e.target.value as SlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_final')}</label>
            <select
              value={cfg.routing.user_summary_slot}
              onChange={e => updateRouting({ user_summary_slot: e.target.value as SlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_contextual')}</label>
            <select
              value={cfg.routing.contextual_retrieval_slot}
              onChange={e => updateRouting({ contextual_retrieval_slot: e.target.value as SlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <p className="text-[11px] text-gray-500 mt-2">
          {t('llm_summary_contextual_hint')}
        </p>
      </div>

      <div className="flex gap-2 mt-4">
        <button onClick={save} className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90">{t('llm_save_config')}</button>
        <button onClick={runHealth} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">{t('llm_check_health')}</button>
        <button onClick={refreshProviders} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">{t('llm_refresh_providers')}</button>
      </div>
    </section>
  )
}

