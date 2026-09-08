// Single-slot LLM editor (connection / model / temp / tokens / ctx).
// Shared between the global LLMSection and the per-frontend LLM panel.
//
// The slot only picks a connection (from the registry, see ConnectionsCard)
// and a model within it — provider/endpoint/api_key live on the connection
// record now, not on the slot.
//
// `disabled` greys the whole slot out and stops the model auto-correct from
// firing — used at the per-frontend tier when the slot is showing an inherited
// (read-only) global value.
import { useEffect } from 'react'
import type { SlotConfig, SlotHealth, LLMConnection, ConnectionsStatus } from '../../api'

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
    if (connModels.length > 0 && !connModels.includes(slot.model)) {
      const t = window.setTimeout(() => onChange({ model: connModels[0] }), 0)
      return () => window.clearTimeout(t)
    }
  }, [connModels, slot.model, onChange, disabled])

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
      {connModels.length > 0 ? (
        <select
          value={connModels.includes(slot.model) ? slot.model : (slot.model || connModels[0])}
          onChange={e => onChange({ model: e.target.value })}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        >
          {connModels.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      ) : (
        <input
          type="text"
          value={slot.model}
          onChange={e => onChange({ model: e.target.value })}
          disabled={disabled}
          placeholder={activeConnection ? 'model id' : 'pick a connection first'}
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
      {footer}
    </div>
  )
}
