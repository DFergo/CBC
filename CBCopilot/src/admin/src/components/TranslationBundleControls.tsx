// Reusable controls for the disclaimer_text / instructions_text translation
// workflow (Sprint 8 §7, option C): admin picks the source language the free
// text is written in, downloads a JSON bundle to hand to translators, or
// uploads a filled-in bundle back. Auto-translate kicks the backend LLM job
// that fills missing language keys from the source text — it's wired in
// Phase D, so here the button just triggers whatever handler the parent passes.
import { useRef, useState } from 'react'
import type { TranslationBundle } from '../api'

// Same 31-lang list as the frontend's i18n.ts. Kept in lock-step.
export const LANGUAGE_CHOICES: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'pt', label: 'Português' },
  { code: 'it', label: 'Italiano' },
  { code: 'nl', label: 'Nederlands' },
  { code: 'pl', label: 'Polski' },
  { code: 'sv', label: 'Svenska' },
  { code: 'hu', label: 'Magyar' },
  { code: 'el', label: 'Ελληνικά' },
  { code: 'ro', label: 'Română' },
  { code: 'hr', label: 'Hrvatski' },
  { code: 'uk', label: 'Українська' },
  { code: 'ru', label: 'Русский' },
  { code: 'tr', label: 'Türkçe' },
  { code: 'ar', label: 'العربية' },
  { code: 'ur', label: 'اردو' },
  { code: 'zh', label: '中文' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
  { code: 'vi', label: 'Tiếng Việt' },
  { code: 'th', label: 'ไทย' },
  { code: 'id', label: 'Bahasa Indonesia' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'bn', label: 'বাংলা' },
  { code: 'mr', label: 'मराठी' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'xh', label: 'isiXhosa' },
  { code: 'sw', label: 'Kiswahili' },
]
export const LANGUAGE_CODES = LANGUAGE_CHOICES.map(l => l.code)

interface Props {
  sourceLanguage: string
  onSourceLanguageChange: (code: string) => void
  disclaimerTranslations: Record<string, string>
  instructionsTranslations: Record<string, string>
  disabled: boolean // true when the tier's text blocks are empty — nothing to download/translate
  // Called when the admin clicks Download — should GET the bundle from the backend
  // and return it. The component handles the browser download.
  onDownload: () => Promise<TranslationBundle>
  // Called when the admin picks a file — the component parses JSON and hands it
  // to the parent as a TranslationBundle. Parent PUTs to the backend + reloads.
  onUpload: (bundle: TranslationBundle) => Promise<void>
  // Optional auto-translate handler. When omitted, the button is hidden.
  onAutoTranslate?: () => Promise<void>
  autoTranslateLabel?: string
  filenameStem: string // e.g. "cbc-translations-global" or "cbc-translations-packaging-eu"
}

export default function TranslationBundleControls({
  sourceLanguage,
  onSourceLanguageChange,
  disclaimerTranslations,
  instructionsTranslations,
  disabled,
  onDownload,
  onUpload,
  onAutoTranslate,
  autoTranslateLabel = 'Auto-translate missing',
  filenameStem,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState<'' | 'download' | 'upload' | 'translate'>('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  // Coverage: how many of the non-source target languages have translations.
  const targetLangs = LANGUAGE_CODES.filter(c => c !== sourceLanguage)
  const discCovered = targetLangs.filter(c => (disclaimerTranslations[c] || '').trim()).length
  const instrCovered = targetLangs.filter(c => (instructionsTranslations[c] || '').trim()).length

  const clearMsg = () => setTimeout(() => setMsg(''), 4000)

  const doDownload = async () => {
    setBusy('download')
    setErr('')
    try {
      const bundle = await onDownload()
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${filenameStem}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setMsg('Downloaded')
      clearMsg()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const doPickFile = () => {
    fileInputRef.current?.click()
  }

  const doUpload = async (file: File) => {
    setBusy('upload')
    setErr('')
    try {
      const text = await file.text()
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Error('File is not valid JSON')
      }
      if (!parsed || typeof parsed !== 'object') throw new Error('JSON must be an object')
      const p = parsed as Record<string, unknown>
      if (typeof p.source_language !== 'string') throw new Error('Missing string "source_language"')
      const bundle: TranslationBundle = {
        source_language: p.source_language,
        disclaimer_text: typeof p.disclaimer_text === 'string' ? p.disclaimer_text : '',
        instructions_text: typeof p.instructions_text === 'string' ? p.instructions_text : '',
        disclaimer_text_translations: (p.disclaimer_text_translations as Record<string, string>) || {},
        instructions_text_translations: (p.instructions_text_translations as Record<string, string>) || {},
      }
      await onUpload(bundle)
      setMsg('Uploaded + saved')
      clearMsg()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const doAutoTranslate = async () => {
    if (!onAutoTranslate) return
    setBusy('translate')
    setErr('')
    try {
      await onAutoTranslate()
      setMsg('Auto-translate triggered')
      clearMsg()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg bg-gray-50/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-semibold text-gray-600">Translations</div>
        <div className="text-[11px] text-gray-500">
          {discCovered}/{targetLangs.length} disclaimer · {instrCovered}/{targetLangs.length} instructions
          {msg && <span className="ml-2 text-green-700">{msg}</span>}
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-xs text-gray-600 flex items-center gap-2">
          Source language
          <select
            value={sourceLanguage}
            onChange={e => onSourceLanguageChange(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
          >
            {LANGUAGE_CHOICES.map(l => (
              <option key={l.code} value={l.code}>{l.label} ({l.code})</option>
            ))}
          </select>
        </label>

        <div className="flex gap-2 ml-auto">
          <button
            type="button"
            onClick={doDownload}
            disabled={disabled || !!busy}
            title={disabled ? 'Set disclaimer / instructions text first' : 'Download translations as JSON'}
            className="text-xs border border-gray-300 rounded-lg px-2.5 py-1 hover:bg-white disabled:opacity-50"
          >
            {busy === 'download' ? 'Downloading…' : 'Download JSON'}
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) void doUpload(f)
            }}
          />
          <button
            type="button"
            onClick={doPickFile}
            disabled={!!busy}
            className="text-xs border border-gray-300 rounded-lg px-2.5 py-1 hover:bg-white disabled:opacity-50"
          >
            {busy === 'upload' ? 'Uploading…' : 'Upload JSON'}
          </button>

          {onAutoTranslate && (
            <button
              type="button"
              onClick={doAutoTranslate}
              disabled={disabled || !!busy}
              title={disabled ? 'Set disclaimer / instructions text first' : 'Fill missing translations via the summariser LLM'}
              className="text-xs bg-uni-blue text-white rounded-lg px-2.5 py-1 hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'translate' ? 'Translating…' : autoTranslateLabel}
            </button>
          )}
        </div>
      </div>

      {err && <p className="text-uni-red text-xs mt-2">{err}</p>}
      <p className="text-[11px] text-gray-500 mt-2">
        Download the JSON, translate the language keys by hand or with a tool, and upload it back. The JSON
        preserves the source text so translators see what they're working from. Auto-translate uses the
        summariser LLM to fill missing languages from the source.
      </p>
    </div>
  )
}
