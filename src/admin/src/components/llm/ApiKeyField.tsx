// API key field shared by connection editors. Two modes: paste-in-UI
// (default) and env-var-on-container (legacy / Vault). Toggle picks which
// one is active. Paste mode shows a password input with show/hide; on
// initial load the backend sends the sentinel "••••••••" if a key is set,
// the user can either leave it (key preserved on Save) or type a new one
// (overwrite). Env mode is the original env-var input.
import { useState } from 'react'
import { API_KEY_SENTINEL } from '../../api'

interface Props {
  apiKey: string | null | undefined
  apiKeyEnv: string | null | undefined
  envHint: string
  onChange: (patch: { api_key?: string | null; api_key_env?: string | null }) => void
  disabled: boolean
}

export default function ApiKeyField({ apiKey, apiKeyEnv, envHint, onChange, disabled }: Props) {
  const initialMode: 'paste' | 'env' =
    (apiKey || '').length > 0 ? 'paste'
    : (apiKeyEnv || '').length > 0 ? 'env'
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
              ({(apiKey || '') === API_KEY_SENTINEL ? 'set; type to replace' : 'pasted, persisted in /app/data/connections.json'})
            </span>
          </label>
          <div className="relative">
            <input
              type={reveal ? 'text' : 'password'}
              value={apiKey || ''}
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
            API key env var name <span className="text-gray-400">(e.g. {envHint})</span>
          </label>
          <input
            type="text"
            value={apiKeyEnv || ''}
            onChange={e => onChange({ api_key_env: e.target.value })}
            placeholder={envHint}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />
        </>
      )}
    </>
  )
}
