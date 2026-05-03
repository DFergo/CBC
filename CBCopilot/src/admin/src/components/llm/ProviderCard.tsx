// Top status indicator for LM Studio / Ollama / API providers. Shared
// between the global LLM section and the per-frontend LLM panel.
interface ProviderInfo {
  endpoint: string
  status: 'online' | 'offline'
  models: string[]
  error: string | null
}

export default function ProviderCard({ name, info }: { name: string; info?: ProviderInfo }) {
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

// Sprint 18 Fase 5 — variant for API providers. Shows the flavor + which
// slots use it + the env var name (not the value). Same dot semantics.
interface ApiProviderInfo {
  slots: string[]
  api_flavor: 'anthropic' | 'openai' | 'openai_compatible' | null
  api_endpoint: string
  api_key_env: string | null
  status: 'online' | 'offline'
  models: string[]
  error: string | null
}

export function ApiProviderCard({ info }: { info: ApiProviderInfo }) {
  const dot = info.status === 'online' ? 'bg-green-500' : 'bg-red-500'
  const flavorLabel: Record<string, string> = {
    anthropic: 'Anthropic',
    openai: 'OpenAI',
    openai_compatible: 'OpenAI-compatible',
  }
  const name = info.api_flavor ? flavorLabel[info.api_flavor] || 'API' : 'API'
  return (
    <div className="border border-gray-200 rounded-lg p-3">
      <div className="flex items-center gap-2">
        <div className={`w-2.5 h-2.5 rounded-full ${dot}`} />
        <span className="text-sm font-medium text-gray-800">{name}</span>
        <span className="text-[10px] text-gray-500 font-medium">
          {info.slots.join(' + ')}
        </span>
        <span className="ml-auto text-[11px] text-gray-400 font-mono truncate" title={info.api_endpoint}>
          {info.api_endpoint}
        </span>
      </div>
      <p className="text-xs text-gray-500 mt-1">
        {info.status === 'online'
          ? `${info.models.length} model${info.models.length === 1 ? '' : 's'} available · key env: ${info.api_key_env || '?'}`
          : (info.error || 'offline')}
      </p>
    </div>
  )
}
