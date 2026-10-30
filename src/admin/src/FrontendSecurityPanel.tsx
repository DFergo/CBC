// Adapted from HRDDHelper/src/admin/src/FrontendSecurityPanel.tsx — backend
// access mode per frontend (signed / trusted network / legacy), optional own
// secret and extra headers. Secret values are write-only.
import { useState } from 'react'
import { updateFrontend } from './api'
import type { FrontendAuthMode, FrontendCredentials, FrontendInfo } from './api'
import { useT } from './i18n'
import type { AdminTranslationKeys } from './i18n'

// 32 random bytes as hex (64 chars) — must also be set as CBC_BACKEND_SECRET on the frontend.
export function generateSecret(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

// "Name: value" per line → object. Blank lines ignored.
export function parseHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const i = line.indexOf(':')
    if (i <= 0) continue
    const name = line.slice(0, i).trim()
    const value = line.slice(i + 1).trim()
    if (name && value) out[name] = value
  }
  return out
}

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm'
const MODES: FrontendAuthMode[] = ['signed', 'unsigned', 'legacy']
const MODE_LABEL: Record<FrontendAuthMode, AdminTranslationKeys> = {
  signed: 'frontends_mode_signed',
  unsigned: 'frontends_mode_unsigned',
  legacy: 'frontends_mode_legacy',
}
const MODE_HELP: Record<FrontendAuthMode, AdminTranslationKeys> = {
  signed: 'frontends_mode_signed_help',
  unsigned: 'frontends_mode_unsigned_help',
  legacy: 'frontends_mode_legacy_help',
}

export interface AccessDraft { mode: FrontendAuthMode; secret: string; headers: string }

// Mode + optional own secret + optional extra headers. Shared by the register form and the Security panel.
export function AccessFields({ draft, setDraft, globalSecret, secretHint }: {
  draft: AccessDraft
  setDraft: (d: AccessDraft) => void
  globalSecret: boolean
  secretHint?: string
}) {
  const { t } = useT()
  const set = (k: keyof AccessDraft, v: string) => setDraft({ ...draft, [k]: v })
  const needsSecret = draft.mode === 'signed' && !globalSecret && !draft.secret.trim()
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('frontends_access_label')}</label>
          <select value={draft.mode} onChange={e => set('mode', e.target.value)} className={inputCls}>
            {MODES.map(m => <option key={m} value={m}>{t(MODE_LABEL[m])}</option>)}
          </select>
        </div>
        {draft.mode === 'signed' && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('frontends_own_secret_label')}</label>
            <div className="flex gap-2">
              <input type="text" value={draft.secret} onChange={e => set('secret', e.target.value)}
                placeholder={secretHint ?? (globalSecret ? t('frontends_secret_placeholder_global') : t('frontends_secret_placeholder_required'))}
                className={`${inputCls} font-mono`} autoComplete="off" spellCheck={false} />
              <button type="button" onClick={() => set('secret', generateSecret())}
                className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 whitespace-nowrap">
                {t('frontends_generate')}
              </button>
            </div>
          </div>
        )}
      </div>
      <p className={`text-xs ${draft.mode === 'unsigned' ? 'text-amber-700' : 'text-gray-500'}`}>{t(MODE_HELP[draft.mode])}</p>
      {needsSecret && <p className="text-xs text-uni-red">{t('frontends_no_installation_secret')}</p>}
      <details className="text-sm" open={!!draft.headers}>
        <summary className="cursor-pointer text-xs text-gray-500 select-none">{t('frontends_extra_headers_summary')}</summary>
        <textarea value={draft.headers} onChange={e => set('headers', e.target.value)} rows={2}
          placeholder={'CF-Access-Client-Id: …\nCF-Access-Client-Secret: …'}
          className={`${inputCls} font-mono mt-2`} spellCheck={false} />
        <p className="text-xs text-gray-400 mt-1">{t('frontends_extra_headers_help')}</p>
      </details>
    </div>
  )
}

export function draftToCredentials(d: AccessDraft): FrontendCredentials {
  const out: FrontendCredentials = { auth_mode: d.mode }
  if (d.mode === 'signed' && d.secret.trim()) out.signing_secret = d.secret.trim()
  const headers = parseHeaders(d.headers)
  if (Object.keys(headers).length) out.extra_headers = headers
  return out
}

