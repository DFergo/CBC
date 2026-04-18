// Sprint 3 placeholder. Full Frontends tab ships in Sprint 4 (per-frontend branding, prompts, RAG, company management, session settings).
export default function FrontendsTab() {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 max-w-3xl">
      <h2 className="text-xl font-semibold text-gray-800 mb-2">Frontends</h2>
      <p className="text-sm text-gray-600 mb-4">
        Per-frontend configuration — branding overrides, prompts, RAG, company list,
        session settings — lands in Sprint 4.
      </p>
      <p className="text-xs text-gray-500">
        Backend company APIs are live now (<code>/admin/api/v1/frontends/&#123;fid&#125;/companies</code>).
        The UI to exercise them is the Sprint 4 deliverable.
      </p>
    </div>
  )
}
