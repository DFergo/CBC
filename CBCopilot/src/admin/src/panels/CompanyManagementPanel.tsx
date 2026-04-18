import { useEffect, useState } from 'react'
import { listCompanies, createCompany, updateCompany, deleteCompany } from '../api'
import type { Company } from '../api'

const RAG_MODES: Company['rag_mode'][] = ['own_only', 'inherit_frontend', 'inherit_all', 'combine_frontend', 'combine_all']
const PROMPT_MODES: Company['prompt_mode'][] = ['inherit', 'own', 'combine']

export default function CompanyManagementPanel({ frontendId }: { frontendId: string }) {
  const [companies, setCompanies] = useState<Company[]>([])
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [newName, setNewName] = useState('')

  const reload = () => {
    listCompanies(frontendId)
      .then(r => setCompanies(r.companies))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }

  useEffect(reload, [frontendId])

  const add = async () => {
    if (!newSlug.trim() || !newName.trim()) return
    setError('')
    try {
      await createCompany(frontendId, { slug: newSlug.trim(), display_name: newName.trim() })
      setNewSlug('')
      setNewName('')
      reload()
      setInfo('Added')
      setTimeout(() => setInfo(''), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const patch = async (slug: string, patchBody: Partial<Company>) => {
    setError('')
    try {
      await updateCompany(frontendId, slug, patchBody)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const remove = async (slug: string) => {
    if (!confirm(`Remove company ${slug}?`)) return
    setError('')
    try {
      await deleteCompany(frontendId, slug)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-gray-700">Companies</h4>
        <span className="text-xs text-gray-500">{companies.length} total{info && <span className="ml-2">— {info}</span>}</span>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Company buttons on the CompanySelectPage of this frontend. Per-company prompts and RAG documents are managed from the General tab endpoints — the admin UI for those lands in Sprint 4B.
      </p>

      {error && <p className="text-uni-red text-xs mb-2">{error}</p>}

      <div className="flex flex-wrap items-end gap-2 mb-4 pb-3 border-b border-gray-100">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Slug (lowercase, a-z 0-9 -)</label>
          <input value={newSlug} onChange={e => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
            placeholder="amcor" className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-40" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Display name</label>
          <input value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="Amcor" className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-56" />
        </div>
        <button onClick={add} disabled={!newSlug.trim() || !newName.trim()}
          className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5 hover:opacity-90 disabled:opacity-50">
          + Add company
        </button>
      </div>

      {companies.length === 0 ? (
        <p className="text-sm text-gray-400">No companies yet.</p>
      ) : (
        <div className="space-y-2">
          {companies.map(c => (
            <div key={c.slug} className={`border border-gray-200 rounded-lg p-3 text-sm ${c.enabled ? '' : 'opacity-60'}`}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-gray-800">{c.display_name}</span>
                  <code className="text-xs text-gray-400">{c.slug}</code>
                  {c.is_compare_all && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">Compare All</span>}
                </div>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={c.enabled} onChange={e => patch(c.slug, { enabled: e.target.checked })} />
                    enabled
                  </label>
                  <button onClick={() => remove(c.slug)} className="text-xs text-uni-red hover:underline">Delete</button>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-2">
                <div>
                  <label className="block text-[11px] text-gray-500">Sort order</label>
                  <input type="number" value={c.sort_order}
                    onChange={e => patch(c.slug, { sort_order: parseInt(e.target.value, 10) || 0 })}
                    className="w-full border border-gray-200 rounded px-2 py-1 text-xs" />
                </div>
                <div>
                  <label className="block text-[11px] text-gray-500">Prompt mode</label>
                  <select value={c.prompt_mode}
                    onChange={e => patch(c.slug, { prompt_mode: e.target.value })}
                    className="w-full border border-gray-200 rounded px-2 py-1 text-xs">
                    {PROMPT_MODES.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-gray-500">RAG mode</label>
                  <select value={c.rag_mode}
                    onChange={e => patch(c.slug, { rag_mode: e.target.value })}
                    className="w-full border border-gray-200 rounded px-2 py-1 text-xs">
                    {RAG_MODES.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              </div>
              <div className="mt-2">
                <label className="block text-[11px] text-gray-500">Country tags (comma-separated ISO codes)</label>
                <input type="text"
                  value={(c.country_tags || []).join(', ')}
                  onChange={e => patch(c.slug, { country_tags: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                  placeholder="DE, FR, IT, PL"
                  className="w-full border border-gray-200 rounded px-2 py-1 text-xs font-mono" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
