// Sprint 20 — embedding / reranker provider editor. Mirrors
// `components/llm/SlotEditor.tsx` (provider / endpoint / model / API key
// with the same paste-or-env-var + sentinel dance + "Test connection"),
// adapted for the two-provider-type-only shape of the RAG pipeline slots.
//
// Sprint 20 followup (Daniel's feedback, 2026-09-07): no vendor gets baked
// in as its own named provider — "api" is generic (works with oMLX, vLLM,
// HF TEI, OpenAI, or anything else speaking the same protocol) and the
// model list is always auto-detected from `GET {endpoint}/models` rather
// than typed against a fixed name. This also fixed a real bug: the probe
// used to discard the detected model list whenever the (optional) deep
// round-trip check failed — e.g. because no model was picked yet — forcing
// the admin to guess an exact model string by hand even though the server
// had already told us what it has loaded. `runProbe` below always keeps
// `r.models` regardless of `r.ok`.
//
// Reused twice by RAGPipelineSection: once for `embedding`, once for
// `reranker` (which additionally shows enabled/top_n fields via `kind`).
import { useEffect, useState } from 'react'
import type { EmbeddingProviderType, EmbeddingSlotConfig, RerankerSlotConfig } from '../../api'
import { API_KEY_SENTINEL, testEmbeddingConnection } from '../../api'

type AnySlot = EmbeddingSlotConfig | RerankerSlotConfig

interface Props {
  kind: 'embedding' | 'reranker'
  label: string
  hint: string
  slot: AnySlot
  onChange: (patch: Partial<AnySlot>) => void
  localModelOptions: string[]
  disabled?: boolean
}

// Models we've actually tested end-to-end (live, against a real oMLX
// instance) and can vouch for — surfaced as a "(recommended)" hint in the
// dropdown when the provider happens to expose one of these, never as a
// restriction. Matched by substring so naming variants (e.g.
// "bge-m3-mlx-fp16", "BAAI/bge-m3") still get flagged. Both are
// multilingual: BGE-M3 covers 100+ languages; the same recommendation logic
// applies to any future validated model — extend this list, don't replace
// the auto-detection.
const RECOMMENDED_SUBSTRINGS: Record<'embedding' | 'reranker', string[]> = {
  embedding: ['bge-m3'],
  reranker: ['bge-reranker-v2-m3'],
}

function isRecommended(kind: 'embedding' | 'reranker', modelId: string): boolean {
  const needle = modelId.toLowerCase()
  return RECOMMENDED_SUBSTRINGS[kind].some(s => needle.includes(s))
}

