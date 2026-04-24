// Sprint 11 — CBA sidepanel. Slide-over from the right on every viewport
// size so the ChatShell layout stays untouched: no flex gymnastics, no
// width flicker when the panel opens, and a single behaviour to reason
// about on mobile + tablet + desktop. On md+ the panel is wider (w-96)
// than on mobile (w-80 capped at 85vw) but it always overlays the chat
// instead of pushing it. A semi-transparent backdrop closes on tap.
//
// Downloads are pull-inverse (Sprint 11): sidecar queues a document-request,
// backend polls + pushes bytes back, React polls this panel's poll hook
// until the bytes are ready, then triggers a browser download.
import { useCallback, useEffect, useRef, useState } from 'react'
import { t } from '../i18n'
import type { LangCode, CitationSource } from '../types'

interface Props {
  lang: LangCode
  sources: CitationSource[]
  open: boolean
  onClose: () => void
  // Phase B — when the user clicks a `[filename, locator]` citation in the
  // chat response, ChatShell bumps this so the panel scrolls that entry into
  // view and briefly pulses it. The parent is responsible for clearing /
  // overwriting it; the panel just reads it.
  highlightedFilename?: string | null
}

type DownloadState = 'idle' | 'downloading' | 'failed'
const POLL_INTERVAL_MS = 500
const POLL_DEADLINE_MS = 45_000

async function downloadDocument(
  source: CitationSource,
  onStatus: (s: DownloadState) => void,
): Promise<void> {
  onStatus('downloading')
  try {
    const queued = await fetch('/internal/document-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope_key: source.scope_key, filename: source.filename }),
    })
    if (!queued.ok) throw new Error(`HTTP ${queued.status}`)
    const { request_id } = (await queued.json()) as { request_id: string }
    const deadline = Date.now() + POLL_DEADLINE_MS
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
      const res = await fetch(`/internal/document/${encodeURIComponent(request_id)}`)
      if (res.status === 404) throw new Error('expired')
      const ctype = res.headers.get('content-type') || ''
      if (ctype.startsWith('application/json')) {
        const body = (await res.json()) as { status: string }
        if (body.status === 'error') throw new Error('backend error')
        continue // still pending
      }
      // Non-JSON response → the sidecar is serving the file.
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = source.filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      onStatus('idle')
      return
    }
    throw new Error('timeout')
  } catch {
    onStatus('failed')
    setTimeout(() => onStatus('idle'), 4000)
  }
}

function tierLabel(tier: string, lang: LangCode): string {
  if (tier === 'global') return t('citations_tier_global', lang)
  if (tier === 'frontend') return t('citations_tier_frontend', lang)
  if (tier === 'company') return t('citations_tier_company', lang)
  return tier
}

export default function CitationsPanel({
  lang, sources, open, onClose, highlightedFilename,
}: Props) {
  const [downloads, setDownloads] = useState<Record<string, DownloadState>>({})
  const itemRefs = useRef<Record<string, HTMLLIElement | null>>({})
  const [pulseKey, setPulseKey] = useState<string | null>(null)

  const updateStatus = useCallback((key: string, s: DownloadState) => {
    setDownloads(prev => ({ ...prev, [key]: s }))
  }, [])

  // Phase B — when the chat triggers a citation click, scroll the matching
  // entry into view + trigger a brief pulse so the user's eye finds it.
  useEffect(() => {
    if (!highlightedFilename || !open) return
    const match = sources.find(s => s.filename === highlightedFilename)
    if (!match) return
    const key = `${match.scope_key}::${match.filename}`
    const el = itemRefs.current[key]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    setPulseKey(key)
    const timer = window.setTimeout(() => setPulseKey(null), 1600)
    return () => window.clearTimeout(timer)
  }, [highlightedFilename, open, sources])

  // Dedup by (scope_key, filename). Preserve insertion order — newest citations
  // land at the bottom so the user sees them pile up as the conversation runs.
  const unique = (() => {
    const seen = new Set<string>()
    const out: CitationSource[] = []
    for (const s of sources) {
      const k = `${s.scope_key}::${s.filename}`
      if (!seen.has(k)) { seen.add(k); out.push(s) }
    }
    return out
  })()

  // Close the mobile drawer on Escape.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      {/* Backdrop — always there when open, tap to dismiss. On desktop the
          opacity is lighter so the admin can still see the chat behind. */}
      {open && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/40 md:bg-black/20 z-40"
          aria-hidden="true"
        />
      )}

      <aside
        className={`
          fixed right-0 top-0 h-full z-50
          w-80 max-w-[85vw] md:w-96
          bg-white border-l border-gray-200 shadow-lg
          transform transition-transform duration-200
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
        aria-hidden={!open}
      >
        <div className="p-4 flex flex-col h-full overflow-hidden">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">{t('citations_panel_title', lang)}</h3>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-xl leading-none px-2"
              aria-label={t('citations_panel_close', lang)}
            >
              ×
            </button>
          </div>

          {unique.length === 0 ? (
            <p className="text-xs text-gray-500 leading-relaxed">
              {t('citations_panel_empty', lang)}
            </p>
          ) : (
            <ul className="flex-1 overflow-y-auto space-y-2 pr-1">
              {unique.map(s => {
                const key = `${s.scope_key}::${s.filename}`
                const state = downloads[key] || 'idle'
                const isPulsing = pulseKey === key
                return (
                  <li
                    key={key}
                    ref={el => { itemRefs.current[key] = el }}
                    className={`
                      border rounded-lg p-2.5 transition-colors duration-500
                      ${isPulsing ? 'border-uni-blue bg-blue-50' : 'border-gray-200 bg-gray-50/60'}
                    `}
                  >
                    <div className="text-xs font-mono text-gray-800 break-all mb-1">
                      {s.filename}
                    </div>
                    {s.labels && s.labels.length > 0 && (
                      <div className="flex flex-wrap gap-1 mb-1.5">
                        {s.labels.map(l => (
                          <span key={l} className="text-[10px] rounded px-1.5 py-0.5 bg-uni-blue/10 text-uni-blue font-medium">
                            {l}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="flex items-center justify-between text-[11px] text-gray-500">
                      <span className="uppercase tracking-wide">{tierLabel(s.tier, lang)}</span>
                      <button
                        onClick={() => downloadDocument(s, st => updateStatus(key, st))}
                        disabled={state === 'downloading'}
                        className={`
                          text-[11px] rounded px-2 py-1 border
                          ${state === 'failed' ? 'border-uni-red text-uni-red' : 'border-uni-blue text-uni-blue hover:bg-blue-50'}
                          disabled:opacity-50
                        `}
                      >
                        {state === 'downloading' ? t('citations_downloading', lang)
                          : state === 'failed' ? t('citations_download_failed', lang)
                          : t('citations_download', lang)}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </aside>
    </>
  )
}
