// Read-only runtime-guardrails viewer (Sprint 7.5 D4=A).
// Collapsible card mounted at the bottom of General tab. Collapsed by
// default so it doesn't dominate the page — click the header to expand
// when tuning / auditing the rules. The pattern catalogue is only
// fetched once the admin opens the card.
import { useEffect, useState } from 'react'
import { getGuardrailsInfo } from '../api'
import type { GuardrailsInfo } from '../api'
import { useT } from '../i18n'

export default function GuardrailsSection() {
  const [data, setData] = useState<GuardrailsInfo | null>(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const { t, lang } = useT()

  useEffect(() => {
    if (!expanded || data || error) return
    getGuardrailsInfo(lang)
      .then(setData)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [expanded, data, error, lang])

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between text-left"
        aria-expanded={expanded}
      >
        <div>
          <h3 className="text-lg font-semibold text-gray-800">{t('section_guardrails')}</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            {t('guardrails_description')}
          </p>
        </div>
        <span className={`text-gray-400 transition-transform ml-3 ${expanded ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
      </button>

      {expanded && (
        <div className="mt-5">
          <p className="text-sm text-gray-500 mb-4">
            {t('guardrails_explanation')}
          </p>

          {error && <p className="text-uni-red text-sm">{error}</p>}
          {!data && !error && <p className="text-sm text-gray-400">{t('generic_loading')}</p>}

          {data && (
            <>
              <div className="grid grid-cols-2 gap-4 mb-5">
                <div className="border border-gray-200 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-0.5">{t('guardrails_warn_threshold')}</div>
                  <div className="text-2xl font-semibold text-amber-700">{data.thresholds.warn_at}</div>
                  <p className="text-[11px] text-gray-500 mt-1">{t('guardrails_warn_hint')}</p>
                </div>
                <div className="border border-gray-200 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-0.5">{t('guardrails_end_threshold')}</div>
                  <div className="text-2xl font-semibold text-uni-red">{data.thresholds.end_at}</div>
                  <p className="text-[11px] text-gray-500 mt-1">{t('guardrails_end_hint')}</p>
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
                      <span className="text-xs text-gray-500">
                        {cat.patterns.length === 1
                          ? t('guardrails_pattern_count_one', { count: cat.patterns.length })
                          : t('guardrails_pattern_count_other', { count: cat.patterns.length })}
                      </span>
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
                  <div className="text-xs font-semibold text-amber-800 mb-1">{t('guardrails_user_sees_trigger')}</div>
                  <div className="text-sm text-gray-700">{data.sample_responses.violation}</div>
                </div>
                <div className="border border-red-200 bg-red-50/40 rounded-lg p-3">
                  <div className="text-xs font-semibold text-uni-red mb-1">{t('guardrails_user_sees_end')}</div>
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
