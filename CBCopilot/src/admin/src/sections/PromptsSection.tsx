import { useEffect, useState } from 'react'
import { listGlobalPrompts, readGlobalPrompt, saveGlobalPrompt } from '../api'
import type { PromptFile } from '../api'

export default function PromptsSection() {
  const [prompts, setPrompts] = useState<PromptFile[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')

  const refresh = async () => {
    try {
      const { prompts } = await listGlobalPrompts()
      setPrompts(prompts)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { refresh() }, [])

  const open = async (name: string) => {
    setSelected(name)
    setSaveStatus('')
    setError('')
    setLoading(true)
    try {
      const { content } = await readGlobalPrompt(name)
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
      await saveGlobalPrompt(selected, content)
      setSaveStatus('Saved')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    }
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">Global prompts</h3>
      <p className="text-sm text-gray-500 mb-4">
        Defaults shipped with the image, editable here. Per-frontend and per-company overrides come in Sprint 4.
      </p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <ul className="space-y-1 border border-gray-200 rounded-lg divide-y divide-gray-200">
            {prompts.length === 0 && <li className="px-3 py-2 text-sm text-gray-400">No prompts yet.</li>}
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
        </div>

        <div className="md:col-span-2">
          {!selected && <p className="text-sm text-gray-400">Select a prompt on the left to edit.</p>}
          {selected && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-700">{selected}</h4>
                {saveStatus && <span className="text-xs text-gray-500">{saveStatus}</span>}
              </div>
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
                  <button
                    onClick={save}
                    className="bg-uni-blue text-white rounded-lg px-4 py-2 text-sm font-medium hover:opacity-90"
                  >
                    Save
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
