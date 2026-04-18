import { useEffect, useState } from 'react'

interface SidecarConfig {
  frontend_id?: string
  auth_required?: boolean
}

export default function App() {
  const [config, setConfig] = useState<SidecarConfig | null>(null)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    fetch('/internal/config')
      .then(r => r.json())
      .then(setConfig)
      .catch(e => setError(String(e)))
  }, [])

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'system-ui, sans-serif',
      background: '#f9fafb',
    }}>
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ fontSize: '1.75rem', color: '#111827', marginBottom: '0.5rem' }}>
          Collective Bargaining Copilot
        </h1>
        <p style={{ color: '#6b7280' }}>
          Sprint 1 — scaffolding online. Full UI lands in Sprint 2.
        </p>
        {config && (
          <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginTop: '1rem' }}>
            Frontend: {config.frontend_id}
          </p>
        )}
        {error && (
          <p style={{ color: '#dc2626', fontSize: '0.875rem', marginTop: '1rem' }}>
            Sidecar unreachable: {error}
          </p>
        )}
      </div>
    </div>
  )
}
