// Sprint 20 — embedding / reranker provider editor. Mirrors
// `components/llm/SlotEditor.tsx` (provider / endpoint / model / API key
// with the same paste-or-env-var + sentinel dance + "Test connection"),
// adapted for the two-provider-type-only shape of the RAG pipeline slots.
//
// Sprint 20 followup (Daniel's feedback, 2026-09-07): no vendor gets baked
// in as its own named provider — "api" is generic (works with oMLX, vLLM,
// HF TEI, OpenAI, or anything else speaking the same protocol) and the
// model list is always auto-detected from `GET {endpoint}/models` rather
// than typed against a fixed name.
//
// Sprint 20 followup 3 (more feedback the same day, after Daniel actually
// tried connecting to his oMLX):
// 1. The very first "Test connection" click ran a full deep round-trip
//    (an actual embed/rerank call) using whatever `model` happened to be
//    set — which, before the admin has picked anything, is the Pydantic
//    default left over from the `local` provider ("BAAI/bge-m3"). Against
//    oMLX that model doesn't exist under that exact name, so a perfectly
//    healthy 44-model server came back as a failure. Fixed: when no model
//    is selected yet, the probe runs `deep=false` (list-only, no model
//    needed at all) — see `list_provider_models` on the backend.
// 2. The "(recommended)" hint used to be baked into the `<option>` text
//    itself, which also then showed up as the CLOSED select's displayed
//    value once chosen — ugly and confusing. Moved to a separate static
//    note below the field, same visual pattern as the API key hint text.
// 3. oMLX (and similar all-in-one servers) serve LLM/TTS/vision models
//    through the SAME `/v1/models` list as embeddings/rerankers — there's
//    no `type` field to filter on structurally. Added a name-pattern
//    heuristic (`looksRelevant`) that hides the obviously-irrelevant ones
//    by default, with a "show all detected models" toggle for when the
//    heuristic is wrong about a custom name.
//
// Sprint 20 followup 4: the visual default shown by the model <select>
// (dropdownModels[0] when slot.model was "") never committed to real state
// until the admin clicked it, so Save could silently submit model="" and
// fail validation — fixed with a useEffect that commits it.
//
// Sprint 20 followup 5 (Daniel's feedback: mixed EN/ES text depending on
// what I happened to type, and several buttons whose purpose wasn't
// obvious even to him): EVERY string here now goes through the admin i18n
// system (`useT()`) instead of hardcoded text, so the component always
// matches whatever language the admin has selected — never a mix. Also
// added short always-visible explanations for the Local/API choice
// (`rag_embed_hint_local` / `_api`) instead of relying on a separate note
// elsewhere, since "what does this button actually do" was the core
// complaint.
//
// Reused twice by RAGPipelineSection: once for `embedding`, once for
// `reranker` (which additionally shows enabled/top_n fields via `kind`).
import { useEffect, useState } from 'react'
import type { EmbeddingProviderType, EmbeddingSlotConfig, RerankerSlotConfig } from '../../api'
import { API_KEY_SENTINEL, testEmbeddingConnection } from '../../api'
import { useT } from '../../i18n'

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
// instance) and can vouch for — surfaced as a static "Recommended" note
// below the field when the provider happens to expose one of these, never
// as a restriction on what's selectable. Matched by substring so naming
// variants (e.g. "bge-m3-mlx-fp16", "BAAI/bge-m3") still get flagged. Both
// are multilingual: BGE-M3 covers 100+ languages; the same recommendation
// logic applies to any future validated model — extend this list, don't
// replace the auto-detection.
const RECOMMENDED_SUBSTRINGS: Record<'embedding' | 'reranker', string[]> = {
  embedding: ['bge-m3'],
  reranker: ['bge-reranker-v2-m3'],
}

function isRecommended(kind: 'embedding' | 'reranker', modelId: string): boolean {
  const needle = modelId.toLowerCase()
  return RECOMMENDED_SUBSTRINGS[kind].some(s => needle.includes(s))
}

// Name-pattern heuristic to declutter a mixed catalog (oMLX-style servers
// serve LLM/TTS/vision/embedding/reranker models through the same
// /v1/models list, with no structural "type" field to filter on). This is
// a UX default, never a hard filter — `showAllModels` bypasses it entirely,
// and nothing here blocks selecting/typing an arbitrary model id.
const IRRELEVANT_HINTS = /tts|kokoro|whisper|-vl-|vision|markitdown|-coder-|instruct|abliterated|heretic/i
const EMBEDDING_HINTS = /embed|bge|e5[-_]|gte|jina|nomic|minilm|arctic|gecko|voyage/i
const RERANKER_HINTS = /rerank|cross-encoder/i

