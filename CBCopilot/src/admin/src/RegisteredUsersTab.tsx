// Adapted from HRDDHelper/src/admin/src/RegisteredUsersTab.tsx.
// Directory of authorized users. Global list + per-frontend replace/append overrides.
// xlsx export, xlsx/csv additive import.
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getContacts,
  updateGlobalContacts,
  updateFrontendContacts,
  deleteFrontendContacts,
  copyContactsFromFrontend,
  exportContactsURL,
  importContacts,
  listFrontends,
  type Contact,
  type ContactsStore,
  type FrontendInfo,
} from './api'

type Scope = 'global' | `frontend:${string}`
type SortDir = 'asc' | 'desc'

const FIELDS: { key: keyof Contact; label: string }[] = [
  { key: 'email', label: 'Email' },
  { key: 'first_name', label: 'First name' },
  { key: 'last_name', label: 'Last name' },
  { key: 'organization', label: 'Organization' },
  { key: 'country', label: 'Country' },
  { key: 'sector', label: 'Sector' },
  { key: 'registered_by', label: 'Registered by' },
]

const EMPTY_CONTACT: Contact = {
  email: '',
  first_name: '',
  last_name: '',
  organization: '',
  country: '',
  sector: '',
  registered_by: '',
}

const sortKey = (scope: Scope) => `cbc_admin_users_sort_${scope}`

