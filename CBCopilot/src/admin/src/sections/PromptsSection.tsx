// Tier-aware prompt editor. Same UX at every tier: the canonical 5 prompts are
// always visible, each shows where it currently resolves (global / frontend /
// company badge), and Save always writes at the current tier — creating an
// override if there isn't one yet. "Remove this-tier override" falls back to
// the parent tier and is only enabled when the current tier owns the file.
//
// Company tier exception: only cba_advisor.md is editable per Daniel's spec
// (companies tune their advisor; core/guardrails/compare_all/context_template
// stay frontend or global).
import { useEffect, useState } from 'react'
import { deletePrompt, previewPromptResolution, savePrompt } from '../api'
import type { PromptResolution } from '../api'

interface CanonicalPrompt {
  name: string
  label: string
  description: string
  editableAtCompany: boolean
  visibleAtCompany: boolean  // compare_all and summary aren't company concerns — hide them at that tier
}

const CANONICAL_PROMPTS: CanonicalPrompt[] = [
  { name: 'core.md', label: 'Core', description: 'System role + persona. Sets who the assistant is and how it behaves overall.', editableAtCompany: false, visibleAtCompany: true },
  { name: 'guardrails.md', label: 'Guardrails', description: 'Refusal rules and safety constraints. Always injected on top of the role prompt.', editableAtCompany: false, visibleAtCompany: true },
  { name: 'cba_advisor.md', label: 'CBA Advisor', description: 'Main role prompt for single-company chat sessions.', editableAtCompany: true, visibleAtCompany: true },
  { name: 'compare_all.md', label: 'Compare All', description: 'Used when the user picks Compare All instead of a single company. Cross-company by definition — no per-company override.', editableAtCompany: false, visibleAtCompany: false },
  { name: 'context_template.md', label: 'Context Template', description: 'Wraps RAG snippets and survey context before sending to the model.', editableAtCompany: false, visibleAtCompany: true },
  { name: 'summary.md', label: 'Summary', description: 'Run at session end: takes the full conversation and produces the user summary that gets emailed out.', editableAtCompany: false, visibleAtCompany: false },
]

type Tier = 'global' | 'frontend' | 'company'

interface Props {
  frontendId?: string
  companySlug?: string
}

