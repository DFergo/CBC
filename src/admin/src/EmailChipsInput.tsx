// Email-list editor adapted from HRDDHelper/src/admin/src/SMTPTab.tsx.
// Input + Add button + chips with X. Enter adds. Duplicates rejected silently.
import { useState } from 'react'

interface Props {
  value: string[]
  onChange: (emails: string[]) => void
  placeholder?: string
}

export default function EmailChipsInput({ value, onChange, placeholder }: Props) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const trimmed = draft.trim().toLowerCase()
    if (!trimmed || value.includes(trimmed)) return
    onChange([...value, trimmed])
    setDraft('')
  }

  const remove = (email: string) => {
    onChange(value.filter(e => e !== email))
  }

  return (
    <div>
      <div className="flex gap-2 mb-2">
        <input
          type="email"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), add())}
          placeholder={placeholder || 'admin@example.com'}
          className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
        />
        <button
          onClick={add}
          disabled={!draft.trim()}
          className="bg-uni-blue text-white rounded-lg px-3 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          Add
        </button>
      </div>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map(email => (
            <span
              key={email}
              className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 border border-blue-200 rounded-full text-xs text-gray-700"
            >
              {email}
              <button
                type="button"
                onClick={() => remove(email)}
                className="text-gray-400 hover:text-uni-red"
                aria-label={`Remove ${email}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
