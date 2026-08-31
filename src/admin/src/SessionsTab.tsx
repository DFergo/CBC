// Admin sessions viewer (Sprint 7 + polish).
// Layout: one table per frontend (Daniel's request). Global filter tabs
// apply within each group. Detail drawer pins the session summary at the
// top (when one exists) with a Copy button, plus Download / Copy-text
// buttons for every user upload.
import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  listSessions, getAdminSession, toggleSessionFlag, destroySession,
  downloadSessionUpload, copySessionUploadText,
} from './api'
import type { SessionSummary, SessionDetail } from './api'
import { useT, tAdmin } from './i18n'
import type { AdminLangCode } from './i18n'

type Filter = 'all' | 'active' | 'completed' | 'flagged'

const POLL_INTERVAL_MS = 10000
const COPYABLE_EXTS = new Set(['.txt', '.md'])

function timeAgo(iso: string | null, lang: AdminLangCode): string {
  if (!iso) return tAdmin('sessions_time_em_dash', lang)
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return tAdmin('sessions_time_em_dash', lang)
  const seconds = (Date.now() - d) / 1000
  if (seconds < 60) return tAdmin('sessions_time_just_now', lang)
  const minutes = seconds / 60
  if (minutes < 60) return tAdmin('sessions_time_min', lang, { n: Math.round(minutes) })
  const hours = minutes / 60
  if (hours < 24) return tAdmin('sessions_time_h', lang, { n: Math.round(hours) })
  const days = hours / 24
  return tAdmin('sessions_time_d', lang, { n: Math.round(days) })
}

function statusBadge(status: string) {
  const palette =
    status === 'active' ? 'bg-green-100 text-green-700 border-green-200'
      : status === 'completed' ? 'bg-gray-100 text-gray-700 border-gray-200'
      : status === 'destroyed' ? 'bg-red-50 text-red-600 border-red-200'
      : 'bg-amber-50 text-amber-700 border-amber-200'
  return <span className={`text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${palette}`}>{status}</span>
}

function ext(filename: string): string {
  const i = filename.lastIndexOf('.')
  return i >= 0 ? filename.slice(i).toLowerCase() : ''
}