function looksRelevant(kind: 'embedding' | 'reranker', modelId: string): boolean {
  const id = modelId.toLowerCase()
  if (IRRELEVANT_HINTS.test(id)) return false
  if (kind === 'reranker') return RERANKER_HINTS.test(id)
  if (RERANKER_HINTS.test(id)) return false // a reranker is never a usable embedder
  return EMBEDDING_HINTS.test(id)
}

export default function EmbeddingSlotEditor({
  kind, label, hint, slot, onChange, localModelOptions, disabled = false,
}: Props) {
  const { t } = useT()
  const [probeStatus, setProbeStatus] = useState<'idle' | 'probing' | 'ok' | 'error'>('idle')
  const [probeMessage, setProbeMessage] = useState('')
  const [probedModels, setProbedModels] = useState<string[]>([])
  const [showAllModels, setShowAllModels] = useState(false)

  useEffect(() => {
    setProbeStatus('idle')
    setProbeMessage('')
    setProbedModels([])
  }, [slot.provider, slot.api_endpoint, slot.api_key_env])

  const runProbe = async () => {
    setProbeStatus('probing')
    setProbeMessage('')
    // No model chosen yet -> list-only probe (no round-trip embed/rerank
    // call, so there's nothing to fail against a not-yet-selected model).
    const hasModel = !!(slot.model || '').trim()
    try {
      const r = await testEmbeddingConnection(kind, {
        provider: slot.provider,
        model: slot.model || undefined,
        api_endpoint: slot.api_endpoint || null,
        api_key: slot.api_key || null,
        api_key_env: slot.api_key_env || null,
      }, hasModel)
      // Always keep the detected model list, even on failure — the backend
      // already returns it whenever `GET /models` succeeded, regardless of
      // whether the (optional) deep round-trip against the CURRENTLY
      // SELECTED model also succeeded. Discarding it here was the bug that
      // forced admins to type an exact model name blind.
      setProbedModels(r.models)
      if (r.ok) {
        setProbeStatus('ok')
        setProbeMessage(
          hasModel
            ? t('rag_embed_probe_verified', { count: r.models.length })
            : t('rag_embed_probe_listed', { count: r.models.length }),
        )
      } else {
        setProbeStatus('error')
        setProbeMessage(
          r.models.length > 0
            ? t('rag_embed_probe_found_but_error', { count: r.models.length, error: (r.error || `HTTP ${r.status_code}`).slice(0, 90) })
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
    if (probedModels.length === 0) return []
    const base = showAllModels ? probedModels : probedModels.filter(m => looksRelevant(kind, m))
    // Recommended (validated) models float to the top; rest stay in
    // whatever order the server reported them.
    const recommended = base.filter(m => isRecommended(kind, m))
    const rest = base.filter(m => !isRecommended(kind, m))
    return [...recommended, ...rest]
  })()

  const recommendedInList = dropdownModels.filter(m => isRecommended(kind, m))
  const hiddenByFilter = slot.provider !== 'local' && !showAllModels
    ? probedModels.length - dropdownModels.length
    : 0

  // Bugfix: the <select> below falls back to `dropdownModels[0]` for its
  // DISPLAYED value when `slot.model` is empty, so a freshly-populated
  // dropdown visually shows the first (usually recommended) model as
  // selected — but that's a rendering fallback only, `onChange` never
  // fires for it, so the actual `slot.model` in state stays "". An admin
  // who doesn't happen to click the dropdown (because it already LOOKS
  // right) then hits Save with an empty model, which fails backend
  // validation for `provider != "local"`. Commit the visual default into
  // real state as soon as the list appears, so what's displayed is always
  // what actually gets saved.
  useEffect(() => {
    if (!slot.model && dropdownModels.length > 0) {
      onChange({ model: dropdownModels[0] } as Partial<AnySlot>)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dropdownModels.join('|'), slot.model])

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
            {t('rag_embed_enabled_label')}
          </label>
        )}
      </div>
      <p className="text-[11px] text-gray-400 leading-snug">{hint}</p>

      <label className="block text-xs text-gray-500">{t('rag_embed_provider_label')}</label>
      <select
        value={slot.provider}
        onChange={e => onProviderChange(e.target.value as EmbeddingProviderType)}
        disabled={disabled}
        className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-500"
      >
        <option value="local">{t('rag_embed_provider_local')}</option>
        <option value="api">{t('rag_embed_provider_api')}</option>
      </select>
      <p className="text-[11px] text-gray-400 leading-snug">
        {slot.provider === 'local' ? t('rag_embed_hint_local') : t('rag_embed_hint_api')}
      </p>
      {slot.provider === 'local' && kind === 'reranker' && (
        <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5">
          {t('rag_embed_reranker_local_caveat')}
        </p>
      )}

      {slot.provider !== 'local' && (
        <>
          <label className="block text-xs text-gray-500">{t('rag_embed_endpoint_label')}</label>
          <input
            type="text"
            value={slot.api_endpoint || ''}
            onChange={e => onChange({ api_endpoint: e.target.value } as Partial<AnySlot>)}
            placeholder={t('rag_embed_endpoint_placeholder')}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />

          <ApiKeyField slot={slot} onChange={onChange} disabled={disabled} />

          {kind === 'reranker' && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-1.5">
              {t('rag_embed_rerank_caveat')}
            </p>
          )}

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={runProbe}
              disabled={disabled || probeStatus === 'probing'}
              className="px-2 py-1 text-xs border border-gray-300 text-gray-700 rounded disabled:opacity-50 hover:bg-gray-50"
            >
              {probeStatus === 'probing' ? t('rag_embed_testing') : t('rag_embed_test_button')}
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
        {t('rag_embed_model_label')}
        {dropdownModels.length > 0 && <span className="text-gray-400 ml-1">{t('rag_embed_model_available', { count: dropdownModels.length })}</span>}
      </label>
      {dropdownModels.length === 0 && slot.provider !== 'local' && (
        <p className="text-[11px] text-gray-400">{t('rag_embed_model_prompt')}</p>
      )}
      {dropdownModels.length > 0 ? (
        <select
          value={dropdownModels.includes(slot.model) ? slot.model : (slot.model || dropdownModels[0])}
          onChange={e => onChange({ model: e.target.value } as Partial<AnySlot>)}
          disabled={disabled}
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
        >
          {dropdownModels.map(m => <option key={m} value={m}>{m}</option>)}
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
      {recommendedInList.length > 0 && (
        <p className="text-[11px] text-gray-400">
          {t('rag_embed_recommended', { models: recommendedInList.join(', ') })}
        </p>
      )}
      {slot.provider !== 'local' && probedModels.length > 0 && (
        <label className="flex items-center gap-1.5 text-[11px] text-gray-500">
          <input
            type="checkbox"
            checked={showAllModels}
            onChange={e => setShowAllModels(e.target.checked)}
            className="rounded border-gray-300"
          />
          {t('rag_embed_show_all', { count: probedModels.length })} ({t('rag_embed_show_all_hint')})
          {!showAllModels && hiddenByFilter > 0 && (
            <span className="text-gray-400">· {t('rag_embed_hidden_count', { count: hiddenByFilter })}</span>
          )}
        </label>
      )}

      {kind === 'reranker' && (
        <div>
          <label className="block text-xs text-gray-500">{t('rag_embed_topn_label')}</label>
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
  const { t } = useT()
  const initialMode: 'paste' | 'env' =
    (slot.api_key || '').length > 0 ? 'paste'
    : (slot.api_key_env || '').length > 0 ? 'env'
    : 'paste'
  const [mode, setMode] = useState<'paste' | 'env'>(initialMode)
  const [reveal, setReveal] = useState(false)

  return (
    <>
      <div className="flex items-center gap-2 mt-1">
        <label className="text-xs text-gray-500">{t('rag_embed_key_source_label')}</label>
        <div className="ml-auto flex gap-1 text-[11px]">
          <button type="button" onClick={() => setMode('paste')} disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'paste' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}>
            {t('rag_embed_key_mode_paste')}
          </button>
          <button type="button" onClick={() => setMode('env')} disabled={disabled}
            className={`px-2 py-0.5 rounded border ${mode === 'env' ? 'bg-blue-50 border-blue-400 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'} disabled:opacity-50`}>
            {t('rag_embed_key_mode_env')}
          </button>
        </div>
      </div>

      {mode === 'paste' ? (
        <>
          <label className="block text-xs text-gray-500">
            {t('rag_embed_key_source_label')} <span className="text-gray-400">
              ({(slot.api_key || '') === API_KEY_SENTINEL ? t('rag_embed_key_set_hint') : t('rag_embed_key_saved_hint')})
            </span>
          </label>
          <div className="relative">
            <input
              type={reveal ? 'text' : 'password'}
              value={slot.api_key || ''}
              onChange={e => onChange({ api_key: e.target.value })}
              placeholder={t('rag_embed_key_placeholder')}
              disabled={disabled}
              className="w-full border border-gray-300 rounded-lg pl-2 pr-16 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
            />
            <button type="button" onClick={() => setReveal(r => !r)} disabled={disabled}
              className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[11px] text-gray-500 hover:text-gray-700 disabled:opacity-50">
              {reveal ? t('rag_embed_key_hide') : t('rag_embed_key_reveal')}
            </button>
          </div>
        </>
      ) : (
        <>
          <label className="block text-xs text-gray-500">{t('rag_embed_key_env_label')}</label>
          <input
            type="text"
            value={slot.api_key_env || ''}
            onChange={e => onChange({ api_key_env: e.target.value })}
            placeholder={t('rag_embed_key_env_placeholder')}
            disabled={disabled}
            className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm font-mono disabled:bg-gray-100 disabled:text-gray-500"
          />
        </>
      )}
    </>
  )
}
