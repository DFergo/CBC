// Tier-aware: omit both props for global, pass frontendId for frontend-level,
// pass frontendId+companySlug for company-level. Same UX for all three tiers.
// Preview resolution button (Sprint 4B D4) shows which tier actually wins at
// resolution time.
import { useEffect, useState } from 'react'
import { deletePrompt, listPrompts, previewPromptResolution, readPrompt, savePrompt } from '../api'
import type { PromptFile, PromptResolution } from '../api'

interface Props {
  frontendId?: string
  companySlug?: string
}

export default function PromptsSection({ frontendId, companySlug }: Props) {
  const [prompts, setPrompts] = useState<PromptFile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<PromptResolution | null>(null)

  const tierLabel = companySlug ? 'company' : frontendId ? 'frontend' : 'global'

  const refresh = async () => {
    try {
      const { prompts } = await listPrompts(frontendId, companySlug)
      setPrompts(prompts)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    setSelected(null)
    setContent('')
    setPreview(null)
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId, companySlug])

  const open = async (name: string) => {
    setSelected(name)
    setSaveStatus('')
    setError('')
    setPreview(null)
    setLoading(true)
    try {
      const { content } = await readPrompt(name, frontendId, companySlug)
      setContent(content)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const save = async () => {
    if (!selected) return
    setSaveStatus('Saving…')
    setError('')
    try {
      await savePrompt(selected, content, frontendId, companySlug)
      setSaveStatus('Saved')
      setTimeout(() => setSaveStatus(''), 2000)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  const removeOverride = async () => {
    if (!selected) return
    if (!confirm(`Delete the ${tierLabel}-level ${selected}? Resolution will fall back to the next tier up.`)) return
    try {
      await deletePrompt(selected, frontendId, companySlug)
      setSelected(null)
      setContent('')
      setPreview(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const runPreview = async () => {
    if (!selected) return
    setError('')
    try {
      // Compare All mode = company tier skipped per SPEC §2.4; use the toggle
      // only when the file literally IS compare_all.md.
      const isCompareAll = selected === 'compare_all.md'
      const r = await previewPromptResolution(selected, frontendId, companySlug, isCompareAll)
      setPreview(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const heading = tierLabel === 'global'
    ? 'Global prompts'
    : tierLabel === 'frontend'
    ? `Frontend prompts — ${frontendId}`
    : `Company prompts — ${frontendId} / ${companySlug}`

  const description = tierLabel === 'global'
    ? 'Defaults shipped with the image, editable here. Per-frontend / per-company overrides live elsewhere.'
    : tierLabel === 'frontend'
    ? 'Overrides applied to this frontend. Companies inherit from here unless they have their own.'
    : 'Overrides applied only to this company. Winner-takes-all: a file here fully replaces the frontend/global version for this company.'

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">{heading}</h3>
      <p className="text-sm text-gray-500 mb-4">{description}</p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <ul className="space-y-1 border border-gray-200 rounded-lg divide-y divide-gray-200">
            {prompts.length === 0 && (
              <li className="px-3 py-2 text-sm text-gray-400">
                No {tierLabel}-level prompts.{tierLabel !== 'global' && ' Upload or create one; otherwise resolution falls back to a higher tier.'}
              </li>
            )}
            {prompts.map(p => (
              <li key={p.name}>
                <button
                  onClick={() => open(p.name)}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                    selected === p.name ? 'bg-blue-50 text-uni-blue font-medium' : 'text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {p.name}
                  <span className="block text-xs text-gray-400">{p.size} bytes</span>
                </button>
              </li>
            ))}
          </ul>
          {tierLabel !== 'global' && (
            <NewPromptForm frontendId={frontendId} companySlug={companySlug} onCreated={refresh} />
          )}
        </div>

        <div className="md:col-span-2">
          {!selected && <p className="text-sm text-gray-400">Select a prompt on the left to edit.</p>}
          {selected && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-700">{selected}</h4>
                <div className="flex items-center gap-2">
                  {saveStatus && <span className="text-xs text-gray-500">{saveStatus}</span>}
                  <button onClick={runPreview} className="text-xs border border-gray-300 rounded px-2 py-1 hover:bg-gray-50">
                    Preview resolution
                  </button>
                </div>
              </div>
              {preview && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs">
                  <strong>Resolution:</strong> wins at <code className="text-blue-800">{preview.tier}</code> tier
                  {preview.path && <> (<code className="text-gray-600">{preview.path}</code>)</>}
                  {!preview.found && ' — no file anywhere in the chain'}
                </div>
              )}
              {loading ? (
                <p className="text-sm text-gray-400">Loading…</p>
              ) : (
                <>
                  <textarea
                    value={content}
                    onChange={e => setContent(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 font-mono text-xs leading-relaxed focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                    rows={20}
                  />
                  <div className="flex gap-2">
                    <button onClick={save} className="bg-uni-blue text-white rounded-lg px-4 py-2 text-sm font-medium hover:opacity-90">
                      Save
                    </button>
                    {tierLabel !== 'global' && (
                      <button onClick={removeOverride} className="border border-uni-red text-uni-red rounded-lg px-3 py-2 text-sm hover:bg-red-50">
                        Delete this override
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function NewPromptForm({ frontendId, companySlug, onCreated }: { frontendId?: string; companySlug?: string; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  const create = async () => {
    let n = name.trim()
    if (!n) return
    if (!n.endsWith('.md')) n = `${n}.md`
    setError('')
    try {
      await savePrompt(n, '# New override\n', frontendId, companySlug)
      setName('')
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="mt-2">
      <div className="flex gap-1">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="core.md"
          className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs font-mono"
        />
        <button
          onClick={create}
          disabled={!name.trim()}
          className="text-xs bg-uni-blue text-white rounded px-2 py-1 hover:opacity-90 disabled:opacity-50"
        >
          + Create
        </button>
      </div>
      {error && <p className="text-uni-red text-xs mt-1">{error}</p>}
    </div>
  )
}
