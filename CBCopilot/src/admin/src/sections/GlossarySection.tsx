// Pattern adapted from HRDDHelper/src/admin/src/RAGTab.tsx (Glossary block).
// Primary editing mode is download-edit-upload of the JSON file.
import { useEffect, useRef, useState } from 'react'
import { getGlossary, saveGlossary } from '../api'
import type { GlossaryTerm } from '../api'
import { downloadJSON } from '../utils'
import { useT } from '../i18n'

export default function GlossarySection() {
  const [glossary, setGlossary] = useState<GlossaryTerm[]>([])
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const uploadRef = useRef<HTMLInputElement>(null)
  const { t } = useT()

  useEffect(() => {
    getGlossary()
      .then(({ terms }) => setGlossary(terms))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setSuccess('')
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      if (!Array.isArray(data.terms)) {
        throw new Error(t('glossary_invalid_terms_array'))
      }
      for (const term of data.terms) {
        if (!term.term) {
          throw new Error(t('glossary_missing_term_field', { snippet: JSON.stringify(term).slice(0, 80) }))
        }
      }
      const result = await saveGlossary(data.terms)
      setGlossary(result.terms)
      setSuccess(t('glossary_updated', { count: result.terms.length }))
      setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('generic_invalid_json'))
    } finally {
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  return (
    <section className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-lg font-semibold text-gray-800">
          {t('glossary_heading')}
          <span className="text-sm font-normal text-gray-400 ml-2">({t('glossary_entry_count', { count: glossary.length })})</span>
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => downloadJSON({ terms: glossary }, 'glossary.json')}
            className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors hover:bg-gray-50"
          >
            {t('generic_download_json')}
          </button>
          <label className="bg-uni-blue text-white rounded-lg px-3 py-1.5 text-sm font-medium transition-colors hover:opacity-90 cursor-pointer">
            {t('generic_upload_json')}
            <input
              ref={uploadRef}
              type="file"
              accept=".json"
              onChange={handleUpload}
              className="hidden"
            />
          </label>
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-3">
        {t('glossary_description')}
      </p>

      {error && <p className="text-uni-red text-sm mb-2">{error}</p>}
      {success && <p className="text-green-700 text-sm mb-2">{success}</p>}

      {glossary.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-uni-blue hover:underline mb-2"
          >
            {expanded ? t('glossary_hide') : t('glossary_show_all', { count: glossary.length })}
          </button>
          {expanded && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm mt-2">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('glossary_col_term')}</th>
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('glossary_col_definition')}</th>
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('glossary_col_translations')}</th>
                  </tr>
                </thead>
                <tbody>
                  {glossary.map(t => (
                    <tr key={t.term} className="border-b border-gray-100">
                      <td className="px-2 py-2 font-medium text-gray-800 whitespace-nowrap align-top">{t.term}</td>
                      <td className="px-2 py-2 text-gray-600 text-xs align-top">{t.definition || ''}</td>
                      <td className="px-2 py-2 text-gray-500 text-xs align-top">
                        {Object.entries(t.translations || {}).map(([lang, val]) => `${lang}: ${val}`).join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}
