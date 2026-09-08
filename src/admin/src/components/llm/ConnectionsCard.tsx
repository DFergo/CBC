// LLM provider connection registry — CRUD list. Each connection is a named,
// reusable provider endpoint (LM Studio / Ollama / a remote API); the 4 LLM
// slots (inference/compressor/summariser/translation) each just pick a
// connection + a model from it, instead of embedding their own
// provider/endpoint/api_key (ported from HRDDHelper's ConnectionsCard).
import { useEffect, useState } from 'react'
import type { LLMConnection, ApiFlavor, ProviderType, ConnectionsStatus } from '../../api'
import {
  getConnections, createConnection, updateConnection, deleteConnection, probeConnection,
} from '../../api'
import ApiKeyField from './ApiKeyField'

const API_FLAVOR_DEFAULTS: Record<ApiFlavor, { endpoint: string; envHint: string }> = {
  anthropic: { endpoint: 'https://api.anthropic.com/v1', envHint: 'ANTHROPIC_API_KEY' },
  openai: { endpoint: 'https://api.openai.com/v1', envHint: 'OPENAI_API_KEY' },
  openai_compatible: { endpoint: '', envHint: 'MY_API_KEY' },
}

function blankConnection(defaults: { lm_studio: string; ollama: string }): LLMConnection {
  return {
    id: '',
    type: 'lm_studio',
    endpoint: defaults.lm_studio,
    api_flavor: null,
    api_endpoint: null,
    api_key: null,
    api_key_env: null,
    model_ids: [],
    enable: true,
  }
}

interface Props {
  defaults: { lm_studio: string; ollama: string }
  status: ConnectionsStatus | null
  onChanged: () => void
  // Manual "Refresh" — re-probes every connection's status. Separate from
  // onChanged (which just re-lists connections after a CRUD action) so the
  // button can show its own busy/done feedback.
  onRefreshStatus: () => Promise<void>
  // Extra buttons rendered next to Refresh (e.g. LLMSection's "Check slot
  // health") so every provider-related action lives in one place, visible
  // without scrolling past the slot cards.
  extraActions?: React.ReactNode
}

