// Pattern adapted from HRDDHelper/src/admin/src/RAGTab.tsx (Organizations block).
// Primary editing mode is download-edit-upload of the JSON file.
import { useEffect, useRef, useState } from 'react'
import { getOrganizations, saveOrganizations } from '../api'
import type { Organization } from '../api'
import { downloadJSON } from '../utils'
import { useT } from '../i18n'

export default function OrgsSection() {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const uploadRef = useRef<HTMLInputElement>(null)
  const { t } = useT()

  useEffect(() => {
    getOrganizations()
      .then(({ organizations }) => setOrgs(organizations))
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
      if (!Array.isArray(data.organizations)) {
        throw new Error(t('orgs_invalid_orgs_array'))
      }
      for (const o of data.organizations) {
        if (!o.name) {
          throw new Error(t('orgs_missing_name_field', { snippet: JSON.stringify(o).slice(0, 80) }))
        }
      }
      const result = await saveOrganizations(data.organizations)
      setOrgs(result.organizations)
      setSuccess(t('orgs_updated', { count: result.organizations.length }))
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
          {t('orgs_heading')}
          <span className="text-sm font-normal text-gray-400 ml-2">({t('orgs_entry_count', { count: orgs.length })})</span>
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => downloadJSON({ organizations: orgs }, 'organizations.json')}
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
        {t('orgs_description')}
      </p>

      {error && <p className="text-uni-red text-sm mb-2">{error}</p>}
      {success && <p className="text-green-700 text-sm mb-2">{success}</p>}

      {orgs.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-uni-blue hover:underline mb-2"
          >
            {expanded ? t('orgs_hide') : t('orgs_show_all', { count: orgs.length })}
          </button>
          {expanded && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm mt-2">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('orgs_col_name')}</th>
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('orgs_col_type')}</th>
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('orgs_col_country')}</th>
                    <th className="text-left px-2 py-2 font-medium text-gray-600">{t('orgs_col_description')}</th>
                  </tr>
                </thead>
                <tbody>
                  {orgs.map((o, i) => (
                    <tr key={i} className="border-b border-gray-100">
                      <td className="px-2 py-2 font-medium text-gray-800 align-top whitespace-nowrap">{o.name}</td>
                      <td className="px-2 py-2 text-gray-500 text-xs align-top">{o.type}</td>
                      <td className="px-2 py-2 text-gray-500 text-xs align-top">{o.country}</td>
                      <td className="px-2 py-2 text-gray-600 text-xs align-top">{o.description || ''}</td>
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
