// Single-slot LLM editor (connection / model / temp / tokens / ctx / reasoning).
// Shared between the global LLMSection and the per-frontend LLM panel.
//
// The slot only picks a connection (from the registry, see ConnectionsCard)
// and a model within it — provider/endpoint/api_key live on the connection
// record now, not on the slot.
//
// `disabled` greys the whole slot out and stops the model auto-correct from
// firing — used at the per-frontend tier when the slot is showing an inherited
// (read-only) global value.
import { useEffect, useState } from 'react'
import ModelCombobox from '../ModelCombobox'
import { getSlotCapabilities } from '../../api'
import type {
  SlotConfig, SlotHealth, LLMConnection, ConnectionsStatus, SlotCapabilities, ControlStatus, ReasoningLevel,
} from '../../api'

const inputCls = 'w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500'

// Sprint 22: what happens to a control on this provider/model (from the backend).
function StatusLine({ st }: { st?: ControlStatus }) {
  if (!st || st.status === 'not sent (default)' || (st.status === 'sent' && !st.note)) return null
  return (
    <p className={`text-[11px] leading-snug mt-0.5 ${st.status === 'ignored' ? 'text-amber-600' : 'text-gray-400'}`}>
      {st.status === 'ignored' ? 'Ignored: ' : ''}{st.note}
    </p>
  )
}

// Number input where blank = null ("don't send").
function NumField({ label, value, onChange, disabled, step, min, placeholder, status }: {
  label: string; value: number | null; onChange: (v: number | null) => void; disabled: boolean
  step?: string; min?: string; placeholder?: string; status?: ControlStatus
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500">{label}</label>
      <input type="number" step={step} min={min} value={value ?? ''} placeholder={placeholder ?? 'default'}
        onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))}
        disabled={disabled} className={inputCls} />
      <StatusLine st={status} />
    </div>
  )
}

interface Props {
  label: string
  hint: string
  slot: SlotConfig
  onChange: (patch: Partial<SlotConfig>) => void
  health?: SlotHealth
  connections: LLMConnection[]
  status: ConnectionsStatus | null
  disabled?: boolean
  // Right-aligned slot in the header (e.g. an Override checkbox at the
  // per-frontend tier). When set, replaces the health badge in that position.
  headerRight?: React.ReactNode
  // Bottom-of-card slot (e.g. a per-slot Save button). Keeps Save next to the
  // fields it applies to instead of one button at the bottom of the page.
  footer?: React.ReactNode
}

