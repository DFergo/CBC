// Single-slot LLM editor (provider / endpoint / model / temp / tokens / ctx).
// Shared between the global LLMSection and the per-frontend LLM panel.
//
// `disabled` greys the whole slot out and stops the model auto-correct from
// firing — used at the per-frontend tier when the slot is showing an inherited
// (read-only) global value.
import { useEffect, useState } from 'react'
import type { SlotConfig, SlotHealth, ProviderType, ApiFlavor } from '../../api'
import { API_KEY_SENTINEL } from '../../api'

const API_FLAVOR_DEFAULTS: Record<ApiFlavor, { endpoint: string; envHint: string }> = {
  anthropic: { endpoint: 'https://api.anthropic.com/v1', envHint: 'ANTHROPIC_API_KEY' },
  openai: { endpoint: 'https://api.openai.com/v1', envHint: 'OPENAI_API_KEY' },
  openai_compatible: { endpoint: '', envHint: 'MY_API_KEY' },
}

interface Props {
  label: string
  hint: string
  slot: SlotConfig
  onChange: (patch: Partial<SlotConfig>) => void
  health?: SlotHealth
  defaults: { lm_studio: string; ollama: string }
  availableModels: string[]
  disabled?: boolean
  // Right-aligned slot in the header (e.g. an Override checkbox at the
  // per-frontend tier). When set, replaces the health badge in that position.
  headerRight?: React.ReactNode
}

export default function SlotEditor({
  label, hint, slot, onChange, health, defaults, availableModels, disabled = false, headerRight,
}: Props) {
  // HRDD-style: if the saved model isn't in the fetched list, auto-correct to
  // the first available. Skipped when disabled — we don't mutate inherited
  // values from another tier.
  useEffect(() => {
    if (disabled) return
    if (availableModels.length > 0 && slot.model && !availableModels.includes(slot.model)) {
      const t = window.setTimeout(() => onChange({ model: availableModels[0] }), 0)
      return () => window.clearTimeout(t)
    }
  }, [availableModels, slot.model, onChange, disabled])

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
    <div className={`border border-gray-200 rounded-lg p-3 space-y-2 ${disabled ? 'bg-gray-50' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <h4 className={`text-sm font-semibold ${disabled ? 'text-gray-500' : 'text-gray-700'}`}>{label}</h4>
        {headerRight ? headerRight : (
          health && (
            <span className={`text-xs px-2 py-0.5 rounded ${health.ok ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
              {health.ok ? 'OK' : health.error ? `ERR: ${health.error.slice(0, 40)}` : `HTTP ${health.status_code}`}
            </span>
          )
        )}
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">{hint}</p>

      <label className="block text-xs text-gray-500">Provider</label>
      <select
        value={slot.provider}
        onChange={e => onProviderChange(e.target.value as ProviderType)}
        disabled={disabled}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
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
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="openai_compatible">OpenAI-compatible</option>
          </select>

          <label className="block text-xs text-gray-500">API endpoint</label>
          <input type="text" value={slot.api_endpoint || ''} onChange={e => onChange({ api_endpoint: e.target.value })}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500" />

          <ApiKeyField slot={slot} onChange={onChange} disabled={disabled} />
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">Endpoint</label>
          <input type="text" value={slot.endpoint} onChange={e => onChange({ endpoint: e.target.value })}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500" />
        </>
      )}

      <label className="block text-xs text-gray-500">
        Model
        {availableModels.length > 0 && (
          <span className="text-gray-400 ml-1">({availableModels.length} available)</span>
        )}
        {availableModels.length === 0 && slot.provider === 'api' && (
          <span className="text-gray-400 ml-1">(click "Check health" once the API key env var is set to populate the list)</span>
        )}
      </label>
      {availableModels.length > 0 ? (
        <select
          value={availableModels.includes(slot.model) ? slot.model : availableModels[0]}
          onChange={e => onChange({ model: e.target.value })}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        >
          {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      ) : (
        <input
          type="text"
          value={slot.model}
          onChange={e => onChange({ model: e.target.value })}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        />
      )}

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-xs text-gray-500">Temp</label>
          <input type="number" step="0.1" min="0" max="2" value={slot.temperature}
            onChange={e => onChange({ temperature: parseFloat(e.target.value) })}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500" />
        </div>
        <div>
          <label className="block text-xs text-gray-500">Max tokens</label>
          <input type="number" min="1" value={slot.max_tokens}
            onChange={e => onChange({ max_tokens: parseInt(e.target.value, 10) })}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500" />
        </div>
        <div>
          <label className="block text-xs text-gray-500">Context</label>
          <input type="number" min="256" value={slot.num_ctx}
            onChange={e => onChange({ num_ctx: parseInt(e.target.value, 10) })}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500" />
        </div>
      </div>
    </div>
  )
}


// Sprint 19 Fase 1 — API key field. Two modes: paste-in-UI (default) and
// env-var-on-container (legacy / Vault). Toggle picks which one is active.
// Paste mode shows a password input with show/hide; on initial load the
// backend sends the sentinel "••••••••" if a key is set, the user can
// either leave it (key preserved on Save) or type a new one (overwrite).
// Env mode is the original Sprint 9 input.
function ApiKeyField({
  slot, onChange, disabled,
}: {
  slot: SlotConfig
  onChange: (patch: Partial<SlotConfig>) => void
  disabled: boolean
}) {
  const flavorHint = API_FLAVOR_DEFAULTS[slot.api_flavor || 'anthropic'].envHint
  // Mode resolution: if the slot already has an api_key set (or sentinel),
  // start in paste mode. Else, if it has api_key_env set, start in env mode.
  // New slots default to paste mode.
  const initialMode: 'paste' | 'env' =
    (slot.api_key || '').length > 0 ? 'paste'
    : (slot.api_key_env || '').length > 0 ? 'env'
    : 'paste'
  const [mode, setMode] = useState<'paste' | 'env'>(initialMode)
  const [reveal, setReveal] = useState(false)

  return (
    <>
      <div className="flex items-center gap-2 mt-1">
        <label className="text-xs text-gray-500">API key source</label>
        <div className="ml-auto flex gap-1 text-[11px]">
          <button
            type="button"
            onClick={() => setMode('paste')}
            disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'paste' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}
          >Paste</button>
          <button
            type="button"
            onClick={() => setMode('env')}
            disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'env' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}
          >Env var</button>
        </div>
      </div>

      {mode === 'paste' ? (
        <>
          <label className="block text-xs text-gray-500">
            API key <span className="text-gray-400">
              ({(slot.api_key || '') === API_KEY_SENTINEL ? 'set; type to replace' : 'pasted, persisted in /app/data/llm_config.json'})
            </span>
          </label>
          <div className="relative">
            <input
              type={reveal ? 'text' : 'password'}
              value={slot.api_key || ''}
              onChange={e => onChange({ api_key: e.target.value })}
              placeholder="sk-..."
              disabled={disabled}
              className="w-full border border-gray-300 rounded-lg pl-2 pr-16 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
            />
            <button
              type="button"
              onClick={() => setReveal(r => !r)}
              disabled={disabled}
              className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[11px] text-gray-500 hover:text-gray-700 disabled:opacity-50"
            >
              {reveal ? 'hide' : 'show'}
            </button>
          </div>
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">
            API key env var name <span className="text-gray-400">(e.g. {flavorHint})</span>
          </label>
          <input
            type="text"
            value={slot.api_key_env || ''}
            onChange={e => onChange({ api_key_env: e.target.value })}
            placeholder={flavorHint}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />
        </>
      )}
    </>
  )
}
