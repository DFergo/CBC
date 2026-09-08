// SPEC §4.7 + §5.1.
// Four slots (inference / compressor / summariser / translation), each picking
// a registered connection + a model within it. Connections are managed once
// in the ConnectionsCard at the top (LLM provider registry port); Refresh
// (connections status) and Check health (per-slot) live right there too, so
// every provider-related action is visible without scrolling past the slot
// cards. Each slot card has its own isolated Save (PUT /llm/slots/{name} —
// touches only that slot), enabled only when that slot's fields differ from
// what's persisted. The non-slot settings (thinking mode, concurrency,
// compression, routing) have their own isolated Save (PUT /llm/settings) at
// the bottom, where the original single Save button used to live.
import { useEffect, useState } from 'react'
import {
  getLLMConfig, saveLLMSlot, saveLLMSettings, checkLLMHealth, getLLMDefaults, getConnections, getConnectionsStatus,
} from '../api'
import type {
  LLMConfig, SlotConfig, SlotName,
  CompressionSettings, RoutingToggles, LLMHealth, LLMConnection, ConnectionsStatus, RoutableSlotName,
} from '../api'
import SlotEditor from '../components/llm/SlotEditor'
import ConnectionsCard from '../components/llm/ConnectionsCard'
import { useT } from '../i18n'
import type { AdminTranslationKeys } from '../i18n'

const SLOT_ORDER: { key: SlotName; labelKey: AdminTranslationKeys; hintKey: AdminTranslationKeys }[] = [
  { key: 'inference', labelKey: 'llm_slot_inference', hintKey: 'llm_slot_inference_hint' },
  { key: 'compressor', labelKey: 'llm_slot_compressor', hintKey: 'llm_slot_compressor_hint' },
  { key: 'summariser', labelKey: 'llm_slot_summariser', hintKey: 'llm_slot_summariser_hint' },
  { key: 'translation', labelKey: 'llm_slot_translation', hintKey: 'llm_slot_translation_hint' },
]

const SLOT_OPTIONS: RoutableSlotName[] = ['inference', 'compressor', 'summariser']

const POLL_INTERVAL_MS = 15000

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

