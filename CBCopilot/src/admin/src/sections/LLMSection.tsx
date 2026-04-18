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
  LLMConfig, SlotConfig, SlotHealth, ProviderType, ApiFlavor, SlotName,
  CompressionSettings, RoutingToggles, LLMHealth, ProvidersStatus,
} from '../api'

const API_FLAVOR_DEFAULTS: Record<ApiFlavor, { endpoint: string; envHint: string }> = {
  anthropic: { endpoint: 'https://api.anthropic.com/v1', envHint: 'ANTHROPIC_API_KEY' },
  openai: { endpoint: 'https://api.openai.com/v1', envHint: 'OPENAI_API_KEY' },
  openai_compatible: { endpoint: '', envHint: 'MY_API_KEY' },
}

const SLOT_ORDER: { key: 'inference' | 'compressor' | 'summariser'; label: string; hint: string }[] = [
  { key: 'inference', label: 'Inference', hint: 'Main chat responses.' },
  { key: 'compressor', label: 'Compressor', hint: 'Lightweight model that folds older messages into a running summary at progressive thresholds.' },
  { key: 'summariser', label: 'Summariser', hint: 'Document summaries during injection + final conversation summary emailed to the user.' },
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
    setSaveStatus('Saving…')
    setError('')
    try {
      const saved = await saveLLMConfig(cfg)
      setCfg(saved)
      setSaveStatus('Saved')
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
        <h3 className="text-lg font-semibold text-gray-800 mb-1">LLM</h3>
        <p className="text-sm text-gray-400">Loading…</p>
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
        <h3 className="text-lg font-semibold text-gray-800">LLM</h3>
        {saveStatus && <span className="text-xs text-gray-500">{saveStatus}</span>}
      </div>
      <p className="text-sm text-gray-500 mb-4">
        Three slots, each picking one of three provider types independently. API keys live in container env vars — only the variable <em>name</em> is stored here.
      </p>

      {/* Top indicator: LM Studio + Ollama live status + model count */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        <ProviderCard name="LM Studio" info={providers?.lm_studio} />
        <ProviderCard name="Ollama" info={providers?.ollama} />
      </div>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {SLOT_ORDER.map(({ key, label, hint }) => (
          <SlotEditor
            key={key}
            label={label}
            hint={hint}
            slot={cfg[key]}
            onChange={p => updateSlot(key, p)}
            health={health?.[key]}
            defaults={defaults}
            availableModels={modelsForSlot(cfg[key], key)}
          />
        ))}
      </div>

      {/* Context compression */}
      <div className="mt-6 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">Context compression</h4>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={cfg.compression.enabled}
              onChange={e => updateCompression({ enabled: e.target.checked })}
              className="rounded border-gray-300"
            />
            Enabled
          </label>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          When enabled, the conversation is compressed by the slot configured above as "Compressor", using progressive thresholds:
          first compression at <em>first threshold</em> tokens, then every <em>step size</em> tokens after.
          Example: first=20 000, step=15 000 → compressions at 20k, 35k, 50k, 65k, …
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">First threshold (tokens)</label>
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
            <label className="block text-xs text-gray-500 mb-1">Step size (tokens)</label>
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
        <h4 className="text-sm font-semibold text-gray-700 mb-1">Summary routing</h4>
        <p className="text-xs text-gray-500 mb-3">
          Pick which slot handles each summarisation task. The compressor can be used here too — any slot works.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Document summary on injection</label>
            <select
              value={cfg.routing.document_summary_slot}
              onChange={e => updateRouting({ document_summary_slot: e.target.value as SlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Final conversation summary</label>
            <select
              value={cfg.routing.user_summary_slot}
              onChange={e => updateRouting({ user_summary_slot: e.target.value as SlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <button onClick={save} className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90">Save LLM config</button>
        <button onClick={runHealth} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">Check health</button>
        <button onClick={refreshProviders} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">Refresh providers</button>
      </div>
    </section>
  )
}

function ProviderCard({ name, info }: { name: string; info?: { endpoint: string; status: 'online' | 'offline'; models: string[]; error: string | null } }) {
  if (!info) {
    return (
      <div className="border border-gray-200 rounded-lg p-3">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-gray-300" />
          <span className="text-sm font-medium text-gray-800">{name}</span>
        </div>
        <p className="text-xs text-gray-400 mt-1">checking…</p>
      </div>
    )
  }
  const dot = info.status === 'online' ? 'bg-green-500' : 'bg-red-500'
  return (
    <div className="border border-gray-200 rounded-lg p-3">
      <div className="flex items-center gap-2">
        <div className={`w-2.5 h-2.5 rounded-full ${dot}`} />
        <span className="text-sm font-medium text-gray-800">{name}</span>
        <span className="ml-auto text-[11px] text-gray-400 font-mono truncate" title={info.endpoint}>{info.endpoint}</span>
      </div>
      <p className="text-xs text-gray-500 mt-1">
        {info.status === 'online'
          ? `${info.models.length} model${info.models.length === 1 ? '' : 's'} available`
          : (info.error || 'offline')}
      </p>
    </div>
  )
}

interface SlotProps {
  label: string
  hint: string
  slot: SlotConfig
  onChange: (patch: Partial<SlotConfig>) => void
  health?: SlotHealth
  defaults: { lm_studio: string; ollama: string }
  availableModels: string[]
}

function SlotEditor({ label, hint, slot, onChange, health, defaults, availableModels }: SlotProps) {
  // HRDD-style: if the saved model isn't in the fetched list, auto-correct to the first available.
  // Runs once per render when the mismatch is detected; guards against tight loops via setTimeout.
  useEffect(() => {
    if (availableModels.length > 0 && slot.model && !availableModels.includes(slot.model)) {
      const t = window.setTimeout(() => onChange({ model: availableModels[0] }), 0)
      return () => window.clearTimeout(t)
    }
  }, [availableModels, slot.model, onChange])

  const onProviderChange = (provider: ProviderType) => {
    if (provider === 'lm_studio') {
      onChange({ provider, endpoint: defaults.lm_studio })
    } else if (provider === 'ollama') {
      onChange({ provider, endpoint: defaults.ollama })
    } else if (!slot.api_flavor) {
      onChange({
        provider,
        api_flavor: 'anthropic',
        api_endpoint: API_FLAVOR_DEFAULTS.anthropic.endpoint,
        api_key_env: slot.api_key_env || '',
      })
    } else {
      onChange({ provider })
    }
  }

  const onFlavorChange = (flavor: ApiFlavor) => {
    onChange({
      api_flavor: flavor,
      api_endpoint: API_FLAVOR_DEFAULTS[flavor].endpoint || slot.api_endpoint || '',
    })
  }

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-gray-700">{label}</h4>
        {health && (
          <span className={`text-xs px-2 py-0.5 rounded ${health.ok ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            {health.ok ? 'OK' : health.error ? `ERR: ${health.error.slice(0, 40)}` : `HTTP ${health.status_code}`}
          </span>
        )}
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">{hint}</p>

      <label className="block text-xs text-gray-500">Provider</label>
      <select
        value={slot.provider}
        onChange={e => onProviderChange(e.target.value as ProviderType)}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
      >
        <option value="lm_studio">LM Studio (local)</option>
        <option value="ollama">Ollama (local)</option>
        <option value="api">API (remote cloud)</option>
      </select>

      {slot.provider === 'api' ? (
        <>
          <label className="block text-xs text-gray-500">Flavor</label>
          <select
            value={slot.api_flavor || 'anthropic'}
            onChange={e => onFlavorChange(e.target.value as ApiFlavor)}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="openai_compatible">OpenAI-compatible</option>
          </select>

          <label className="block text-xs text-gray-500">API endpoint</label>
          <input type="text" value={slot.api_endpoint || ''} onChange={e => onChange({ api_endpoint: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />

          <label className="block text-xs text-gray-500">
            API key env var name <span className="text-gray-400">(e.g. {API_FLAVOR_DEFAULTS[slot.api_flavor || 'anthropic'].envHint})</span>
          </label>
          <input type="text" value={slot.api_key_env || ''} onChange={e => onChange({ api_key_env: e.target.value })}
            placeholder={API_FLAVOR_DEFAULTS[slot.api_flavor || 'anthropic'].envHint}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono" />
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">Endpoint</label>
          <input type="text" value={slot.endpoint} onChange={e => onChange({ endpoint: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
        </>
      )}

      <label className="block text-xs text-gray-500">
        Model
        {availableModels.length > 0 && (
          <span className="text-gray-400 ml-1">({availableModels.length} available)</span>
        )}
        {availableModels.length === 0 && slot.provider === 'api' && (
          <span className="text-gray-400 ml-1">(click "Check health" below once the API key env var is set to populate the list)</span>
        )}
      </label>
      {availableModels.length > 0 ? (
        <select
          value={availableModels.includes(slot.model) ? slot.model : availableModels[0]}
          onChange={e => onChange({ model: e.target.value })}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono"
        >
          {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      ) : (
        <input
          type="text"
          value={slot.model}
          onChange={e => onChange({ model: e.target.value })}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono"
        />
      )}

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-xs text-gray-500">Temp</label>
          <input type="number" step="0.1" min="0" max="2" value={slot.temperature}
            onChange={e => onChange({ temperature: parseFloat(e.target.value) })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500">Max tokens</label>
          <input type="number" min="1" value={slot.max_tokens}
            onChange={e => onChange({ max_tokens: parseInt(e.target.value, 10) })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500">Context</label>
          <input type="number" min="256" value={slot.num_ctx}
            onChange={e => onChange({ num_ctx: parseInt(e.target.value, 10) })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
        </div>
      </div>
    </div>
  )
}
