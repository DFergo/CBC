// Adapted from HRDDHelper/src/admin/src/ModelCombobox.tsx. CBC additions:
// `disabled` (inherited read-only values at the per-frontend tier) and
// overridable `labels` (the embedding editor is translated).
import { useMemo, useRef, useState } from 'react'

export interface ModelComboboxLabels {
  placeholder: string
  noteEndpoint: string
  noteExact: string
  statusOutside: string
  statusNotOffered: string
}

const DEFAULT_LABELS: ModelComboboxLabels = {
  placeholder: 'Search or type a model ID',
  noteEndpoint: 'offered by the endpoint',
  noteExact: 'use exact ID',
  statusOutside: 'Outside this connection’s model list (offered by the endpoint).',
  statusNotOffered: 'Not offered by this connection — check the ID.',
}

// Single search field for picking a model ID.
//  - Typing filters `models` (the connection's allow-list if set, else everything discovered).
//  - An exact ID that the endpoint offers but the allow-list doesn't (`extra`) is offered too.
//  - "Use exact ID" commits the typed text as-is (for models the endpoint doesn't list).
// The value is only committed on pick / Enter / blur, never per keystroke.

const MAX_SHOWN = 200

function SearchIcon() {
  return (
    <svg className="w-4 h-4 text-gray-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <circle cx="9" cy="9" r="6" />
      <path d="M13.5 13.5L17 17" strokeLinecap="round" />
    </svg>
  )
}

export default function ModelCombobox({
  value, models, extra = [], onChange, placeholder, emptyHint, disabled = false, labels,
}: {
  value: string
  models: string[]          // primary list (allow-list or discovered)
  extra?: string[]          // also offered by the endpoint, selectable by exact ID only
  onChange: (id: string) => void
  placeholder?: string
  emptyHint?: string        // shown when there is nothing to list
  disabled?: boolean
  labels?: Partial<ModelComboboxLabels>
}) {
  const L = { ...DEFAULT_LABELS, ...labels }
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const skipBlur = useRef(false)  // Escape: leave without committing the typed text

  const q = query.trim()
  const options = useMemo(() => {
    const ql = q.toLowerCase()
    const out: { id: string; note?: string }[] = models
      .filter(m => !ql || m.toLowerCase().includes(ql))
      .slice(0, MAX_SHOWN)
      .map(id => ({ id }))
    if (q && !models.includes(q) && extra.includes(q)) out.unshift({ id: q, note: L.noteEndpoint })
    if (q && !models.includes(q) && !extra.includes(q)) out.push({ id: q, note: L.noteExact })
    return out
  }, [q, models, extra, L.noteEndpoint, L.noteExact])

  const commit = (id: string) => {
    if (id && id !== value) onChange(id)
    setOpen(false)
    setQuery('')
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(a => Math.min(a + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (options[active]) commit(options[active].id); else if (q) commit(q) }
    else if (e.key === 'Escape') { skipBlur.current = true; setOpen(false); setQuery(''); inputRef.current?.blur() }
  }

  const status = !value ? null
    : models.includes(value) ? null
    : extra.includes(value) ? L.statusOutside
    : models.length || extra.length ? L.statusNotOffered
    : null

  return (
    <div className="relative">
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3"><SearchIcon /></span>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          spellCheck={false}
          autoComplete="off"
          value={open ? query : value}
          placeholder={value || placeholder || L.placeholder}
          disabled={disabled}
          onFocus={() => { setOpen(true); setQuery(''); setActive(0) }}
          onChange={e => { setQuery(e.target.value); setOpen(true); setActive(0) }}
          onBlur={() => {
            if (q && !skipBlur.current) commit(q)
            else { setOpen(false); setQuery('') }
            skipBlur.current = false
          }}
          onKeyDown={onKeyDown}
          className="w-full border border-gray-300 rounded-lg pl-9 pr-3 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none font-mono disabled:bg-gray-100 disabled:text-gray-500"
        />
      </div>
      {open && options.length > 0 && (
        <ul role="listbox" className="absolute z-20 mt-1 w-full max-h-64 overflow-auto bg-white border border-gray-200 rounded-lg shadow-md py-1 text-sm">
          {options.map((o, i) => (
            <li
              key={`${o.id}-${o.note ?? ''}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={e => { e.preventDefault(); commit(o.id) }}
              onMouseEnter={() => setActive(i)}
              className={`px-3 py-1.5 cursor-pointer flex items-center justify-between gap-2 ${i === active ? 'bg-gray-100' : ''} ${o.id === value ? 'font-medium text-uni-blue' : 'text-gray-700'}`}
            >
              <span className="truncate">{o.id}</span>
              {o.note && <span className="shrink-0 text-xs text-gray-400">{o.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {status && !disabled && <p className="text-xs text-amber-600 mt-1">{status}</p>}
      {!models.length && !extra.length && emptyHint && <p className="text-xs text-gray-400 mt-1">{emptyHint}</p>}
    </div>
  )
}