export default function EmbeddingSlotEditor({
  kind, label, hint, slot, onChange, localModelOptions, disabled = false,
}: Props) {
  const [probeStatus, setProbeStatus] = useState<'idle' | 'probing' | 'ok' | 'error'>('idle')
  const [probeMessage, setProbeMessage] = useState('')
  const [probedModels, setProbedModels] = useState<string[]>([])

  useEffect(() => {
    setProbeStatus('idle')
    setProbeMessage('')
    setProbedModels([])
  }, [slot.provider, slot.api_endpoint, slot.api_key_env])

  const runProbe = async () => {
    setProbeStatus('probing')
    setProbeMessage('')
    try {
      const r = await testEmbeddingConnection(kind, {
        provider: slot.provider,
        model: slot.model || undefined,
        api_endpoint: slot.api_endpoint || null,
        api_key: slot.api_key || null,
        api_key_env: slot.api_key_env || null,
      })
      // Always keep the detected model list, even on failure — the backend
      // already returns it whenever `GET /models` succeeded, regardless of
      // whether the (optional) deep round-trip against the CURRENTLY
      // SELECTED model also succeeded. Discarding it here was the bug that
      // forced admins to type an exact model name blind.
      setProbedModels(r.models)
      if (r.ok) {
        setProbeStatus('ok')
        setProbeMessage(`OK · ${r.models.length} model${r.models.length === 1 ? '' : 's'}`)
      } else {
        setProbeStatus('error')
        setProbeMessage(
          r.models.length > 0
            ? `${r.models.length} model${r.models.length === 1 ? '' : 's'} found, but: ${(r.error || `HTTP ${r.status_code}`).slice(0, 90)}`
            : (r.error?.slice(0, 100) || `HTTP ${r.status_code}`),
        )
      }
    } catch (e) {
      setProbeStatus('error')
      setProbeMessage(e instanceof Error ? e.message.slice(0, 100) : 'probe failed')
    }
  }

  const onProviderChange = (provider: EmbeddingProviderType) => {
    if (provider === 'local') {
      onChange({
        provider,
        model: localModelOptions[0] || '',
        api_endpoint: null,
        api_key: null,
        api_key_env: null,
      } as Partial<AnySlot>)
    } else {
      onChange({ provider, model: '' } as Partial<AnySlot>)
    }
  }

  const dropdownModels = (() => {
    if (slot.provider === 'local') return localModelOptions
    if (probedModels.length > 0) {
      // Recommended (validated) models float to the top; rest stay in
      // whatever order the server reported them.
      const recommended = probedModels.filter(m => isRecommended(kind, m))
      const rest = probedModels.filter(m => !isRecommended(kind, m))
      return [...recommended, ...rest]
    }
    return []
  })()

  return (
    <div className={`border border-gray-200 rounded-lg p-3 space-y-2 ${disabled ? 'bg-gray-50' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-700">{label}</h4>
        {kind === 'reranker' && (
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={(slot as RerankerSlotConfig).enabled}
              disabled={disabled}
              onChange={e => onChange({ enabled: e.target.checked } as Partial<AnySlot>)}
              className="rounded border-gray-300"
            />
            Enabled
          </label>
        )}
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">{hint}</p>

      <label className="block text-xs text-gray-500">Provider</label>
      <select
        value={slot.provider}
        onChange={e => onProviderChange(e.target.value as EmbeddingProviderType)}
        disabled={disabled}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
      >
        <option value="local">Local (baked into image)</option>
        <option value="api">API (self-hosted or commercial — oMLX, vLLM, OpenAI, ...)</option>
      </select>

      {slot.provider !== 'local' && (
        <>
          <label className="block text-xs text-gray-500">API endpoint</label>
          <input
            type="text"
            value={slot.api_endpoint || ''}
            onChange={e => onChange({ api_endpoint: e.target.value } as Partial<AnySlot>)}
            placeholder="http://<host>:<port>/v1 — e.g. your oMLX/vLLM server, or https://api.openai.com/v1"
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />

          <ApiKeyField slot={slot} onChange={onChange} disabled={disabled} />

          {kind === 'reranker' && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5">
              Reranking uses a de-facto <code>/rerank</code> endpoint (shared by oMLX, HF TEI, vLLM,
              Infinity) that is NOT part of the official OpenAI API. It may not work against every
              API provider — click "Test connection" to confirm before saving.
            </p>
          )}

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
              <span className="text-[11px] px-2 py-0.5 rounded bg-green-100 text-green-700">{probeMessage}</span>
            )}
            {probeStatus === 'error' && (
              <span className="text-[11px] px-2 py-0.5 rounded bg-red-100 text-red-700">{probeMessage}</span>
            )}
          </div>
        </>
      )}

      <label className="block text-xs text-gray-500">
        Model
        {dropdownModels.length > 0 && <span className="text-gray-400 ml-1">({dropdownModels.length} available)</span>}
        {dropdownModels.length === 0 && slot.provider !== 'local' && (
          <span className="text-gray-400 ml-1">(fill endpoint + key, click "Test connection" to populate)</span>
        )}
      </label>
      {dropdownModels.length > 0 ? (
        <select
          value={dropdownModels.includes(slot.model) ? slot.model : (slot.model || dropdownModels[0])}
          onChange={e => onChange({ model: e.target.value } as Partial<AnySlot>)}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        >
          {dropdownModels.map(m => (
            <option key={m} value={m}>{m}{isRecommended(kind, m) ? ' — recomendado (probado por nosotros)' : ''}</option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={slot.model}
          onChange={e => onChange({ model: e.target.value } as Partial<AnySlot>)}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        />
      )}

      {kind === 'reranker' && (
        <div>
          <label className="block text-xs text-gray-500">Top N</label>
          <input
            type="number"
            min={1}
            max={50}
            value={(slot as RerankerSlotConfig).top_n}
            onChange={e => onChange({ top_n: parseInt(e.target.value, 10) } as Partial<AnySlot>)}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
          />
        </div>
      )}
    </div>
  )
}

// Same paste/env-var pattern as llm/SlotEditor.tsx's ApiKeyField, kept as a
// local copy rather than a shared extraction — the LLM one is typed against
// `ApiFlavor`-specific env hints that don't apply here, and duplicating ~40
// lines was judged simpler than generalising both call sites right now
// (decisión propia, revisar si se añade un tercer consumidor).
function ApiKeyField({
  slot, onChange, disabled,
}: {
  slot: AnySlot
  onChange: (patch: Partial<AnySlot>) => void
  disabled: boolean
}) {
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
          <button type="button" onClick={() => setMode('paste')} disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'paste' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}>
            Paste
          </button>
          <button type="button" onClick={() => setMode('env')} disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'env' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}>
            Env var
          </button>
        </div>
      </div>

      {mode === 'paste' ? (
        <>
          <label className="block text-xs text-gray-500">
            API key <span className="text-gray-400">
              ({(slot.api_key || '') === API_KEY_SENTINEL ? 'set; type to replace' : 'pasted, persisted in /app/data/embedding_config.json'})
            </span>
          </label>
          <div className="relative">
            <input
              type={reveal ? 'text' : 'password'}
              value={slot.api_key || ''}
              onChange={e => onChange({ api_key: e.target.value })}
              placeholder="optional — some self-hosted servers don't require one"
              disabled={disabled}
              className="w-full border border-gray-300 rounded-lg pl-2 pr-16 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
            />
            <button type="button" onClick={() => setReveal(r => !r)} disabled={disabled}
              className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[11px] text-gray-500 hover:text-gray-700 disabled:opacity-50">
              {reveal ? 'hide' : 'show'}
            </button>
          </div>
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">API key env var name</label>
          <input
            type="text"
            value={slot.api_key_env || ''}
            onChange={e => onChange({ api_key_env: e.target.value })}
            placeholder="MY_EMBEDDING_API_KEY"
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />
        </>
      )}
    </>
  )
}
