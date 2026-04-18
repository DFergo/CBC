// Sprint 1 placeholder. Full dashboard (General + Frontends tabs) lands in Sprint 3.
interface Props {
  onLogout: () => void
}

export default function Dashboard({ onLogout }: Props) {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-800">CBC Admin</h1>
          <p className="text-xs text-gray-500">Collective Bargaining Copilot</p>
        </div>
        <button
          onClick={onLogout}
          className="text-sm text-gray-600 hover:text-uni-red transition-colors"
        >
          Sign out
        </button>
      </header>

      <main className="p-8">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 max-w-2xl">
          <h2 className="text-xl font-semibold text-gray-800 mb-2">Sprint 1 — scaffolding online</h2>
          <p className="text-gray-600 text-sm">
            Backend is running, admin auth works. The full dashboard (General + Frontends tabs,
            prompts, RAG, companies) ships in Sprint 3.
          </p>
        </div>
      </main>
    </div>
  )
}
