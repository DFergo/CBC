// Adapted from HRDDHelper/src/frontend/src/components/ChatShell.tsx.
// CBC 6B differences:
// - The first user bubble is the survey's initial_query (the backend already
//   injected it server-side in Sprint 6A; we just render it immediately so
//   the UI doesn't look empty while tokens are being generated).
// - Uploads use Sprint 5's sidecar /internal/upload endpoint; chips show
//   upload progress inline.
// - End-session flow goes through /internal/close-session; the summariser
//   slot streams the summary back via the same SSE channel.
// - Guardrails banner appears when session.guardrail_violations >= 2.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { t } from '../i18n'
import type { BrandingConfig, CitationSource, LangCode, RecoveryData, SurveyData } from '../types'
import CitationsPanel from './CitationsPanel'

const SUMMARY_MARKER = 'summary'
// Fallbacks used until /internal/guardrails/thresholds resolves. Match the
// backend defaults so the UX is identical even when the sidecar proxy has
// to synthesize a value (backend slow / unreachable).
const DEFAULT_WARN_AT = 2
const DEFAULT_END_AT = 5
const STATUS_POLL_MS = 5000

interface AttachmentChip {
  id: string
  filename: string
  status: 'uploading' | 'ready' | 'failed'
  error?: string
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'summary'
  content: string
  attachments?: string[]
}

interface SessionStatus {
  status: 'active' | 'completed' | 'destroyed' | string
  guardrail_violations: number
  message_count: number
}

interface Props {
  lang: LangCode
  sessionToken: string
  survey: SurveyData
  branding?: BrandingConfig
  recoveryData?: RecoveryData | null
  // Sprint 11 — when false, the CBA sidepanel + its toggle are hidden
  // entirely (per-frontend switch in SessionSettings). Defaults to true
  // when the deployment config didn't include the key.
  cbaSidepanelEnabled?: boolean
}

function mapRecovery(rec: RecoveryData | null | undefined): ChatMessage[] {
  if (!rec) return []
  return rec.messages.map(m => ({
    role: m.role === 'assistant_summary' ? 'summary' : (m.role === 'user' ? 'user' : 'assistant'),
    content: m.content,
    attachments: (m.attachments && m.attachments.length) ? m.attachments : undefined,
  }))
}

