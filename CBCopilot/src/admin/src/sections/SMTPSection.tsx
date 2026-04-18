// SMTP config + notification toggles + per-frontend admin-recipients override.
import { useEffect, useState } from 'react'
import {
  getSMTPConfig, saveSMTPConfig, testSMTP,
  listFrontends,
  getFrontendNotificationOverride,
  saveFrontendNotificationOverride,
  deleteFrontendNotificationOverride,
} from '../api'
import type { SMTPConfig, FrontendInfo, NotificationOverride, NotificationOverrideResponse } from '../api'
import EmailChipsInput from '../EmailChipsInput'

export default function SMTPSection() {
  const [cfg, setCfg] = useState<SMTPConfig | null>(null)
  const [saveStatus, setSaveStatus] = useState('')
  const [testStatus, setTestStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getSMTPConfig().then(setCfg).catch(e => setError(String(e)))
  }, [])

  const update = (patch: Partial<SMTPConfig>) => {
    setCfg(c => c ? { ...c, ...patch } : c)
  }

  const save = async () => {
    if (!cfg) return
    setSaveStatus('Saving…')
    setError('')
    try {
      const saved = await saveSMTPConfig(cfg)
      setCfg(saved)
      setSaveStatus('Saved')
      setTimeout(() => setSaveStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  const runTest = async () => {
    setTestStatus('Sending…')
    setError('')
    try {
      const r = await testSMTP()
      setTestStatus(r.ok ? 'Test email sent' : `Failed: ${r.error}`)
    } catch (e) {
      setTestStatus('')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!cfg) {
    return (
      <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">SMTP</h3>
        <p className="text-sm text-gray-400">Loading…</p>
      </section>
    )
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-lg font-semibold text-gray-800">SMTP</h3>
        {saveStatus && <span className="text-xs text-gray-500">{saveStatus}</span>}
      </div>
      <p className="text-sm text-gray-500 mb-4">
        Outgoing email for auth codes (Sprint 7), user session summaries, and admin notifications.
        Password stays on the data volume — redacted in GET responses.
      </p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Host</label>
          <input type="text" value={cfg.host} onChange={e => update({ host: e.target.value })}
            placeholder="smtp.example.org" className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Port</label>
          <input type="number" value={cfg.port} onChange={e => update({ port: parseInt(e.target.value, 10) })}
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Username</label>
          <input type="text" value={cfg.username} onChange={e => update({ username: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Password</label>
          <input type="password" value={cfg.password} onChange={e => update({ password: e.target.value })}
            placeholder="leave *** to keep existing" className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">From address</label>
          <input type="email" value={cfg.from_address} onChange={e => update({ from_address: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        </div>
        <div className="flex items-center pt-5">
          <input id="use_tls" type="checkbox" checked={cfg.use_tls} onChange={e => update({ use_tls: e.target.checked })}
            className="rounded border-gray-300" />
          <label htmlFor="use_tls" className="ml-2 text-sm text-gray-700">Use STARTTLS</label>
        </div>
      </div>

      {/* Admin notification emails (global default) */}
      <div className="mt-5 border-t border-gray-200 pt-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Admin notification emails (global)</label>
        <p className="text-xs text-gray-500 mb-2">
          Recipients for admin notifications system-wide. Type an email and press Enter or click Add. Per-frontend overrides can replace or extend this list — see below.
        </p>
        <EmailChipsInput
          value={cfg.admin_notification_emails}
          onChange={emails => update({ admin_notification_emails: emails })}
          placeholder="admin@uniglobalunion.org"
        />
      </div>

      {/* Notification toggles */}
      <div className="mt-4 border-t border-gray-200 pt-4">
        <h4 className="text-sm font-medium text-gray-700 mb-2">Email notifications</h4>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.send_summary_to_user}
              onChange={e => update({ send_summary_to_user: e.target.checked })}
              className="rounded border-gray-300" />
            Send session summary to the user (to the email they provided in the survey)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.send_summary_to_admin}
              onChange={e => update({ send_summary_to_admin: e.target.checked })}
              className="rounded border-gray-300" />
            Send session summary to the admin(s)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfg.send_new_document_to_admin}
              onChange={e => update({ send_new_document_to_admin: e.target.checked })}
              className="rounded border-gray-300" />
            Notify admin(s) when a user uploads a new document in chat
          </label>
        </div>
      </div>

      <div className="flex gap-2 mt-4 items-center">
        <button onClick={save} className="text-sm bg-uni-blue text-white rounded-lg px-3 py-2 hover:opacity-90">Save SMTP config</button>
        <button onClick={runTest} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50">Send test email</button>
        {testStatus && <span className="text-xs text-gray-500">{testStatus}</span>}
      </div>

      <FrontendOverrideBlock />
    </section>
  )
}

function FrontendOverrideBlock() {
  const [frontends, setFrontends] = useState<FrontendInfo[]>([])
  const [selected, setSelected] = useState('')
  const [override, setOverride] = useState<NotificationOverride | null>(null)
  const [resolved, setResolved] = useState<string[]>([])
  const [hasOverride, setHasOverride] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    listFrontends().then(({ frontends }) => setFrontends(frontends)).catch(e => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!selected) {
      setOverride(null); setResolved([]); setHasOverride(false); setDirty(false); setStatus(''); return
    }
    getFrontendNotificationOverride(selected)
      .then((r: NotificationOverrideResponse) => {
        setHasOverride(!!r.override)
        setOverride(r.override || { admin_emails_mode: 'replace', admin_notification_emails: [] })
        setResolved(r.resolved_admin_emails)
        setDirty(false)
      })
      .catch(e => setError(String(e)))
  }, [selected])

  const save = async () => {
    if (!selected || !override) return
    setStatus('Saving…')
    setError('')
    try {
      const r = await saveFrontendNotificationOverride(selected, override)
      setHasOverride(!!r.override)
      setResolved(r.resolved_admin_emails)
      setDirty(false)
      setStatus('Saved')
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    }
  }

  const remove = async () => {
    if (!selected) return
    if (!confirm('Remove the per-frontend override? This frontend will fall back to the global admin emails.')) return
    try {
      await deleteFrontendNotificationOverride(selected)
      const r = await getFrontendNotificationOverride(selected)
      setHasOverride(!!r.override)
      setOverride(r.override || { admin_emails_mode: 'replace', admin_notification_emails: [] })
      setResolved(r.resolved_admin_emails)
      setDirty(false)
      setStatus('Override removed.')
      setTimeout(() => setStatus(''), 2500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="mt-6 border-t border-gray-200 pt-4">
      <h4 className="text-sm font-medium text-gray-700 mb-1">Per-frontend admin recipients</h4>
      <p className="text-xs text-gray-500 mb-3">
        Override the admin-notification recipients for a specific frontend (useful when a sector-specific deployment
        has its own responsible admin). Only affects the "summary to admin" and "new document to admin" notifications.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <label className="text-sm text-gray-700">Frontend:</label>
        <select
          value={selected}
          onChange={e => setSelected(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
        >
          <option value="">— select —</option>
          {frontends.map(fe => <option key={fe.frontend_id} value={fe.frontend_id}>{fe.name || fe.frontend_id}</option>)}
        </select>
        {status && <span className="text-xs text-gray-500">{status}</span>}
      </div>

      {selected && override && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-3">
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-700">Mode:</label>
            <select
              value={override.admin_emails_mode}
              onChange={e => { setOverride({ ...override, admin_emails_mode: e.target.value as 'replace' | 'append' }); setDirty(true) }}
              className="border border-gray-300 rounded-lg px-3 py-1 text-sm"
            >
              <option value="replace">Replace global</option>
              <option value="append">Append to global</option>
            </select>
            {hasOverride && (
              <button onClick={remove} className="text-xs text-uni-red hover:underline ml-auto">Remove override</button>
            )}
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Admin emails for this frontend</label>
            <EmailChipsInput
              value={override.admin_notification_emails}
              onChange={emails => { setOverride({ ...override, admin_notification_emails: emails }); setDirty(true) }}
              placeholder="sector-lead@example.org"
            />
          </div>
          <div className="text-xs text-gray-600">
            <strong>Resolved recipients (preview):</strong> {resolved.length > 0 ? resolved.join(', ') : '— none —'}
          </div>
          <button
            onClick={save}
            disabled={!dirty}
            className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
          >
            Save override
          </button>
        </div>
      )}
    </div>
  )
}