export default function SessionsTab() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { t, lang } = useT()

  const refresh = useCallback(async () => {
    try {
      const r = await listSessions()
      setSessions(r.sessions)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : t('sessions_failed_load'))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setError(e instanceof Error ? e.message : t('sessions_failed_detail'))
    }
  }

  const handleFlag = async (token: string) => {
    try {
      const r = await toggleSessionFlag(token)
      setSessions(prev => prev.map(s => s.token === token ? { ...s, flagged: r.flagged } : s))
      if (selected?.token === token) setSelected({ ...selected, flagged: r.flagged })
    } catch (e) {
      setError(e instanceof Error ? e.message : t('sessions_failed_flag'))
    }
  }

  const handleDestroy = async (token: string) => {
    if (!confirm(t('sessions_destroy_row_confirm', { token }))) return
    setBusy(true)
    try {
      await destroySession(token)
      setSessions(prev => prev.filter(s => s.token !== token))
      if (selected?.token === token) setSelected(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('sessions_failed_destroy'))
    } finally {
      setBusy(false)
    }
  }

  const filtered = useMemo(() => {
    if (filter === 'all') return sessions
    if (filter === 'flagged') return sessions.filter(s => s.flagged)
    return sessions.filter(s => s.status === filter)
  }, [sessions, filter])

  // Group by frontend. Sessions without a frontend_id fall under "Unassigned".
  const grouped = useMemo(() => {
    const buckets = new Map<string, { label: string; rows: SessionSummary[] }>()
    for (const s of filtered) {
      const key = s.frontend_id || '__unassigned__'
      const label = s.frontend_name || s.frontend_id || t('sessions_unassigned_group')
      const existing = buckets.get(key)
      if (existing) {
        existing.rows.push(s)
        // Keep the best-looking label we've seen
        if (!existing.label && label) existing.label = label
      } else {
        buckets.set(key, { label, rows: [s] })
      }
    }
    // Sort groups by label (unassigned last)
    return Array.from(buckets.entries()).sort(([a, ga], [b, gb]) => {
      if (a === '__unassigned__') return 1
      if (b === '__unassigned__') return -1
      return ga.label.localeCompare(gb.label)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered])

  const filterLabel: Record<Filter, string> = {
    all: t('sessions_filter_all'),
    active: t('sessions_filter_active'),
    completed: t('sessions_filter_completed'),
    flagged: t('sessions_filter_flagged'),
  }

  return (
    <div className="max-w-6xl space-y-5">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-800">{t('sessions_title')}</h2>
        <div className="flex gap-1">
          {(['all', 'active', 'completed', 'flagged'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`text-xs px-3 py-1 rounded-full border ${filter === f ? 'bg-uni-blue text-white border-uni-blue' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}
            >
              {filterLabel[f]}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-uni-red text-sm">{error}</p>}

      {loading ? (
        <p className="text-sm text-gray-400">{t('generic_loading')}</p>
      ) : grouped.length === 0 ? (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 text-sm text-gray-400">
          {t('sessions_empty')}
        </div>
      ) : (
        grouped.map(([key, group]) => (
          <div key={key} className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-gray-50/40">
              <h3 className="text-sm font-semibold text-gray-800">{group.label}</h3>
              <span className="text-xs text-gray-500">
                {group.rows.length === 1
                  ? t('sessions_count_one', { count: group.rows.length })
                  : t('sessions_count_other', { count: group.rows.length })}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                    <th className="text-left px-4 py-2 font-medium">{t('sessions_col_token')}</th>
                    <th className="text-left px-4 py-2 font-medium">{t('sessions_col_company')}</th>
                    <th className="text-left px-4 py-2 font-medium">{t('sessions_col_country')}</th>
                    <th className="text-center px-3 py-2 font-medium">{t('sessions_col_status')}</th>
                    <th className="text-right px-3 py-2 font-medium">{t('sessions_col_messages')}</th>
                    <th className="text-right px-3 py-2 font-medium" title={t('sessions_viol_title')}>{t('sessions_viol_abbrev')}</th>
                    <th className="text-right px-4 py-2 font-medium">{t('sessions_col_last_activity')}</th>
                    <th className="text-center px-3 py-2 font-medium">{t('sessions_col_flag_header')}</th>
                    <th className="text-right px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {group.rows.map(s => (
                    <tr key={s.token} onClick={() => open(s.token)} className="hover:bg-blue-50/40 cursor-pointer">
                      <td className="px-4 py-2 font-mono text-xs">{s.token}</td>
                      <td className="px-4 py-2 text-xs text-gray-700">
                        {s.is_compare_all ? <span className="italic">{t('companies_compare_all')}</span> : (s.company_display_name || s.company_slug || t('sessions_time_em_dash'))}
                      </td>
                      <td className="px-4 py-2 text-xs font-mono text-gray-500">{s.country || t('sessions_time_em_dash')}</td>
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
                      <td className="px-4 py-2 text-right text-xs text-gray-500">{timeAgo(s.last_activity, lang)}</td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={e => { e.stopPropagation(); handleFlag(s.token) }}
                          title={s.flagged ? t('sessions_flag_star_unflag') : t('sessions_flag_star_flag')}
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
                          {t('sessions_destroy_inline')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}

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
  const [summaryCopied, setSummaryCopied] = useState(false)
  const [uploadFeedback, setUploadFeedback] = useState<Record<string, string>>({})
  const { t } = useT()

  const setFeedback = (name: string, text: string) => {
    setUploadFeedback(prev => ({ ...prev, [name]: text }))
    window.setTimeout(() => {
      setUploadFeedback(prev => {
        const next = { ...prev }
        delete next[name]
        return next
      })
    }, 2000)
  }

  const copySummary = async () => {
    if (!detail.summary) return
    try {
      await navigator.clipboard.writeText(detail.summary)
      setSummaryCopied(true)
      window.setTimeout(() => setSummaryCopied(false), 2000)
    } catch {/* ignore */}
  }

  const doDownload = async (name: string) => {
    setFeedback(name, t('sessions_upload_downloading'))
    try {
      await downloadSessionUpload(detail.token, name)
      setFeedback(name, t('sessions_upload_saved'))
    } catch (e) {
      setFeedback(name, e instanceof Error ? e.message : t('sessions_upload_failed'))
    }
  }

  const doCopyText = async (name: string) => {
    setFeedback(name, t('sessions_upload_copying'))
    try {
      await copySessionUploadText(detail.token, name)
      setFeedback(name, t('sessions_upload_copied'))
    } catch (e) {
      setFeedback(name, e instanceof Error ? e.message : t('sessions_upload_failed'))
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex justify-end z-50" onClick={onClose}>
      <aside
        onClick={e => e.stopPropagation()}
        className="bg-white w-full max-w-3xl h-full overflow-y-auto shadow-xl"
      >
        <header className="sticky top-0 bg-white border-b border-gray-200 px-5 py-3 flex items-center justify-between z-10">
          <div>
            <div className="text-xs font-mono text-gray-500">{detail.token}</div>
            <h3 className="text-lg font-semibold text-gray-800">
              {detail.is_compare_all ? t('companies_compare_all') : (survey.company_display_name || survey.company_slug || t('sessions_session_label'))}
              <span className="ml-2">{statusBadge(detail.status)}</span>
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => onFlag(detail.token)} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-2.5 py-1 hover:bg-gray-50">
              {detail.flagged ? t('sessions_unflag_drawer_button') : t('sessions_flag_drawer_button')}
            </button>
            <button onClick={() => onDestroy(detail.token)} className="text-sm border border-uni-red text-uni-red rounded-lg px-2.5 py-1 hover:bg-red-50">
              {t('sessions_destroy_drawer_button')}
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none px-1">&times;</button>
          </div>
        </header>

        {detail.summary && (
          <section className="px-5 py-4 border-b border-gray-100 bg-blue-50/30">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs uppercase tracking-wide text-uni-blue font-semibold">{t('sessions_summary_heading')}</h4>
              <button onClick={copySummary}
                className="text-xs border border-uni-blue/40 text-uni-blue rounded-lg px-2 py-1 hover:bg-blue-100">
                {summaryCopied ? t('sessions_summary_copied') : t('sessions_summary_copy_label')}
              </button>
            </div>
            <div className="prose prose-sm max-w-none text-gray-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.summary}</ReactMarkdown>
            </div>
          </section>
        )}

        <section className="px-5 py-4 border-b border-gray-100 text-sm text-gray-700">
          <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">{t('sessions_survey_heading')}</h4>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
            <dt className="text-gray-500">{t('sessions_dt_frontend')}</dt><dd>{detail.frontend_name || detail.frontend_id || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_language')}</dt><dd>{detail.language}</dd>
            <dt className="text-gray-500">{t('sessions_dt_country')}</dt><dd>{survey.country || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_region')}</dt><dd>{survey.region || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_name')}</dt><dd>{survey.name || <span className="italic text-gray-400">{t('sessions_dt_anonymous')}</span>}</dd>
            <dt className="text-gray-500">{t('sessions_dt_email')}</dt><dd>{survey.email || <span className="italic text-gray-400">{t('sessions_dt_none')}</span>}</dd>
            <dt className="text-gray-500">{t('sessions_dt_organisation')}</dt><dd>{survey.organization || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_position')}</dt><dd>{survey.position || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_created')}</dt><dd>{detail.created_at || t('sessions_time_em_dash')}</dd>
            <dt className="text-gray-500">{t('sessions_dt_last_activity')}</dt><dd>{detail.last_activity || t('sessions_time_em_dash')}</dd>
            {detail.completed_at && (<>
              <dt className="text-gray-500">{t('sessions_dt_completed')}</dt><dd>{detail.completed_at}</dd>
            </>)}
            <dt className="text-gray-500">{t('sessions_dt_violations')}</dt>
            <dd className={detail.guardrail_violations >= 5 ? 'text-uni-red font-medium' : detail.guardrail_violations > 0 ? 'text-amber-700' : ''}>
              {detail.guardrail_violations}
            </dd>
          </dl>
          {survey.initial_query && (
            <div className="mt-3">
              <div className="text-xs text-gray-500 mb-1">{t('sessions_initial_query')}</div>
              <div className="text-sm italic text-gray-700">{survey.initial_query}</div>
            </div>
          )}
        </section>

        {detail.uploads.length > 0 && (
          <section className="px-5 py-4 border-b border-gray-100">
            <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">{t('sessions_uploads_count_heading', { count: detail.uploads.length })}</h4>
            <ul className="text-xs divide-y divide-gray-100">
              {detail.uploads.map(u => {
                const canCopy = COPYABLE_EXTS.has(ext(u.name))
                const fb = uploadFeedback[u.name]
                return (
                  <li key={u.name} className="flex items-center justify-between gap-3 py-1.5">
                    <div className="min-w-0 flex-1">
                      <div className="font-mono truncate">{u.name}</div>
                      <div className="text-gray-400">{t('sessions_upload_bytes', { size: u.size })}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {fb && <span className="text-[11px] text-gray-500">{fb}</span>}
                      <button onClick={() => doDownload(u.name)}
                        className="text-[11px] border border-gray-300 text-gray-700 rounded px-2 py-0.5 hover:bg-gray-50">
                        {t('sessions_upload_download')}
                      </button>
                      {canCopy && (
                        <button onClick={() => doCopyText(u.name)}
                          className="text-[11px] border border-gray-300 text-gray-700 rounded px-2 py-0.5 hover:bg-gray-50">
                          {t('sessions_upload_copy_text')}
                        </button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        <section className="px-5 py-4">
          <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">{t('sessions_conversation_count_heading', { count: detail.message_count })}</h4>
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