export default function PromptsSection({ frontendId, companySlug }: Props) {
  const [resolutions, setResolutions] = useState<Record<string, PromptResolution>>({})
  const [selected, setSelected] = useState<string>(CANONICAL_PROMPTS[0].name)
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')

  const currentTier: Tier = companySlug ? 'company' : frontendId ? 'frontend' : 'global'
  const parentTier: Tier | null = currentTier === 'company' ? 'frontend' : currentTier === 'frontend' ? 'global' : null

  const visiblePrompts = currentTier === 'company'
    ? CANONICAL_PROMPTS.filter(p => p.visibleAtCompany)
    : CANONICAL_PROMPTS

  const reloadAll = async () => {
    setError('')
    try {
      const entries = await Promise.all(
        visiblePrompts.map(async p => {
          const r = await previewPromptResolution(p.name, frontendId, companySlug, p.name === 'compare_all.md')
          return [p.name, r] as const
        }),
      )
      const map: Record<string, PromptResolution> = {}
      entries.forEach(([k, v]) => { map[k] = v })
      setResolutions(map)
      // Reload the currently-shown content if the selected prompt's resolution moved
      const sel = entries.find(([k]) => k === selected)
      if (sel) {
        setContent(sel[1].content || '')
        setDirty(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    setSelected(visiblePrompts[0].name)
    setSaveStatus('')
    setError('')
    reloadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frontendId, companySlug])

  const open = (name: string) => {
    setSelected(name)
    setSaveStatus('')
    setError('')
    setContent(resolutions[name]?.content || '')
    setDirty(false)
  }

  const meta = CANONICAL_PROMPTS.find(p => p.name === selected)!
  const sel = resolutions[selected]
  const ownsAtCurrentTier = sel?.tier === currentTier
  const readOnly = currentTier === 'company' && !meta.editableAtCompany

  const save = async () => {
    setSaveStatus('Saving…')
    setError('')
    try {
      setLoading(true)
      await savePrompt(selected, content, frontendId, companySlug)
      setSaveStatus(`Saved at ${currentTier} tier`)
      setTimeout(() => setSaveStatus(''), 2500)
      await reloadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaveStatus('')
    } finally {
      setLoading(false)
    }
  }

  const removeOverride = async () => {
    if (!parentTier) return
    if (!confirm(`Remove this ${currentTier}-tier override of ${meta.label}? This prompt will fall back to the ${parentTier} version.`)) return
    setError('')
    try {
      setLoading(true)
      await deletePrompt(selected, frontendId, companySlug)
      setSaveStatus(`Reverted to ${parentTier} tier`)
      setTimeout(() => setSaveStatus(''), 2500)
      await reloadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const heading = currentTier === 'global'
    ? 'Global prompts'
    : currentTier === 'frontend'
    ? `Frontend prompts — ${frontendId}`
    : `Company prompts — ${companySlug}`

  const description = currentTier === 'global'
    ? 'The five core prompts shipped with the image. Everything below inherits from these unless overridden.'
    : currentTier === 'frontend'
    ? 'The same five prompts. Edit and save here to override the global version for this frontend; companies inherit from here unless they have their own override.'
    : 'The same five prompts inherited from the frontend (or global). Only CBA Advisor is editable at the company tier — the rest stay at frontend / global to keep guardrails and core behaviour consistent.'

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">{heading}</h3>
      <p className="text-sm text-gray-500 mb-4">{description}</p>

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <ul className="border border-gray-200 rounded-lg divide-y divide-gray-200">
            {visiblePrompts.map(p => {
              const r = resolutions[p.name]
              const isActive = selected === p.name
              const lockedHere = currentTier === 'company' && !p.editableAtCompany
              return (
                <li key={p.name}>
                  <button
                    onClick={() => open(p.name)}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                      isActive ? 'bg-blue-50 text-uni-blue font-medium' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span>{p.label}</span>
                      {r && <TierBadge tier={r.tier} currentTier={currentTier} />}
                    </div>
                    <div className="text-[11px] text-gray-400 font-mono mt-0.5">
                      {p.name}{lockedHere && <span className="ml-2 text-amber-600">read-only here</span>}
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        <div className="md:col-span-2">
          {sel && (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="text-sm font-medium text-gray-800">{meta.label} <span className="text-xs text-gray-400 font-mono">{meta.name}</span></h4>
                  <p className="text-xs text-gray-500 mt-0.5">{meta.description}</p>
                </div>
                {saveStatus && <span className="text-xs text-green-700 whitespace-nowrap">{saveStatus}</span>}
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs flex items-center justify-between flex-wrap gap-2">
                <div>
                  <strong>Currently resolving at:</strong> <code className="text-blue-800">{sel.tier}</code> tier
                  {sel.path && <> · <code className="text-gray-600 text-[11px]">{sel.path}</code></>}
                  {!sel.found && ' — no file anywhere in the chain'}
                </div>
                {readOnly && (
                  <span className="text-amber-700">Editable only at frontend / global tier</span>
                )}
              </div>

              <textarea
                value={content}
                onChange={e => { if (!readOnly) { setContent(e.target.value); setDirty(true) } }}
                readOnly={readOnly}
                className={`w-full border border-gray-300 rounded-lg px-3 py-2 font-mono text-xs leading-relaxed focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none ${readOnly ? 'bg-gray-50 cursor-not-allowed' : ''}`}
                rows={20}
              />

              {!readOnly && (
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={save}
                    disabled={loading || !dirty}
                    className="bg-uni-blue text-white rounded-lg px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
                  >
                    Save at {currentTier} tier
                  </button>
                  {currentTier !== 'global' && ownsAtCurrentTier && (
                    <button
                      onClick={removeOverride}
                      disabled={loading}
                      className="border border-uni-red text-uni-red rounded-lg px-3 py-2 text-sm hover:bg-red-50 disabled:opacity-50"
                    >
                      Remove this-tier override (revert to {parentTier})
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function TierBadge({ tier, currentTier }: { tier: PromptResolution['tier']; currentTier: Tier }) {
  const isOwn = tier === currentTier
  const palette = tier === 'company'
    ? 'bg-purple-100 text-purple-700 border-purple-200'
    : tier === 'frontend'
    ? 'bg-blue-100 text-blue-700 border-blue-200'
    : tier === 'global'
    ? 'bg-gray-100 text-gray-700 border-gray-200'
    : 'bg-red-50 text-red-700 border-red-200'
  return (
    <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border ${palette}`} title={isOwn ? 'Owned at this tier' : 'Inherited'}>
      {tier === 'none' ? 'missing' : tier}{isOwn && ' ◆'}
    </span>
  )
}