export function SigningBadge({ f }: { f: FrontendInfo }) {
  const { t } = useT()
  const base = 'text-[10px] px-1.5 py-0.5 rounded border whitespace-nowrap'
  const mode = f.auth_mode ?? (f.signing_enabled ? 'signed' : 'legacy')
  return (
    <>
      {mode === 'signed' && (f.signing_enabled
        ? <span className={`${base} bg-green-50 text-green-700 border-green-200`}>
            {t('frontends_badge_signed')}{f.signing_source === 'own' ? ` · ${t('frontends_badge_own_secret')}` : ''}
          </span>
        : <span className={`${base} bg-red-50 text-uni-red border-red-200`}>{t('frontends_badge_no_secret')}</span>)}
      {mode === 'unsigned' && <span className={`${base} bg-amber-50 text-amber-700 border-amber-200`}>{t('frontends_badge_unsigned')}</span>}
      {mode === 'legacy' && <span className={`${base} bg-gray-50 text-gray-500 border-gray-200`}>{t('frontends_badge_legacy')}</span>}
      {mode === 'signed' && f.surface_auth === 'trusted-network' && (
        <span className={`${base} bg-amber-50 text-amber-700 border-amber-200`} title={t('frontends_security_reports_trusted')}>
          {t('frontends_badge_accepts_unsigned')}
        </span>
      )}
    </>
  )
}

export default function FrontendSecurityPanel({ f, globalSecret, onSaved }: { f: FrontendInfo; globalSecret: boolean; onSaved: () => void }) {
  const { t } = useT()
  const [url, setUrl] = useState(f.url)
  const [draft, setDraft] = useState<AccessDraft>({ mode: f.auth_mode ?? 'legacy', secret: '', headers: '' })
  const [clearOwn, setClearOwn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const save = async (data: FrontendCredentials & { url?: string }, done: string) => {
    setBusy(true); setErr(''); setMsg('')
    try {
      await updateFrontend(f.frontend_id, data)
      setDraft(d => ({ ...d, secret: '', headers: '' }))
      setClearOwn(false)
      setMsg(done)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const urlChanged = url.trim().replace(/\/+$/, '') !== f.url
  const modeChanged = draft.mode !== (f.auth_mode ?? 'legacy')
  const dirty = urlChanged || modeChanged || !!draft.secret.trim() || !!draft.headers.trim() || clearOwn

  // URL + mode + credentials go in ONE update, verified against the frontend with the final combination.
  const saveAll = () => {
    const data: FrontendCredentials & { url?: string } = draftToCredentials(draft)
    if (urlChanged) data.url = url.trim()
    if (clearOwn && !draft.secret.trim()) data.signing_secret = ''
    save(data, t('frontends_security_saved'))
  }

  const source = f.signing_source === 'own'
    ? t('frontends_secret_source_own')
    : f.signing_source === 'global' ? t('frontends_secret_source_global') : t('frontends_secret_source_none')

  return (
    <div className="mt-2 border-t border-gray-100 pt-3 space-y-3" onClick={e => e.stopPropagation()}>
      <div className="text-xs text-gray-500">
        {t('frontends_security_current_label')}: <strong>{t(MODE_LABEL[f.auth_mode ?? 'legacy'])}</strong>
        {f.auth_mode === 'signed' && <> · {t('frontends_security_secret_label')}: <strong>{source}</strong></>}
        {' · '}{t('frontends_security_headers_label')}: <strong>{f.extra_header_names?.length ? f.extra_header_names.join(', ') : t('frontends_secret_source_none')}</strong>
      </div>
      {f.auth_mode === 'signed' && f.surface_auth === 'trusted-network' && (
        <p className="text-xs text-amber-700">{t('frontends_security_reports_trusted')}</p>
      )}
      <div>
        <label className="block text-xs text-gray-500 mb-1">{t('frontends_backend_url_label')}</label>
        <input type="text" value={url} onChange={e => setUrl(e.target.value)} spellCheck={false} className={`${inputCls} font-mono`} />
      </div>
      <AccessFields draft={draft} setDraft={setDraft} globalSecret={globalSecret}
        secretHint={f.signing_source === 'own' ? t('frontends_secret_placeholder_keep') : undefined} />
      {f.signing_source === 'own' && draft.mode === 'signed' && (
        <label className="flex items-center gap-2 text-xs text-gray-600">
          <input type="checkbox" checked={clearOwn} onChange={e => setClearOwn(e.target.checked)} />
          {t('frontends_remove_own_secret')}
        </label>
      )}
      <div className="flex gap-2">
        <button onClick={saveAll} disabled={busy || !dirty}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          {busy ? t('generic_saving') : t('generic_save')}
        </button>
        {!!f.extra_header_names?.length && (
          <button onClick={() => save({ extra_headers: {} }, t('frontends_headers_removed'))} disabled={busy}
            className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50">
            {t('frontends_remove_extra_headers')}
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400">{t('frontends_rotation_help')}</p>
      {msg && <p className="text-xs text-green-700">{msg}</p>}
      {err && <p className="text-xs text-uni-red">{err}</p>}
    </div>
  )
}