export default function ChatShell({
  lang, sessionToken, survey, branding: _branding, recoveryData,
  cbaSidepanelEnabled = true,
}: Props) {
  const initialQuery = (survey.initial_query || '').trim()
  const recoveredMessages = mapRecovery(recoveryData)
  const isRecovering = recoveredMessages.length > 0

  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    isRecovering
      ? recoveredMessages
      : (initialQuery ? [{ role: 'user', content: initialQuery }] : []),
  )
  const [input, setInput] = useState('')
  // A new session is still streaming when we mount (backend is generating the
  // first response). A recovered session is NOT streaming — everything is on
  // disk; we only open the SSE for future turns.
  const [isStreaming, setIsStreaming] = useState<boolean>(!isRecovering && !!initialQuery)
  const [streamingText, setStreamingText] = useState('')
  const [isSummaryStream, setIsSummaryStream] = useState(false)
  const [error, setError] = useState('')
  const [sessionEnded, setSessionEnded] = useState(recoveryData?.status === 'completed')
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  const [summaryCopied, setSummaryCopied] = useState(false)
  const [violations, setViolations] = useState(recoveryData?.guardrail_violations ?? 0)
  const [attachments, setAttachments] = useState<AttachmentChip[]>([])
  const [warnAt, setWarnAt] = useState(DEFAULT_WARN_AT)
  const [endAt, setEndAt] = useState(DEFAULT_END_AT)
  // Sprint 11 — CBA citations piling up across this session. The panel renders
  // them deduped by (scope_key, filename) and offers a pull-inverse download.
  const [sources, setSources] = useState<CitationSource[]>([])
  // Sidepanel open state. Default open on md+ viewports, closed on mobile so
  // the chat starts clean. Re-checked on resize so rotating a tablet doesn't
  // leave the user stuck.
  const [panelOpen, setPanelOpen] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : false,
  )

  const chatEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const streamingTextRef = useRef('')
  const isSummaryStreamRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // HRDD-style scroll guard. While the LLM is streaming a long response, the
  // user often wants to scroll back up to read what already came through.
  // We auto-scroll to the bottom only when the user IS at the bottom; the
  // moment they scroll up, we leave them in peace until they send the next
  // message (which resets the flag — see send / endSession below).
  const userScrolledUp = useRef(false)

  const bangedOnGuardrails = violations >= endAt

  // --- SSE connection ---

  const openStream = useCallback(() => {
    if (eventSourceRef.current) eventSourceRef.current.close()
    const es = new EventSource(`/internal/stream/${sessionToken}`)
    eventSourceRef.current = es
    let consecutiveErrors = 0

    es.addEventListener('token', (e: MessageEvent) => {
      consecutiveErrors = 0
      streamingTextRef.current += e.data
      setStreamingText(streamingTextRef.current)
      setIsStreaming(true)
    })

    // Sprint 11: the backend emits a `sources` event right before `done`
    // carrying the JSON list of documents that contributed chunks to this
    // turn's response. We dedup against whatever is already in state so the
    // panel shows an accumulating but unique list over the whole chat.
    es.addEventListener('sources', (e: MessageEvent) => {
      try {
        const incoming = JSON.parse(e.data) as CitationSource[]
        if (!Array.isArray(incoming)) return
        setSources(prev => {
          const seen = new Set(prev.map(s => `${s.scope_key}::${s.filename}`))
          const next = [...prev]
          for (const s of incoming) {
            const k = `${s.scope_key}::${s.filename}`
            if (s.filename && !seen.has(k)) {
              seen.add(k)
              next.push(s)
            }
          }
          return next
        })
      } catch {
        // ignore malformed payload — drop silently
      }
    })

    es.addEventListener('done', (e: MessageEvent) => {
      es.close()
      const full = streamingTextRef.current
      const doneReason = (e.data || '').trim()
      const wasSummary = isSummaryStreamRef.current || doneReason === SUMMARY_MARKER
      if (full) {
        setMessages(prev => [...prev, { role: wasSummary ? 'summary' : 'assistant', content: full }])
      }
      streamingTextRef.current = ''
      setStreamingText('')
      setIsStreaming(false)
      if (wasSummary) {
        setSessionEnded(true)
      }
      isSummaryStreamRef.current = false
      setIsSummaryStream(false)
    })

    es.addEventListener('error', (e: MessageEvent) => {
      es.close()
      streamingTextRef.current = ''
      setStreamingText('')
      setIsStreaming(false)
      setError(e.data || t('chat_error', lang))
      isSummaryStreamRef.current = false
      setIsSummaryStream(false)
    })

    es.onerror = () => {
      consecutiveErrors += 1
      if (consecutiveErrors >= 3) {
        es.close()
        streamingTextRef.current = ''
        setStreamingText('')
        setIsStreaming(false)
        setError(t('chat_error', lang))
      }
    }
  }, [sessionToken, lang])

  // Open the stream on mount + re-open if the component is remounted.
  useEffect(() => {
    openStream()
    return () => {
      eventSourceRef.current?.close()
      eventSourceRef.current = null
    }
  }, [openStream])

  // Fetch live guardrail thresholds once. Sidecar proxies the backend; any
  // failure falls back to DEFAULT_WARN_AT / DEFAULT_END_AT (backend defaults).
  useEffect(() => {
    let cancelled = false
    fetch('/internal/guardrails/thresholds')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled || !data) return
        if (typeof data.warn_at === 'number') setWarnAt(data.warn_at)
        if (typeof data.end_at === 'number') setEndAt(data.end_at)
      })
      .catch(() => { /* keep defaults */ })
    return () => { cancelled = true }
  }, [])

  // --- Session status poll (guardrails + ended flag) ---

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`/api/v1/sessions/${sessionToken}/status`)
        if (!res.ok) return
        const data: SessionStatus = await res.json()
        if (cancelled) return
        setViolations(data.guardrail_violations)
        if (data.status === 'completed' || data.status === 'destroyed') {
          setSessionEnded(true)
        }
      } catch {
        // ignore poll failures — this only drives the banner
      }
    }
    poll()
    const id = window.setInterval(poll, STATUS_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [sessionToken])

  // --- Auto-scroll + textarea auto-resize ---
  //
  // The chat is rendered inside the page's natural flow, so the scroll
  // container is `window`. Track whether the user has scrolled up: if they
  // have, suspend auto-scroll until they hit the bottom again or send a new
  // message. Lets them read past content without being yanked down by every
  // streamed token.
  useEffect(() => {
    const onScroll = () => {
      const doc = document.documentElement
      const distanceFromBottom = doc.scrollHeight - (window.scrollY + window.innerHeight)
      userScrolledUp.current = distanceFromBottom > 80
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (userScrolledUp.current) return
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const max = Math.floor(window.innerHeight * 0.4)
    el.style.height = Math.min(el.scrollHeight, max) + 'px'
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }, [input])

  // --- Send ---

  const send = async () => {
    const text = input.trim()
    const readyChips = attachments.filter(a => a.status === 'ready').map(a => a.filename)
    // Allow file-only turns: user drops a PDF without typing anything and
    // expects CBC to examine it. Backend seeds a default prompt in that case.
    if ((!text && readyChips.length === 0) || isStreaming || sessionEnded) return
    // Sending a new message means the user wants to see the response; pull
    // them back to the bottom even if they had scrolled up to read history.
    userScrolledUp.current = false
    setMessages(prev => [...prev, {
      role: 'user',
      content: text || `Please examine: ${readyChips.join(', ')}`,
      attachments: readyChips.length ? readyChips : undefined,
    }])
    setInput('')
    setError('')
    streamingTextRef.current = ''
    setStreamingText('')
    setIsStreaming(true)
    // Re-open the SSE stream in case the previous one closed after `done`.
    openStream()
    try {
      const res = await fetch('/internal/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_token: sessionToken,
          content: text,
          language: lang,
          attachments: readyChips,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      // Clear the ready chips now that they "shipped" with the turn.
      setAttachments(prev => prev.filter(a => a.status !== 'ready'))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('chat_error', lang))
      setIsStreaming(false)
    }
  }

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // --- End session ---

  const endSession = async () => {
    setShowEndConfirm(false)
    if (sessionEnded) return
    userScrolledUp.current = false
    setError('')
    streamingTextRef.current = ''
    setStreamingText('')
    isSummaryStreamRef.current = true
    setIsSummaryStream(true)
    setIsStreaming(true)
    openStream()
    try {
      const res = await fetch('/internal/close-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: sessionToken, language: lang }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('chat_error', lang))
      setIsStreaming(false)
      isSummaryStreamRef.current = false
      setIsSummaryStream(false)
    }
  }

  // --- File upload ---

  const uploadFiles = async (files: File[]) => {
    if (sessionEnded) return
    for (const file of files) {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
      setAttachments(prev => [...prev, { id, filename: file.name, status: 'uploading' }])
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await fetch(`/internal/upload/${encodeURIComponent(sessionToken)}`, {
          method: 'POST',
          body: formData,
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: 'Upload failed' }))
          throw new Error(body.detail || `HTTP ${res.status}`)
        }
        setAttachments(prev => prev.map(a => a.id === id ? { ...a, status: 'ready' } : a))
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed'
        setAttachments(prev => prev.map(a => a.id === id ? { ...a, status: 'failed', error: msg } : a))
      }
    }
  }

  const onFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (files.length) uploadFiles(files)
  }

  const removeChip = (id: string) => {
    setAttachments(prev => prev.filter(a => a.id !== id))
  }

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    const files = Array.from(e.dataTransfer.files || [])
    if (files.length) uploadFiles(files)
  }
  const suppress = (e: React.DragEvent<HTMLDivElement>) => { e.preventDefault(); e.stopPropagation() }

  // --- Copy summary to clipboard ---

  const lastSummary = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === 'summary') return messages[i].content
    return ''
  }, [messages])

  const copySummary = async () => {
    if (!lastSummary) return
    try {
      await navigator.clipboard.writeText(lastSummary)
      setSummaryCopied(true)
      setTimeout(() => setSummaryCopied(false), 2000)
    } catch { /* clipboard permission denied; non-fatal */ }
  }

  // --- Render ---

  const inputDisabled = sessionEnded || isStreaming || bangedOnGuardrails

  return (
    <div
      className="flex flex-col w-full max-w-4xl mx-auto mt-6 px-4 pb-6"
      onDragEnter={suppress} onDragOver={suppress} onDrop={onDrop}
    >
      {violations >= warnAt && !bangedOnGuardrails && (
        <div className="bg-amber-50 border border-amber-300 rounded-lg px-4 py-2 text-xs text-amber-800 mb-3">
          {t('chat_guardrail_warning', lang)}
        </div>
      )}
      {bangedOnGuardrails && !sessionEnded && (
        <div className="bg-red-50 border border-red-300 rounded-lg px-4 py-3 text-sm text-red-800 mb-3">
          {t('chat_session_ended_guardrails', lang)}
        </div>
      )}

      <div className="flex-1 space-y-4 mb-4">
        {messages.map((m, i) => <Bubble key={i} message={m} lang={lang} onCopySummary={copySummary} summaryCopied={summaryCopied} />)}
        {isStreaming && streamingText && (
          <Bubble message={{ role: isSummaryStream ? 'summary' : 'assistant', content: streamingText }} lang={lang} streaming />
        )}
        {isStreaming && !streamingText && (
          // HRDD-style activity bubble: makes it visually obvious the system
          // hasn't hung. Pulsing dot + label that switches between "preparing"
          // (haven't seen a token yet) and "thinking" (i18n default), so the
          // user can tell the difference between "still warming up" and
          // "actively generating but slow first token".
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-lg px-4 py-3 bg-white border border-gray-200 text-gray-600">
              <div className="flex items-center gap-2 text-sm">
                <span className="inline-block w-2 h-2 bg-uni-blue rounded-full animate-pulse" />
                {t('chat_thinking', lang)}
              </div>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {sessionEnded && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-700 mb-3">
          <div className="font-semibold mb-1">{t('chat_session_ended_title', lang)}</div>
          <p>{t('chat_session_ended_body', lang)}</p>
        </div>
      )}

      {error && <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-uni-red mb-3">{error}</div>}

      {!sessionEnded && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-3">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {attachments.map(a => (
                <span key={a.id}
                  className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-full border
                    ${a.status === 'ready' ? 'bg-green-50 border-green-200 text-green-800'
                      : a.status === 'failed' ? 'bg-red-50 border-red-200 text-red-800'
                      : 'bg-gray-50 border-gray-200 text-gray-700'}`}
                  title={a.error || ''}
                >
                  <span className="font-mono">{a.filename}</span>
                  <span className="opacity-60">
                    {a.status === 'ready' ? t('chat_attach_ready', lang)
                      : a.status === 'failed' ? t('chat_attach_failed', lang)
                      : t('chat_attach_uploading', lang)}
                  </span>
                  <button onClick={() => removeChip(a.id)} aria-label={t('chat_attach_remove', lang)}
                    className="ml-1 text-gray-400 hover:text-gray-700">&times;</button>
                </span>
              ))}
            </div>
          )}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder={t('chat_placeholder', lang)}
            disabled={inputDisabled}
            rows={2}
            className="w-full resize-none border-0 focus:ring-0 outline-none text-sm disabled:bg-transparent disabled:text-gray-400"
          />
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => fileInputRef.current?.click()}
                disabled={sessionEnded}
                className="text-xs border border-gray-300 text-gray-600 rounded-lg px-2.5 py-1 hover:bg-gray-50 disabled:opacity-50"
              >
                {t('chat_attach_button', lang)}
              </button>
              <input ref={fileInputRef} type="file" multiple accept=".pdf,.txt,.md,.docx" onChange={onFilePick} className="hidden" />
              <button type="button" onClick={() => setShowEndConfirm(true)}
                disabled={sessionEnded || isStreaming}
                className="text-xs border border-gray-300 text-gray-600 rounded-lg px-2.5 py-1 hover:bg-gray-50 disabled:opacity-50"
              >
                {t('chat_end_session', lang)}
              </button>
              {cbaSidepanelEnabled && (
                <button
                  type="button"
                  onClick={() => setPanelOpen(true)}
                  className="text-xs border border-gray-300 text-gray-600 rounded-lg px-2.5 py-1 hover:bg-gray-50 relative"
                  title={t('citations_panel_title', lang)}
                >
                  {t('citations_panel_open', lang)}
                  {sources.length > 0 && (
                    <span className="ml-1.5 inline-flex items-center justify-center text-[10px] font-semibold w-4 h-4 rounded-full bg-uni-blue text-white">
                      {sources.length}
                    </span>
                  )}
                </button>
              )}
            </div>
            <button type="button" onClick={send}
              disabled={inputDisabled || (!input.trim() && !attachments.some(a => a.status === 'ready'))}
              className="text-sm bg-uni-blue text-white rounded-lg px-4 py-1.5 hover:opacity-90 disabled:opacity-50"
            >
              {t('chat_send', lang)}
            </button>
          </div>
        </div>
      )}

      {showEndConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setShowEndConfirm(false)}>
          <div className="bg-white rounded-xl shadow-lg max-w-md p-6" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-2">{t('chat_end_confirm_title', lang)}</h3>
            <p className="text-sm text-gray-600 mb-4">{t('chat_end_confirm_body', lang)}</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowEndConfirm(false)} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50">
                {t('chat_end_confirm_no', lang)}
              </button>
              <button onClick={endSession} className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90">
                {t('chat_end_confirm_yes', lang)}
              </button>
            </div>
          </div>
        </div>
      )}
      {cbaSidepanelEnabled && (
        <CitationsPanel
          lang={lang}
          sources={sources}
          open={panelOpen}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  )
}


function Bubble({
  message, lang, streaming, onCopySummary, summaryCopied,
}: {
  message: ChatMessage
  lang: LangCode
  streaming?: boolean
  onCopySummary?: () => void
  summaryCopied?: boolean
}) {
  const isUser = message.role === 'user'
  const isSummary = message.role === 'summary'

  if (isSummary) {
    return (
      <div className="border border-uni-blue/30 bg-blue-50/40 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-uni-blue">{t('chat_summary_heading', lang)}</h3>
          {!streaming && onCopySummary && (
            <button onClick={onCopySummary}
              className="text-xs border border-uni-blue/40 text-uni-blue rounded-lg px-2 py-1 hover:bg-blue-100"
            >
              {summaryCopied ? t('chat_summary_copied', lang) : t('chat_summary_copy', lang)}
            </button>
          )}
        </div>
        <div className="prose prose-sm max-w-none text-gray-800">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${isUser ? 'bg-uni-blue text-white' : 'bg-white border border-gray-200 text-gray-800'}`}>
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {message.attachments.map(f => (
              <span key={f} className={`text-[11px] px-2 py-0.5 rounded-full font-mono ${isUser ? 'bg-white/15' : 'bg-gray-100 text-gray-700'}`}>{f}</span>
            ))}
          </div>
        )}
        {isUser ? (
          <div className="whitespace-pre-wrap">{message.content}</div>
        ) : (
          <div className="prose prose-sm max-w-none text-gray-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
