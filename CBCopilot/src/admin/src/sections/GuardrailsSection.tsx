// Read-only runtime-guardrails viewer (Sprint 7.5 D4=A).
// Collapsible card mounted at the bottom of General tab. Collapsed by
// default so it doesn't dominate the page — click the header to expand
// when tuning / auditing the rules. The pattern catalogue is only
// fetched once the admin opens the card.
import { useEffect, useState } from 'react'
import { getGuardrailsInfo } from '../api'
import type { GuardrailsInfo } from '../api'

export default function GuardrailsSection() {
  const [data, setData] = useState<GuardrailsInfo | null>(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!expanded || data || error) return
    getGuardrailsInfo('en')
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [expanded, data, error])

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between text-left"
        aria-expanded={expanded}
      >
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Runtime guardrails</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            Pattern-based filter that runs before every user turn hits the LLM.
          </p>
        </div>
        <span className={`text-gray-400 transition-transform ml-3 ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
      </button>

      {expanded && (
        <div className="mt-5">
          <p className="text-sm text-gray-500 mb-4">
            A triggered turn is blocked — the user gets a fixed response instead of an LLM reply, and the session's
            violation counter increments. Once the session reaches the end threshold, it is auto-completed and locked
            for further turns. Rules are hardcoded in v1; edit <code>services/guardrails.py</code> to tune them.
          </p>

          {error && <p className="text-uni-red text-sm">{error}</p>}
          {!data && !error && <p className="text-sm text-gray-400">Loading…</p>}

          {data && (
            <>
              <div className="grid grid-cols-2 gap-4 mb-5">
                <div className="border border-gray-200 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-0.5">Warn threshold</div>
                  <div className="text-2xl font-semibold text-amber-700">{data.thresholds.warn_at}</div>
                  <p className="text-[11px] text-gray-500 mt-1">Amber banner appears in ChatShell from this many violations onwards.</p>
                </div>
                <div className="border border-gray-200 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-0.5">End threshold</div>
                  <div className="text-2xl font-semibold text-uni-red">{data.thresholds.end_at}</div>
                  <p className="text-[11px] text-gray-500 mt-1">Session auto-completed + flagged the moment it reaches this count.</p>
                </div>
              </div>

              <div className="space-y-3">
                {data.categories.map(cat => (
                  <div key={cat.category} className="border border-gray-200 rounded-lg">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50/60">
                      <div>
                        <div className="text-sm font-semibold text-gray-800">{cat.label}</div>
                        <code className="text-[11px] text-gray-500">{cat.category}</code>
                      </div>
                      <span className="text-xs text-gray-500">{cat.patterns.length} pattern{cat.patterns.length === 1 ? '' : 's'}</span>
                    </div>
                    <ul className="divide-y divide-gray-100">
                      {cat.patterns.map((p, i) => (
                        <li key={i} className="px-3 py-1.5 font-mono text-[11px] text-gray-700 break-all">{p}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>

              <div className="mt-5 space-y-2">
                <div className="border border-amber-200 bg-amber-50/40 rounded-lg p-3">
                  <div className="text-xs font-semibold text-amber-800 mb-1">User sees on trigger (below end threshold)</div>
                  <div className="text-sm text-gray-700">{data.sample_responses.violation}</div>
                </div>
                <div className="border border-red-200 bg-red-50/40 rounded-lg p-3">
                  <div className="text-xs font-semibold text-uni-red mb-1">User sees when session is ended</div>
                  <div className="text-sm text-gray-700">{data.sample_responses.session_ended}</div>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
