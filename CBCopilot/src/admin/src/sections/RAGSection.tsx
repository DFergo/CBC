import { useEffect, useRef, useState } from 'react'
import {
  listGlobalRAG,
  uploadGlobalRAG,
  deleteGlobalRAG,
  getGlobalRAGStats,
  reindexGlobalRAG,
} from '../api'
import type { RAGDocument, RAGStats } from '../api'

export default function RAGSection() {
  const [docs, setDocs] = useState<RAGDocument[]>([])
  const [stats, setStats] = useState<RAGStats | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = async () => {
    try {
      const [{ documents }, s] = await Promise.all([listGlobalRAG(), getGlobalRAGStats()])
      setDocs(documents)
      setStats(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => { refresh() }, [])

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setError('')
    setBusy(true)
    try {
      await uploadGlobalRAG(f)
      if (fileRef.current) fileRef.current.value = ''
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (name: string) => {
    setError('')
    setBusy(true)
    try {
      await deleteGlobalRAG(name)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const onReindex = async () => {
    setError('')
    setBusy(true)
    try {
      const s = await reindexGlobalRAG()
      setStats(s)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const fmtSize = (n: number) => {
    if (n < 1024) return `${n} B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
    return `${(n / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-1">Global RAG documents</h3>
      <p className="text-sm text-gray-500 mb-3">
        Upload CBAs, company policies, and related documents. Sprint 3 stores files; real
        indexing (LlamaIndex) lands in Sprint 5.
      </p>

      {stats && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 mb-4">
          <strong>{stats.document_count}</strong> documents, total {fmtSize(stats.total_size_bytes)}. {stats.note}
        </div>
      )}

      {error && <p className="text-uni-red text-sm mb-3">{error}</p>}

      <div className="flex gap-3 mb-4">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt,.md"
          onChange={onUpload}
          disabled={busy}
          className="text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
        />
        <button
          onClick={onReindex}
          disabled={busy}
          className="text-sm border border-gray-300 text-gray-700 rounded-lg px-3 py-2 hover:bg-gray-50 disabled:opacity-50"
        >
          Reindex
        </button>
      </div>

      <ul className="border border-gray-200 rounded-lg divide-y divide-gray-200">
        {docs.length === 0 && <li className="px-3 py-2 text-sm text-gray-400">No documents yet.</li>}
        {docs.map(d => (
          <li key={d.name} className="flex items-center justify-between px-3 py-2 text-sm">
            <div>
              <span className="font-medium text-gray-800">{d.name}</span>
              <span className="ml-2 text-xs text-gray-400">{fmtSize(d.size)}</span>
            </div>
            <button
              onClick={() => onDelete(d.name)}
              disabled={busy}
              className="text-xs text-uni-red hover:underline disabled:opacity-50"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
