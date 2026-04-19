// Top status indicator for LM Studio / Ollama. Shared between the global LLM
// section and the per-frontend LLM panel.
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