export default function SlotEditor({
  label, hint, slot, onChange, health, connections, status, disabled = false, headerRight, footer,
}: Props) {
  const activeConnection = connections.find(c => c.id === slot.connection_id)
  const connModels = (() => {
    if (!activeConnection) return []
    if (activeConnection.model_ids.length > 0) return activeConnection.model_ids
    return status?.[activeConnection.id]?.models || []
  })()
  // Everything the endpoint reports, even when the connection has an allow-list.
  const discoveredModels = (activeConnection && status?.[activeConnection.id]?.models) || []

  // HRDD-style: if the model is blank (just switched connection) or the
  // saved model isn't in the fetched list, auto-correct to the first
  // available — and actually persist it via onChange. Previously this only
  // fired when `slot.model` was truthy, so a blank model (the state right
  // after switching connections) never got corrected: the <select> below
  // LOOKS like it shows a model (render-time fallback to connModels[0]) but
  // that value was never written back to state, so Save silently persisted
  // an empty model — which is exactly what broke OpenRouter (400 Bad
  // Request: empty `model` in the request body). Skipped when disabled —
  // we don't mutate inherited values from another tier.
  useEffect(() => {
    if (disabled) return
    // Only a BLANK model is filled in: an exact ID the connection doesn't list
    // is a deliberate choice (the model field accepts it and warns).
    if (connModels.length > 0 && !slot.model) {
      const t = window.setTimeout(() => onChange({ model: connModels[0] }), 0)
      return () => window.clearTimeout(t)
    }
  }, [connModels, slot.model, onChange, disabled])

  // Sprint 22: ask the backend which controls apply to this connection + model,
  // with the values being edited, so no setting is a silent no-op.
  const [caps, setCaps] = useState<SlotCapabilities | null>(null)
  const capsInput = JSON.stringify({
    connection: slot.connection_id, model: slot.model, temperature: slot.temperature ?? null,
    max_tokens: slot.max_tokens ?? null, num_ctx: slot.num_ctx ?? null, reasoning: slot.reasoning ?? null,
  })
  useEffect(() => {
    if (!slot.connection_id) { setCaps(null); return }
    const t = window.setTimeout(() => {
      getSlotCapabilities(JSON.parse(capsInput)).then(setCaps).catch(() => setCaps(null))
    }, 400)
    return () => window.clearTimeout(t)
  }, [capsInput, slot.connection_id])
  const isOllama = caps?.provider === 'ollama' || activeConnection?.type === 'ollama'
  const reasoningOptions = caps?.controls.reasoning.options

  const onConnectionChange = (connectionId: string) => {
    // Reset model — the previous connection's model id won't exist in the
    // new connection's catalogue.
    onChange({ connection_id: connectionId, model: '' })
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

      <label className="block text-xs text-gray-500">Connection</label>
      <select
        value={slot.connection_id}
        onChange={e => onConnectionChange(e.target.value)}
        disabled={disabled}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
      >
        <option value="">— none —</option>
        {connections.map(c => (
          <option key={c.id} value={c.id}>
            {c.id} ({c.type === 'api' ? c.api_flavor : c.type})
          </option>
        ))}
      </select>

      <label className="block text-xs text-gray-500">
        Model
        {connModels.length > 0 && (
          <span className="text-gray-400 ml-1">({connModels.length} available)</span>
        )}
      </label>
      <ModelCombobox
        value={slot.model}
        models={connModels}
        extra={discoveredModels.filter(m => !connModels.includes(m))}
        onChange={model => onChange({ model })}
        disabled={disabled}
        placeholder={activeConnection ? undefined : 'pick a connection first'}
      />

      <div className="grid grid-cols-2 gap-2">
        <NumField label="Temp" step="0.1" min="0" value={slot.temperature} disabled={disabled}
          onChange={v => onChange({ temperature: v })} status={caps?.controls.temperature} />
        <NumField label="Max tokens" min="1" value={slot.max_tokens} disabled={disabled}
          onChange={v => onChange({ max_tokens: v })} status={caps?.controls.max_tokens} />
        <NumField label={isOllama ? 'Context (num_ctx)' : 'Context (Ollama only)'} min="256" value={slot.num_ctx}
          disabled={disabled} onChange={v => onChange({ num_ctx: v })}
          placeholder={caps?.context_length ? `model: ${caps.context_length.toLocaleString()}` : 'default'}
          status={isOllama ? undefined : { status: 'ignored', note: 'not sent to this provider' }} />
        <div>
          <label className="block text-xs text-gray-500">Reasoning</label>
          <select value={slot.reasoning ?? ''} disabled={disabled}
            onChange={e => onChange({ reasoning: (e.target.value || null) as ReasoningLevel | null })}
            className={inputCls}>
            <option value="">provider default</option>
            {(['off', 'low', 'medium', 'high'] as ReasoningLevel[]).map(lv => {
              const unavailable = !!reasoningOptions && !reasoningOptions.includes(lv)
              return <option key={lv} value={lv} disabled={unavailable}>{lv}{unavailable ? ' (n/a)' : ''}</option>
            })}
          </select>
          <StatusLine st={caps?.controls.reasoning} />
        </div>
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">
        {caps ? `${caps.provider_label}. ` : ''}Blank = not sent (provider default). Reasoning tokens are billed and
        count against Max tokens: with reasoning on, a small value can return an empty answer.
      </p>
      {footer}
    </div>
  )
}
