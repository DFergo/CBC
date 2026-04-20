// Admin sessions viewer (Sprint 7, D6=A).
// Columns distilled from HRDD's SessionsTab — dropped role/mode (CBC has a
// single user profile) and the internal-summary / report indicators (ADR-004).
// Added CBC-specific columns: country and guardrail violations.
import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { listSessions, getAdminSession, toggleSessionFlag, destroySession } from './api'
import type { SessionSummary, SessionDetail } from './api'

type Filter = 'all' | 'active' | 'completed' | 'flagged'

const POLL_INTERVAL_MS = 10000

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return '—'
  const seconds = (Date.now() - d) / 1000
  if (seconds < 60) return 'just now'
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.round(minutes)} min`
  const hours = minutes / 60
  if (hours < 24) return `${Math.round(hours)} h`
  const days = hours / 24
  return `${Math.round(days)} d`
}

function statusBadge(status: string) {
  const palette =
    status === 'active' ? 'bg-green-100 text-green-700 border-green-200'
      : status === 'completed' ? 'bg-gray-100 text-gray-700 border-gray-200'
      : status === 'destroyed' ? 'bg-red-50 text-red-600 border-red-200'
      : 'bg-amber-50 text-amber-700 border-amber-200'
  return <span className={`text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${palette}`}>{status}</span>
}

export default function SessionsTab() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const r = await listSessions()
      setSessions(r.sessions)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [refresh])

  const open = async (token: string) => {
    setError('')
    setSelected(null)
    try {
      const detail = await getAdminSession(token)
      setSelected(detail)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load session')
    }
  }

  const handleFlag = async (token: string) => {
    try {
      const r = await toggleSessionFlag(token)
      setSessions(prev => prev.map(s => s.token === token ? { ...s, flagged: r.flagged } : s))
      if (selected?.token === token) setSelected({ ...selected, flagged: r.flagged })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to toggle flag')
    }
  }

  const handleDestroy = async (token: string) => {
    if (!confirm(`Permanently destroy session ${token}? This deletes the conversation, uploads, and session RAG. Cannot be undone.`)) return
    setBusy(true)
    try {
      await destroySession(token)
      setSessions(prev => prev.filter(s => s.token !== token))
      if (selected?.token === token) setSelected(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to destroy session')
    } finally {
      setBusy(false)
    }
  }

  const filtered = useMemo(() => {
    if (filter === 'all') return sessions
    if (filter === 'flagged') return sessions.filter(s => s.flagged)
    return sessions.filter(s => s.status === filter)
  }, [sessions, filter])

  return (
    <div className="max-w-6xl">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-800">Sessions</h2>
          <div className="flex gap-1">
            {(['all', 'active', 'completed', 'flagged'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`text-xs px-3 py-1 rounded-full border ${filter === f ? 'bg-uni-blue text-white border-uni-blue' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="px-4 py-2 text-uni-red text-sm">{error}</p>}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <th className="text-left px-4 py-2 font-medium">Token</th>
                <th className="text-left px-4 py-2 font-medium">Frontend</th>
                <th className="text-left px-4 py-2 font-medium">Company</th>
                <th className="text-left px-4 py-2 font-medium">Country</th>
                <th className="text-center px-3 py-2 font-medium">Status</th>
                <th className="text-right px-3 py-2 font-medium">Msgs</th>
                <th className="text-right px-3 py-2 font-medium" title="Guardrail violations">Viol.</th>
                <th className="text-right px-4 py-2 font-medium">Last activity</th>
                <th className="text-center px-3 py-2 font-medium">Flag</th>
                <th className="text-right px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && (
                <tr><td colSpan={10} className="px-4 py-6 text-center text-gray-400">Loading…</td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-6 text-center text-gray-400">No sessions.</td></tr>
              )}
              {filtered.map(s => (
                <tr key={s.token} onClick={() => open(s.token)} className="hover:bg-blue-50/40 cursor-pointer">
                  <td className="px-4 py-2 font-mono text-xs">{s.token}</td>
                  <td className="px-4 py-2 text-xs text-gray-700">{s.frontend_name || s.frontend_id || '—'}</td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {s.is_compare_all ? <span className="italic">Compare All</span> : (s.company_display_name || s.company_slug || '—')}
                  </td>
                  <td className="px-4 py-2 text-xs font-mono text-gray-500">{s.country || '—'}</td>
                  <td className="px-3 py-2 text-center">{statusBadge(s.status)}</td>
                  <td className="px-3 py-2 text-right text-xs text-gray-700">{s.message_count}</td>
                  <td className="px-3 py-2 text-right text-xs">
                    {s.guardrail_violations > 0 ? (
                      <span className={`font-medium ${s.guardrail_violations >= 5 ? 'text-uni-red' : 'text-amber-700'}`}>
                        {s.guardrail_violations}
                      </span>
                    ) : (
                      <span className="text-gray-300">0</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-gray-500">{timeAgo(s.last_activity)}</td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={e => { e.stopPropagation(); handleFlag(s.token) }}
                      title={s.flagged ? 'Unflag' : 'Flag'}
                      className={`text-lg leading-none ${s.flagged ? 'text-amber-500' : 'text-gray-300 hover:text-amber-500'}`}
                    >
                      {s.flagged ? '★' : '☆'}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={e => { e.stopPropagation(); handleDestroy(s.token) }}
                      disabled={busy}
                      className="text-xs text-uni-red hover:underline disabled:opacity-50"
                    >
                      Destroy
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && <DetailDrawer detail={selected} onClose={() => setSelected(null)} onFlag={handleFlag} onDestroy={handleDestroy} />}
    </div>
  )
}


function DetailDrawer({
  detail, onClose, onFlag, onDestroy,
}: {
  detail: SessionDetail
  onClose: () => void
  onFlag: (token: string) => void
  onDestroy: (token: string) => void
}) {
  const survey = detail.survey as Record<string, string>
  return (
    <div className="fixed inset-0 bg-black/40 flex justify-end z-50" onClick={onClose}>
      <aside
        onClick={e => e.stopPropagation()}
        className="bg-white w-full max-w-3xl h-full overflow-y-auto shadow-xl"
      >
        <header className="sticky top-0 bg-white border-b border-gray-200 px-5 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs font-mono text-gray-500">{detail.token}</div>
            <h3 className="text-lg font-semibold text-gray-800">
              {detail.is_compare_all ? 'Compare All' : (survey.company_display_name || survey.company_slug || 'Session')}
              <span className="ml-2">{statusBadge(detail.status)}</span>
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => onFlag(detail.token)} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-2.5 py-1 hover:bg-gray-50">
              {detail.flagged ? 'Unflag' : 'Flag'}
            </button>
            <button onClick={() => onDestroy(detail.token)} className="text-sm border border-uni-red text-uni-red rounded-lg px-2.5 py-1 hover:bg-red-50">
              Destroy
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-1">&times;</button>
          </div>
        </header>

        <section className="px-5 py-4 border-b border-gray-100 text-sm text-gray-700">
          <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Survey</h4>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
            <dt className="text-gray-500">Frontend</dt><dd>{detail.frontend_name || detail.frontend_id || '—'}</dd>
            <dt className="text-gray-500">Language</dt><dd>{detail.language}</dd>
            <dt className="text-gray-500">Country</dt><dd>{survey.country || '—'}</dd>
            <dt className="text-gray-500">Region</dt><dd>{survey.region || '—'}</dd>
            <dt className="text-gray-500">Name</dt><dd>{survey.name || <span className="italic text-gray-400">anonymous</span>}</dd>
            <dt className="text-gray-500">Email</dt><dd>{survey.email || <span className="italic text-gray-400">none</span>}</dd>
            <dt className="text-gray-500">Organisation</dt><dd>{survey.organization || '—'}</dd>
            <dt className="text-gray-500">Position</dt><dd>{survey.position || '—'}</dd>
            <dt className="text-gray-500">Created</dt><dd>{detail.created_at || '—'}</dd>
            <dt className="text-gray-500">Last activity</dt><dd>{detail.last_activity || '—'}</dd>
            {detail.completed_at && (<>
              <dt className="text-gray-500">Completed</dt><dd>{detail.completed_at}</dd>
            </>)}
            <dt className="text-gray-500">Violations</dt>
            <dd className={detail.guardrail_violations >= 5 ? 'text-uni-red font-medium' : detail.guardrail_violations > 0 ? 'text-amber-700' : ''}>
              {detail.guardrail_violations}
            </dd>
          </dl>
          {survey.initial_query && (
            <div className="mt-3">
              <div className="text-xs text-gray-500 mb-1">Initial query</div>
              <div className="text-sm italic text-gray-700">{survey.initial_query}</div>
            </div>
          )}
        </section>

        {detail.uploads.length > 0 && (
          <section className="px-5 py-4 border-b border-gray-100">
            <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Uploads ({detail.uploads.length})</h4>
            <ul className="text-xs space-y-1">
              {detail.uploads.map(u => (
                <li key={u.name} className="flex items-center justify-between">
                  <span className="font-mono">{u.name}</span>
                  <span className="text-gray-400">{u.size} bytes</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="px-5 py-4">
          <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Conversation ({detail.message_count} messages)</h4>
          <div className="space-y-4">
            {detail.messages.map((m, i) => (
              <div key={i}>
                <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">
                  {m.role} {m.timestamp && <span className="ml-2 lowercase">{m.timestamp}</span>}
                </div>
                {m.attachments.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    {m.attachments.map(f => (
                      <span key={f} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 border border-gray-200 font-mono">{f}</span>
                    ))}
                  </div>
                )}
                <div className={`rounded-lg px-3 py-2 text-sm ${m.role === 'user' ? 'bg-blue-50 text-gray-800' : m.role === 'assistant_summary' ? 'bg-uni-blue/5 border border-uni-blue/20 text-gray-800' : 'bg-gray-50 text-gray-800'}`}>
                  {m.role === 'user' ? (
                    <div className="whitespace-pre-wrap">{m.content}</div>
                  ) : (
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  )
}