export default function ConnectionsCard({ defaults, status, onChanged, onRefreshStatus, extraActions }: Props) {
  const [connections, setConnections] = useState<LLMConnection[]>([])
  const [editing, setEditing] = useState<LLMConnection | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [error, setError] = useState('')
  const [refreshState, setRefreshState] = useState<'idle' | 'busy' | 'done'>('idle')

  const load = async () => {
    try { setConnections(await getConnections()) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  useEffect(() => { load() }, [])

  const refresh = async () => {
    setRefreshState('busy')
    setError('')
    try {
      await load()
      await onRefreshStatus()
      setRefreshState('done')
      setTimeout(() => setRefreshState('idle'), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setRefreshState('idle')
    }
  }

  const startNew = () => { setEditing(blankConnection(defaults)); setIsNew(true) }
  const startEdit = (c: LLMConnection) => { setEditing({ ...c }); setIsNew(false) }
  const cancel = () => { setEditing(null); setIsNew(false) }

  const save = async () => {
    if (!editing) return
    setError('')
    try {
      if (isNew) await createConnection(editing)
      else await updateConnection(editing.id, editing)
      setEditing(null)
      setIsNew(false)
      await load()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const remove = async (id: string) => {
    setError('')
    try {
      await deleteConnection(id)
      await load()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
        <h4 className="text-sm font-semibold text-gray-700">Connections</h4>
        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={refreshState === 'busy'}
            className="text-xs border border-gray-300 text-gray-700 rounded px-2 py-1 hover:bg-gray-50 disabled:opacity-50"
          >
            {refreshState === 'busy' ? 'Refreshing…' : refreshState === 'done' ? 'Updated ✓' : 'Refresh'}
          </button>
          {extraActions}
          <button
            onClick={startNew}
            className="text-xs border border-gray-300 text-gray-700 rounded px-2 py-1 hover:bg-gray-50"
          >
            + Add connection
          </button>
        </div>
      </div>
      <p className="text-[11px] text-gray-400 mb-3">
        Register a provider once (LM Studio, Ollama, or a remote API) and reuse it across
        inference / compressor / summariser / translation slots below.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="space-y-2">
        {connections.map(c => {
          const st = status?.[c.id]
          return (
            <div key={c.id} className="flex items-center justify-between gap-2 border border-gray-200 rounded-lg px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm font-mono truncate">{c.id}</div>
                <div className="text-[11px] text-gray-500">
                  {c.type === 'api' ? `api (${c.api_flavor})` : c.type}
                  {!c.enable && <span className="ml-1 text-gray-400">(disabled)</span>}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {st && (
                  <span className={`text-[11px] px-2 py-0.5 rounded ${st.status === 'online' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {st.status === 'online' ? `${st.models.length} model${st.models.length === 1 ? '' : 's'}` : 'offline'}
                  </span>
                )}
                <button onClick={() => startEdit(c)} className="text-xs text-uni-blue hover:underline">Edit</button>
                <button onClick={() => remove(c.id)} className="text-xs text-uni-red hover:underline">Delete</button>
              </div>
            </div>
          )
        })}
        {connections.length === 0 && (
          <p className="text-xs text-gray-400">No connections registered yet.</p>
        )}
      </div>

      {editing && (
        <ConnectionForm
          conn={editing}
          isNew={isNew}
          defaults={defaults}
          onChange={patch => setEditing(e => e ? { ...e, ...patch } : e)}
          onSave={save}
          onCancel={cancel}
        />
      )}
    </div>
  )
}

function ConnectionForm({
  conn, isNew, defaults, onChange, onSave, onCancel,
}: {
  conn: LLMConnection
  isNew: boolean
  defaults: { lm_studio: string; ollama: string }
  onChange: (patch: Partial<LLMConnection>) => void
  onSave: () => void
  onCancel: () => void
}) {
  const [probeStatus, setProbeStatus] = useState<'idle' | 'probing' | 'ok' | 'error'>('idle')
  const [probeMessage, setProbeMessage] = useState('')

  const onTypeChange = (type: ProviderType) => {
    if (type === 'lm_studio') {
      onChange({ type, endpoint: defaults.lm_studio, api_flavor: null, api_endpoint: null, api_key: null, api_key_env: null })
    } else if (type === 'ollama') {
      onChange({ type, endpoint: defaults.ollama, api_flavor: null, api_endpoint: null, api_key: null, api_key_env: null })
    } else {
      const flavor = conn.api_flavor || 'anthropic'
      onChange({ type, api_flavor: flavor, api_endpoint: API_FLAVOR_DEFAULTS[flavor].endpoint, api_key_env: conn.api_key_env || '' })
    }
    setProbeStatus('idle')
  }

  const onFlavorChange = (flavor: ApiFlavor) => {
    onChange({ api_flavor: flavor, api_endpoint: API_FLAVOR_DEFAULTS[flavor].endpoint || conn.api_endpoint || '' })
    setProbeStatus('idle')
  }

  const runProbe = async () => {
    setProbeStatus('probing')
    setProbeMessage('')
    try {
      const r = await probeConnection(conn)
      if (r.ok) {
        setProbeStatus('ok')
        setProbeMessage(`${r.models.length} model${r.models.length === 1 ? '' : 's'}`)
      } else {
        setProbeStatus('error')
        setProbeMessage(r.error?.slice(0, 80) || `HTTP ${r.status_code}`)
      }
    } catch (e) {
      setProbeStatus('error')
      setProbeMessage(e instanceof Error ? e.message.slice(0, 80) : 'probe failed')
    }
  }

  return (
    <div className="mt-3 border border-gray-300 rounded-lg p-3 space-y-2 bg-gray-50">
      <label className="block text-xs text-gray-500">Connection id</label>
      <input
        type="text"
        value={conn.id}
        onChange={e => onChange({ id: e.target.value })}
        disabled={!isNew}
        placeholder="e.g. anthropic-main"
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
      />

      <label className="block text-xs text-gray-500">Type</label>
      <select
        value={conn.type}
        onChange={e => onTypeChange(e.target.value as ProviderType)}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
      >
        <option value="lm_studio">LM Studio (local)</option>
        <option value="ollama">Ollama (local)</option>
        <option value="api">API (remote cloud)</option>
      </select>

      {conn.type === 'api' ? (
        <>
          <label className="block text-xs text-gray-500">Flavor</label>
          <select
            value={conn.api_flavor || 'anthropic'}
            onChange={e => onFlavorChange(e.target.value as ApiFlavor)}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="openai_compatible">OpenAI-compatible</option>
          </select>

          <label className="block text-xs text-gray-500">API endpoint</label>
          <input
            type="text"
            value={conn.api_endpoint || ''}
            onChange={e => onChange({ api_endpoint: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          />

          <ApiKeyField
            apiKey={conn.api_key}
            apiKeyEnv={conn.api_key_env}
            envHint={API_FLAVOR_DEFAULTS[conn.api_flavor || 'anthropic'].envHint}
            onChange={onChange}
            disabled={false}
          />

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={runProbe}
              disabled={probeStatus === 'probing'}
              className="px-2 py-1 text-xs border border-gray-300 text-gray-700 rounded disabled:opacity-50 hover:bg-gray-50"
            >
              {probeStatus === 'probing' ? 'Testing…' : 'Test connection'}
            </button>
            {probeStatus === 'ok' && (
              <span className="text-[11px] px-2 py-0.5 rounded bg-green-100 text-green-700">OK · {probeMessage}</span>
            )}
            {probeStatus === 'error' && (
              <span className="text-[11px] px-2 py-0.5 rounded bg-red-100 text-red-700">{probeMessage}</span>
            )}
          </div>
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">Endpoint</label>
          <input
            type="text"
            value={conn.endpoint || ''}
            onChange={e => onChange({ endpoint: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          />
        </>
      )}

      <label className="block text-xs text-gray-500">
        Model allowlist <span className="text-gray-400">(optional, comma-separated; empty = auto-discover)</span>
      </label>
      <input
        type="text"
        value={conn.model_ids.join(', ')}
        onChange={e => onChange({ model_ids: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono"
      />

      <label className="flex items-center gap-2 text-xs text-gray-600 pt-1">
        <input type="checkbox" checked={conn.enable} onChange={e => onChange({ enable: e.target.checked })} className="rounded border-gray-300" />
        Enabled
      </label>

      <div className="flex gap-2 pt-2">
        <button
          onClick={onSave}
          disabled={!conn.id.trim() || (conn.type === 'api' && !conn.api_flavor)}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
        >
          Save
        </button>
        <button onClick={onCancel} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </div>
  )
}
