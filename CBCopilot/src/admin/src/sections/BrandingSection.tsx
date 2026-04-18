// Sprint 3 placeholder — global branding defaults.
// Backend store not built yet; lives in Sprint 4 alongside per-frontend branding override.
export default function BrandingSection() {
  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-2">Branding defaults</h3>
      <p className="text-sm text-gray-500">
        Global branding (default logo, colors, app title) is tracked in Sprint 4 alongside the
        per-frontend override UI. For now, branding comes from each frontend's
        <code className="text-xs bg-gray-100 px-1 rounded mx-1">deployment_frontend.json</code>.
      </p>
    </section>
  )
}