// Small per-card save control shared by every slot + the misc-settings card.
// Grey/disabled when `dirty` is false, shows Saving…/Saved/error feedback —
// same idea as HRDDHelper's SaveBar. `onSave` is an isolated PUT (per-slot or
// per-settings), so clicking one card's Save never touches another card's
// unsaved draft.
function CardSaveButton({ dirty, onSave, label = 'Save' }: { dirty: boolean; onSave: () => Promise<void>; label?: string }) {
  const [state, setState] = useState<SaveState>('idle')
  const [errMsg, setErrMsg] = useState('')

  const click = async () => {
    setState('saving')
    setErrMsg('')
    try {
      await onSave()
      setState('saved')
      setTimeout(() => setState('idle'), 2000)
    } catch (e) {
      setState('error')
      setErrMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={click}
        disabled={!dirty || state === 'saving'}
        className="text-xs bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {state === 'saving' ? 'Saving…' : label}
      </button>
      {dirty && state === 'idle' && <span className="text-[11px] text-gray-400">Unsaved changes</span>}
      {state === 'saved' && <span className="text-[11px] text-green-600">Saved ✓</span>}
      {state === 'error' && <span className="text-[11px] text-uni-red">{errMsg.slice(0, 60)}</span>}
    </div>
  )
}

export default function LLMSection() {
  const [cfg, setCfg] = useState<LLMConfig | null>(null)
  const [savedCfg, setSavedCfg] = useState<LLMConfig | null>(null)
  const [defaults, setDefaults] = useState<{ lm_studio: string; ollama: string } | null>(null)
  const [connections, setConnections] = useState<LLMConnection[]>([])
  const [status, setStatus] = useState<ConnectionsStatus | null>(null)
  const [health, setHealth] = useState<LLMHealth | null>(null)
  const [healthState, setHealthState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [error, setError] = useState('')
  const { t } = useT()

  const refreshConnectionsStatus = async () => {
    setStatus(await getConnectionsStatus())
  }

  useEffect(() => {
    Promise.all([getLLMConfig(), getLLMDefaults(), getConnections(), getConnectionsStatus()])
      .then(([c, d, conns, st]) => { setCfg(c); setSavedCfg(c); setDefaults(d); setConnections(conns); setStatus(st) })
      .catch(e => setError(String(e)))

    const interval = window.setInterval(() => { refreshConnectionsStatus().catch(() => { /* best-effort */ }) }, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [])

  const updateSlot = (which: SlotName, patch: Partial<SlotConfig>) => {
    setCfg(c => c ? { ...c, [which]: { ...c[which], ...patch } } : c)
  }

  const updateCompression = (patch: Partial<CompressionSettings>) => {
    setCfg(c => c ? { ...c, compression: { ...c.compression, ...patch } } : c)
  }

  const updateRouting = (patch: Partial<RoutingToggles>) => {
    setCfg(c => c ? { ...c, routing: { ...c.routing, ...patch } } : c)
  }

  // Each slot has its own isolated PUT — saving Inference does not touch
  // Compressor on the backend. Only merge THAT slot's field back into
  // cfg/savedCfg (not the whole response) — otherwise an unsaved draft the
  // admin is mid-editing in another slot would get clobbered by the stale
  // value the backend just echoed back for it.
  const persistSlot = (which: SlotName) => async () => {
    if (!cfg) throw new Error('no config loaded')
    const saved = await saveLLMSlot(which, cfg[which])
    setCfg(c => c ? { ...c, [which]: saved[which] } : c)
    setSavedCfg(c => c ? { ...c, [which]: saved[which] } : c)
  }

  // Non-slot settings (thinking mode, concurrency, compression, routing) —
  // isolated PUT that leaves all 4 slots untouched on the backend; mirror
  // that here by only merging the settings fields, not the whole response,
  // so any slot mid-edit elsewhere on the page keeps its unsaved draft.
  const persistSettings = async () => {
    if (!cfg) throw new Error('no config loaded')
    const saved = await saveLLMSettings({
      compression: cfg.compression,
      routing: cfg.routing,
      disable_thinking: cfg.disable_thinking,
      max_concurrent_turns: cfg.max_concurrent_turns,
    })
    const merge = (c: LLMConfig): LLMConfig => ({
      ...c,
      compression: saved.compression,
      routing: saved.routing,
      disable_thinking: saved.disable_thinking,
      max_concurrent_turns: saved.max_concurrent_turns,
    })
    setCfg(c => c ? merge(c) : c)
    setSavedCfg(c => c ? merge(c) : c)
  }

  const runHealth = async () => {
    setHealthState('busy')
    setError('')
    try {
      setHealth(await checkLLMHealth())
      setHealthState('done')
      setTimeout(() => setHealthState('idle'), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setHealthState('idle')
    }
  }

  if (!cfg || !savedCfg || !defaults) {
    return (
      <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">{t('llm_heading')}</h3>
        <p className="text-sm text-gray-400">{t('generic_loading')}</p>
      </section>
    )
  }

  const slotDirty = (key: SlotName) => JSON.stringify(cfg[key]) !== JSON.stringify(savedCfg[key])
  const miscDirty =
    JSON.stringify(cfg.compression) !== JSON.stringify(savedCfg.compression) ||
    JSON.stringify(cfg.routing) !== JSON.stringify(savedCfg.routing) ||
    cfg.disable_thinking !== savedCfg.disable_thinking ||
    cfg.max_concurrent_turns !== savedCfg.max_concurrent_turns

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">{t('llm_heading')}</h3>
      <p className="text-sm text-gray-500 mb-4">
        {t('llm_description')}
      </p>

      <div className="mb-2">
        <ConnectionsCard
          defaults={defaults}
          status={status}
          onChanged={() => { refreshConnectionsStatus().catch(() => { /* best-effort */ }) }}
          onRefreshStatus={refreshConnectionsStatus}
          extraActions={
            <button
              onClick={runHealth}
              disabled={healthState === 'busy'}
              className="text-xs border border-gray-300 text-gray-700 rounded px-2 py-1 hover:bg-gray-50 disabled:opacity-50"
            >
              {healthState === 'busy' ? 'Checking…' : healthState === 'done' ? 'Checked ✓' : t('llm_check_health')}
            </button>
          }
        />
      </div>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-4">
        {SLOT_ORDER.map(({ key, labelKey, hintKey }) => (
          <SlotEditor
            key={key}
            label={t(labelKey)}
            hint={t(hintKey)}
            slot={cfg[key]}
            onChange={p => updateSlot(key, p)}
            health={health?.[key]}
            connections={connections}
            status={status}
            footer={<CardSaveButton dirty={slotDirty(key)} onSave={persistSlot(key)} />}
          />
        ))}
      </div>

      {/* Sprint 13 / Sprint 14 fix — Thinking / Reasoning toggle. Semantics
          expressed as ON/OFF on the switch to match the adjacent dropdown
          and avoid the double-negative confusion of "disable thinking". OFF
          is the default and keeps reasoning out of the chat; ON lets the
          model emit its <think> prelude. Applies across all slots regardless
          of provider. Backend field stays `disable_thinking` (inverted here). */}
      <div className="mt-6 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_thinking_mode')}</h4>
          <select
            value={cfg.disable_thinking ? 'off' : 'on'}
            onChange={e => setCfg(c => c ? { ...c, disable_thinking: e.target.value === 'off' } : c)}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value="off">OFF</option>
            <option value="on">ON</option>
          </select>
        </div>
        <p className="text-xs text-gray-500">
          {t('llm_thinking_mode_description')}
        </p>
      </div>

      {/* Sprint 14 — Max concurrent turns. Backend-wide cap on parallel chat
          turns; must align with the runtime's Parallel setting. */}
      <div className="mt-4 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_max_concurrent_turns')}</h4>
          <select
            value={cfg.max_concurrent_turns}
            onChange={e => setCfg(c => c ? { ...c, max_concurrent_turns: parseInt(e.target.value, 10) as 1 | 2 | 4 | 6 } : c)}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={4}>4</option>
            <option value={6}>6</option>
          </select>
        </div>
        <p className="text-xs text-gray-500">
          {t('llm_max_concurrent_turns_description')}
        </p>
      </div>

      {/* Context compression */}
      <div className="mt-6 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h4 className="text-sm font-semibold text-gray-700">{t('llm_context_compression')}</h4>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={cfg.compression.enabled}
              onChange={e => updateCompression({ enabled: e.target.checked })}
              className="rounded border-gray-300"
            />
            {t('llm_context_enabled')}
          </label>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          {t('llm_context_description')}
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_context_first_threshold')}</label>
            <input
              type="number"
              min={1000}
              value={cfg.compression.first_threshold}
              onChange={e => updateCompression({ first_threshold: parseInt(e.target.value, 10) })}
              disabled={!cfg.compression.enabled}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-400"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_context_step_size')}</label>
            <input
              type="number"
              min={500}
              value={cfg.compression.step_size}
              onChange={e => updateCompression({ step_size: parseInt(e.target.value, 10) })}
              disabled={!cfg.compression.enabled}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-400"
            />
          </div>
        </div>
      </div>

      {/* Summary routing */}
      <div className="mt-4 border border-gray-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-1">{t('llm_summary_routing')}</h4>
        <p className="text-xs text-gray-500 mb-3">
          {t('llm_summary_routing_description')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_document')}</label>
            <select
              value={cfg.routing.document_summary_slot}
              onChange={e => updateRouting({ document_summary_slot: e.target.value as RoutableSlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_final')}</label>
            <select
              value={cfg.routing.user_summary_slot}
              onChange={e => updateRouting({ user_summary_slot: e.target.value as RoutableSlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('llm_summary_contextual')}</label>
            <select
              value={cfg.routing.contextual_retrieval_slot}
              onChange={e => updateRouting({ contextual_retrieval_slot: e.target.value as RoutableSlotName })}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            >
              {SLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <p className="text-[11px] text-gray-500 mt-2">
          {t('llm_summary_contextual_hint')}
        </p>
      </div>

      <div className="mt-4">
        <CardSaveButton dirty={miscDirty} onSave={persistSettings} label={t('llm_save_config')} />
      </div>
    </section>
  )
}
