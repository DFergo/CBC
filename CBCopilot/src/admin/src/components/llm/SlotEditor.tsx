// Single-slot LLM editor (provider / endpoint / model / temp / tokens / ctx).
// Shared between the global LLMSection and the per-frontend LLM panel.
//
// `disabled` greys the whole slot out and stops the model auto-correct from
// firing — used at the per-frontend tier when the slot is showing an inherited
// (read-only) global value.
import { useEffect, useState } from 'react'
import type { SlotConfig, SlotHealth, ProviderType, ApiFlavor } from '../../api'
import { API_KEY_SENTINEL, probeSlot } from '../../api'

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
  // Sprint 19 followup — fired when the admin picks a different provider
  // for this slot. Parent uses it to refetch `providers/` so the model
  // dropdown repopulates with the new provider's catalogue immediately
  // (otherwise the admin has to wait for the next 15-s polling cycle).
  onProviderSwitched?: () => void
}

export default function SlotEditor({
  label, hint, slot, onChange, health, defaults, availableModels, disabled = false, headerRight,
  onProviderSwitched,
}: Props) {
  // Sprint 19 followup — local state for the "Test connection" probe of
  // in-progress API configs. Models discovered via probe merge with the
  // padre's `availableModels` so the dropdown shows them immediately, even
  // before Save. Probe status drives a small pill next to the button.
  const [probeStatus, setProbeStatus] = useState<'idle' | 'probing' | 'ok' | 'error'>('idle')
  const [probeMessage, setProbeMessage] = useState<string>('')
  const [probedModels, setProbedModels] = useState<string[]>([])

  // Reset probe state whenever the slot's identity changes (provider /
  // flavor / endpoint / key_env). Old results stop being valid the moment
  // any of those fields move.
  useEffect(() => {
    setProbeStatus('idle')
    setProbeMessage('')
    setProbedModels([])
  }, [slot.provider, slot.api_flavor, slot.api_endpoint, slot.api_key_env])

  const runProbe = async () => {
    setProbeStatus('probing')
    setProbeMessage('')
    try {
      const r = await probeSlot({
        provider: slot.provider,
        // Don't send `model: ""` — backend validator might trip on empty.
        // Send everything else so check_slot_health can do its work.
        api_flavor: slot.api_flavor || null,
        api_endpoint: slot.api_endpoint || null,
        api_key: slot.api_key || null,
        api_key_env: slot.api_key_env || null,
        endpoint: slot.endpoint,
      } as Partial<SlotConfig>)
      if (r.ok) {
        setProbeStatus('ok')
        setProbeMessage(`${r.models.length} model${r.models.length === 1 ? '' : 's'}`)
        setProbedModels(r.models)
      } else {
        setProbeStatus('error')
        setProbeMessage(r.error?.slice(0, 80) || `HTTP ${r.status_code}`)
      }
    } catch (e) {
      setProbeStatus('error')
      setProbeMessage(e instanceof Error ? e.message.slice(0, 80) : 'probe failed')
    }
  }

  // Merge availableModels (from parent's providers state) with probedModels
  // (from this component's transient Test). Dedup, preserve order — parent
  // first because if a config is already saved, parent has the authoritative
  // list. Probed models extend it for unsaved drafts.
  const dropdownModels = (() => {
    if (probedModels.length === 0) return availableModels
    const seen = new Set(availableModels)
    const merged = [...availableModels]
    for (const m of probedModels) if (!seen.has(m)) { seen.add(m); merged.push(m) }
    return merged
  })()
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
    // Sprint 19 followup — when the admin switches provider, reset the
    // `model` field and any provider-specific fields. The previous behaviour
    // left `model` set to whatever it was for the OLD provider (e.g.
    // "qwen3.6:27b" from Ollama), so saving against a different provider
    // (api/MiniMax) produced a config the API rejects with 400. Daniel hit
    // this twice. Now: model="" forces the admin to pick a value valid for
    // the NEW provider before Save, and the parent re-fetches
    // `providers/` so the dropdown repopulates with the right model list.
    if (provider === 'lm_studio') {
      onChange({
        provider,
        model: '',
        endpoint: defaults.lm_studio,
        // Wipe API-only fields so the persisted config is clean.
        api_flavor: null,
        api_endpoint: null,
        api_key: null,
        api_key_env: null,
      })
    } else if (provider === 'ollama') {
      onChange({
        provider,
        model: '',
        endpoint: defaults.ollama,
        api_flavor: null,
        api_endpoint: null,
        api_key: null,
        api_key_env: null,
      })
    } else {
      // provider === 'api'. Default to anthropic flavor + its endpoint when
      // we don't have one yet. Always reset model — the previous local-
      // provider model id won't exist in any cloud catalogue.
      onChange({
        provider,
        model: '',
        api_flavor: slot.api_flavor || 'anthropic',
        api_endpoint: slot.api_endpoint || API_FLAVOR_DEFAULTS[slot.api_flavor || 'anthropic'].endpoint,
        api_key_env: slot.api_key_env || '',
      })
    }
    // Tell the parent to refresh the providers status so the dropdown
    // populates with the new provider's models without waiting for the
    // 15-s polling cycle.
    onProviderSwitched?.()
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

          {/* Sprint 19 followup — Test connection. Probes endpoint+flavor+key
              live without needing Save first. Populates the dropdown below. */}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={runProbe}
              disabled={disabled || probeStatus === 'probing'}
              className="px-2 py-1 text-xs border border-gray-300 text-gray-700 rounded disabled:opacity-50 hover:bg-gray-50"
            >
              {probeStatus === 'probing' ? 'Testing…' : 'Test connection'}
            </button>
            {probeStatus === 'ok' && (
              <span className="text-[11px] px-2 py-0.5 rounded bg-green-100 text-green-700">
                OK · {probeMessage}
              </span>
            )}
            {probeStatus === 'error' && (
              <span className="text-[11px] px-2 py-0.5 rounded bg-red-100 text-red-700">
                {probeMessage}
              </span>
            )}
          </div>
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
        {dropdownModels.length > 0 && (
          <span className="text-gray-400 ml-1">({dropdownModels.length} available)</span>
        )}
        {dropdownModels.length === 0 && slot.provider === 'api' && (
          <span className="text-gray-400 ml-1">(fill endpoint + flavor + API key, click "Test connection" to populate)</span>
        )}
      </label>
      {dropdownModels.length > 0 ? (
        <select
          value={dropdownModels.includes(slot.model) ? slot.model : (slot.model || dropdownModels[0])}
          onChange={e => onChange({ model: e.target.value })}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        >
          {dropdownModels.map(m => <option key={m} value={m}>{m}</option>)}
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
