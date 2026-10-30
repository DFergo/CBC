// Sprint 22: token and prompt-cache usage per slot / connection / model, with
// the cache hit rate (cached prompt tokens / prompt tokens) as reported by the
// provider. Data: GET /admin/api/v1/llm/usage (llm_usage.py).
import { useEffect, useState } from 'react'
import { getLLMUsage, resetLLMUsage } from '../../api'
import type { LLMUsageRow } from '../../api'
import { useT } from '../../i18n'

export default function UsageCard() {
  const { t } = useT()
  const [rows, setRows] = useState<LLMUsageRow[] | null>(null)
  const load = () => { getLLMUsage().then(r => setRows(r.rows)).catch(() => setRows([])) }
  useEffect(load, [])
  const fmt = (n: number) => n.toLocaleString()
  return (
    <div className="mt-6 border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-sm font-semibold text-gray-700">{t('llm_usage_heading')}</h4>
        <div className="flex gap-2">
          <button onClick={load} className="text-xs border border-gray-300 text-gray-700 rounded px-2 py-1 hover:bg-gray-50">{t('llm_usage_refresh')}</button>
          <button onClick={() => { if (confirm(t('llm_usage_reset_confirm'))) resetLLMUsage().then(r => setRows(r.rows)) }}
            className="text-xs border border-gray-300 text-gray-700 rounded px-2 py-1 hover:bg-gray-50">{t('llm_usage_reset')}</button>
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-3">{t('llm_usage_description')}</p>
      {!rows ? null : rows.length === 0 ? (
        <p className="text-xs text-gray-400">{t('llm_usage_empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="py-1 pr-3">{t('llm_usage_col_slot')}</th>
                <th className="py-1 pr-3">{t('llm_usage_col_model')}</th>
                <th className="py-1 pr-3 text-right">{t('llm_usage_col_calls')}</th>
                <th className="py-1 pr-3 text-right">{t('llm_usage_col_prompt')}</th>
                <th className="py-1 pr-3 text-right">{t('llm_usage_col_cached')}</th>
                <th className="py-1 pr-3 text-right">{t('llm_usage_col_hit_rate')}</th>
                <th className="py-1 pr-3 text-right">{t('llm_usage_col_completion')}</th>
                <th className="py-1 text-right">{t('llm_usage_col_reasoning')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={`${r.slot}|${r.connection}|${r.model}`} className="border-b border-gray-100">
                  <td className="py-1 pr-3">{r.slot}</td>
                  <td className="py-1 pr-3 font-mono">{r.connection} / {r.model}</td>
                  <td className="py-1 pr-3 text-right">{fmt(r.calls)}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.prompt_tokens) : '—'}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.cached_tokens) : '—'}</td>
                  <td className="py-1 pr-3 text-right font-medium">{r.hit_rate == null ? '—' : `${(r.hit_rate * 100).toFixed(1)} %`}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.completion_tokens) : '—'}</td>
                  <td className="py-1 text-right">{r.calls_with_usage ? fmt(r.reasoning_tokens) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