export default function RegisteredUsersTab() {
  const [store, setStore] = useState<ContactsStore | null>(null)
  const [frontends, setFrontends] = useState<FrontendInfo[]>([])
  const [scope, setScope] = useState<Scope>('global')
  const [rows, setRows] = useState<Contact[]>([])
  const [mode, setMode] = useState<'replace' | 'append'>('replace')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('')
  const [sortCol, setSortCol] = useState<keyof Contact>('email')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [copyFrom, setCopyFrom] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const reloadAll = async () => {
    try {
      const [s, fe] = await Promise.all([getContacts(), listFrontends()])
      setStore(s)
      setFrontends(fe.frontends || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load contacts')
    }
  }

  useEffect(() => { reloadAll() }, [])

  useEffect(() => {
    const saved = localStorage.getItem(sortKey(scope))
    if (saved) {
      try {
        const { col, dir } = JSON.parse(saved)
        setSortCol(col)
        setSortDir(dir)
      } catch { /* ignore */ }
    } else {
      setSortCol('email')
      setSortDir('asc')
    }
  }, [scope])

  useEffect(() => {
    if (!store) return
    if (scope === 'global') {
      setRows(store.global.map(c => ({ ...c })))
      setMode('replace')
    } else {
      const fid = scope.slice('frontend:'.length)
      const override = store.per_frontend?.[fid]
      if (override) {
        setRows(override.contacts.map(c => ({ ...c })))
        setMode(override.mode)
      } else {
        setRows([])
        setMode('replace')
      }
    }
    setDirty(false)
  }, [store, scope])

  const currentFrontendId = scope.startsWith('frontend:') ? scope.slice('frontend:'.length) : ''
  const hasOverride = currentFrontendId ? Boolean(store?.per_frontend?.[currentFrontendId]) : false

  const frontendsWithOverride = useMemo(
    () => new Set(Object.keys(store?.per_frontend || {})),
    [store],
  )

  const filteredSortedRows = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const filtered = f
      ? rows.filter(r => FIELDS.some(({ key }) => String(r[key] || '').toLowerCase().includes(f)))
      : rows
    return [...filtered].sort((a, b) => {
      const av = String(a[sortCol] || '').toLowerCase()
      const bv = String(b[sortCol] || '').toLowerCase()
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [rows, filter, sortCol, sortDir])

  const handleSort = (col: keyof Contact) => {
    const nextDir: SortDir = col === sortCol && sortDir === 'asc' ? 'desc' : 'asc'
    setSortCol(col)
    setSortDir(nextDir)
    localStorage.setItem(sortKey(scope), JSON.stringify({ col, dir: nextDir }))
  }

  const updateRow = (idx: number, field: keyof Contact, value: string) => {
    const target = filteredSortedRows[idx]
    setRows(prev => prev.map(r => (r === target ? { ...r, [field]: value } : r)))
    setDirty(true)
  }

  const addRow = () => {
    setRows(prev => [...prev, { ...EMPTY_CONTACT }])
    setDirty(true)
  }

  const deleteRow = (idx: number) => {
    const target = filteredSortedRows[idx]
    setRows(prev => prev.filter(r => r !== target))
    setDirty(true)
  }

  const handleSave = async () => {
    setError('')
    setInfo('')
    setSaving(true)
    try {
      const clean = rows.filter(r => r.email.trim())
      if (scope === 'global') {
        await updateGlobalContacts(clean)
      } else {
        await updateFrontendContacts(currentFrontendId, mode, clean)
      }
      await reloadAll()
      setInfo('Saved.')
      setTimeout(() => setInfo(''), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteOverride = async () => {
    if (!currentFrontendId) return
    if (!confirm('Remove the per-frontend list? The frontend will fall back to the global list.')) return
    setError('')
    try {
      await deleteFrontendContacts(currentFrontendId)
      await reloadAll()
      setInfo('Override removed.')
      setTimeout(() => setInfo(''), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const handleCopyFrom = async () => {
    if (!currentFrontendId || !copyFrom) return
    if (rows.length > 0 && !confirm(`Replace the current list with contacts from "${copyFrom}"?`)) return
    setError('')
    try {
      await copyContactsFromFrontend(currentFrontendId, copyFrom, mode)
      await reloadAll()
      setCopyFrom('')
      setInfo('Copied.')
      setTimeout(() => setInfo(''), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copy failed')
    }
  }

  const handleExport = () => {
    const token = localStorage.getItem('cbc_admin_token') || ''
    fetch(exportContactsURL(scope), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => {
        if (!r.ok) throw new Error(`Export failed (${r.status})`)
        return r.blob()
      })
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `contacts_${scope.replace(':', '_')}.xlsx`
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Export failed'))
  }

  const handleImport = async (file: File) => {
    setError('')
    setInfo('')
    try {
      const res = await importContacts(file, scope)
      await reloadAll()
      setInfo(`Imported: ${res.added} added, ${res.updated} updated, ${res.ignored_malformed} ignored.`)
      setTimeout(() => setInfo(''), 4000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    }
  }

  const sortIndicator = (col: keyof Contact) => (col !== sortCol ? '' : sortDir === 'asc' ? ' ▲' : ' ▼')

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="flex items-start justify-between mb-4 gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Registered Users</h2>
            <p className="text-sm text-gray-500 mt-1">
              Directory of authorized users (emails that can authenticate via the email-code flow).
              Global list applies to all frontends by default; per-frontend lists can replace or append.
            </p>
          </div>
          <div>
            <label className="text-sm text-gray-700 mr-2">Scope:</label>
            <select
              value={scope}
              onChange={e => setScope(e.target.value as Scope)}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
            >
              <option value="global">Global</option>
              {frontends.map(fe => (
                <option key={fe.id} value={`frontend:${fe.id}`}>
                  {fe.name || fe.id}{frontendsWithOverride.has(fe.id) ? ' ◆ custom' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>

        {scope.startsWith('frontend:') && (
          <div className="bg-gray-50 rounded-lg p-4 mb-4 flex flex-wrap items-center gap-4">
            <div>
              <label className="text-sm text-gray-700 mr-2">Mode:</label>
              <select
                value={mode}
                onChange={e => { setMode(e.target.value as 'replace' | 'append'); setDirty(true) }}
                className="border border-gray-300 rounded-lg px-3 py-1 text-sm"
              >
                <option value="replace">Replace global</option>
                <option value="append">Append to global</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-700">Copy from:</label>
              <select
                value={copyFrom}
                onChange={e => setCopyFrom(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-1 text-sm"
              >
                <option value="">— select —</option>
                {frontends.filter(fe => fe.id !== currentFrontendId && frontendsWithOverride.has(fe.id)).map(fe => (
                  <option key={fe.id} value={fe.id}>{fe.name || fe.id}</option>
                ))}
              </select>
              <button
                onClick={handleCopyFrom}
                disabled={!copyFrom}
                className="text-xs px-3 py-1 rounded-lg bg-gray-200 text-gray-700 hover:bg-gray-300 disabled:opacity-50"
              >
                Copy
              </button>
            </div>
            {hasOverride && (
              <button
                onClick={handleDeleteOverride}
                className="text-xs px-3 py-1 rounded-lg border border-uni-red text-uni-red hover:bg-red-50 ml-auto"
              >
                Remove override (fall back to global)
              </button>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 mb-3">
          <input
            type="text"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter (email, name, country…)"
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px]"
          />
          <span className="text-xs text-gray-500">{filteredSortedRows.length} / {rows.length} shown</span>
          <button onClick={addRow} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50">+ Add row</button>
          <button onClick={handleExport} className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-1.5 hover:bg-gray-50">Download XLSX</button>
          <label className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 font-medium hover:opacity-90 cursor-pointer">
            Import XLSX / CSV
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) handleImport(f)
                if (fileInputRef.current) fileInputRef.current.value = ''
              }}
            />
          </label>
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 font-medium hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>

        {error && <p className="text-uni-red text-sm mb-2">{error}</p>}
        {info && <p className="text-green-700 text-sm mb-2">{info}</p>}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                {FIELDS.map(({ key, label }) => (
                  <th
                    key={key}
                    onClick={() => handleSort(key)}
                    className="text-left px-2 py-2 font-medium text-gray-600 cursor-pointer select-none hover:bg-gray-100"
                  >
                    {label}{sortIndicator(key)}
                  </th>
                ))}
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filteredSortedRows.length === 0 && (
                <tr><td colSpan={FIELDS.length + 1} className="text-center text-gray-400 py-4">No contacts.</td></tr>
              )}
              {filteredSortedRows.map((row, idx) => (
                <tr key={idx} className="border-b border-gray-100 hover:bg-gray-50">
                  {FIELDS.map(({ key }) => (
                    <td key={key} className="px-2 py-1">
                      <input
                        type="text"
                        value={row[key] || ''}
                        onChange={e => updateRow(idx, key, e.target.value)}
                        className="w-full px-2 py-1 text-sm border border-transparent rounded focus:border-gray-300 focus:bg-white outline-none"
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right">
                    <button onClick={() => deleteRow(idx)} className="text-xs text-uni-red hover:underline">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
