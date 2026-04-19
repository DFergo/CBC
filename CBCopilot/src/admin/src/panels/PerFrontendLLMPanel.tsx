// Per-frontend LLM override (Sprint 4B, decision D2=B).
// Single checkbox "Override global config". When enabled, the UI snapshots
// the current global config and lets the admin edit it. When disabled, the
// override file is deleted and the frontend inherits global.
//
// This panel intentionally does NOT duplicate the full LLM editor from
// LLMSection — too much UI. Instead it shows the effective config at-a-glance
// and links the admin to a JSON editor / upload/download for power editing.
// For Sprint 4B that's enough. Sprint 5+ can evolve if people find it clunky.
import { useEffect, useRef, useState } from 'react'
import {
  getFrontendLLMOverride, saveFrontendLLMOverride, deleteFrontendLLMOverride,
  getLLMConfig,
} from '../api'
import type { LLMConfig } from '../api'
import { downloadJSON } from '../utils'

export default function PerFrontendLLMPanel({ frontendId }: { frontendId: string }) {
  const [override, setOverride] = useState<LLMConfig | null>(null)
  const [globalCfg, setGlobalCfg] = useState<LLMConfig | null>(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const uploadRef = useRef<HTMLInputElement>(null)

  const reload = async () => {
    try {
      const [ov, g] = await Promise.all([
        getFrontendLLMOverride(frontendId),
        getLLMConfig(),
      ])
      setOverride(ov.override)
      setGlobalCfg(g)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId])

  const enableOverride = async () => {
    if (!globalCfg) return
    setError('')
    try {
      // Snapshot the current global and persist as this frontend's override
      await saveFrontendLLMOverride(frontendId, globalCfg)
      await reload()
      setInfo('Override created from global snapshot')
      setTimeout(() => setInfo(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const disableOverride = async () => {
    if (!confirm('Disable the per-frontend LLM override? This frontend will use the global config.')) return
    setError('')
    try {
      await deleteFrontendLLMOverride(frontendId)
      await reload()
      setInfo('Override removed')
      setTimeout(() => setInfo(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      if (!data.inference || !data.compressor || !data.summariser) {
        throw new Error('Invalid LLM config JSON: needs inference, compressor, summariser slots.')
      }
      await saveFrontendLLMOverride(frontendId, data)
      await reload()
      setInfo('Override updated from uploaded JSON')
      setTimeout(() => setInfo(''), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const effective = override || globalCfg

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">LLM override</h4>
        <span className="text-xs text-gray-500">
          {override ? 'custom ◆' : 'inheriting global'}
          {info && <span className="ml-2 text-green-700">{info}</span>}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        When disabled, this frontend uses the global LLM config from the General tab. When enabled, the override replaces
        the global one entirely for this frontend's chat sessions. Edit by downloading the JSON, modifying, and re-uploading.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <label className="flex items-center gap-2 text-sm mb-3">
        <input
          type="checkbox"
          checked={!!override}
          onChange={e => (e.target.checked ? enableOverride() : disableOverride())}
          className="rounded border-gray-300"
        />
        Override global config
      </label>

      {effective && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs mb-3">
          <div><strong>Effective config:</strong> {override ? 'per-frontend override' : 'inherited from global'}</div>
          <ul className="mt-2 space-y-0.5">
            <li><code>inference</code>: {effective.inference.provider} / {effective.inference.model || '(no model)'}</li>
            <li><code>compressor</code>: {effective.compressor.provider} / {effective.compressor.model || '(no model)'}</li>
            <li><code>summariser</code>: {effective.summariser.provider} / {effective.summariser.model || '(no model)'}</li>
            <li>compression <code>{effective.compression.enabled ? 'enabled' : 'disabled'}</code> · first={effective.compression.first_threshold} · step={effective.compression.step_size}</li>
            <li>routing: doc summary → <code>{effective.routing.document_summary_slot}</code>, user summary → <code>{effective.routing.user_summary_slot}</code></li>
          </ul>
        </div>
      )}

      {override && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => downloadJSON(override, `llm-override-${frontendId}.json`)}
            className="text-xs border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 hover:bg-gray-50"
          >
            Download JSON
          </button>
          <label className="text-xs bg-uni-blue text-white rounded-lg px-3 py-1.5 font-medium hover:opacity-90 cursor-pointer">
            Upload JSON
            <input ref={uploadRef} type="file" accept=".json" onChange={handleUpload} className="hidden" />
          </label>
        </div>
      )}
    </div>
  )
}
