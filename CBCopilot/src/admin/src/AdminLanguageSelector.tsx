// Sprint 12 — language picker in the admin header. Plain native <select>
// so it works everywhere (keyboard, screen reader, mobile) without dragging
// in a popover library. The native dropdown feels a touch out of place
// against the dark header but the accessibility / small-size win is worth
// more than the pure aesthetic.
import { ADMIN_LANGUAGES, persistAdminLang, useAdminLang, useT } from './i18n'
import type { AdminLangCode } from './i18n'

export default function AdminLanguageSelector() {
  const { lang, setLang } = useAdminLang()
  const { t } = useT()

  const onChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const code = e.target.value as AdminLangCode
    persistAdminLang(code)
    setLang(code)
  }

  return (
    <label className="flex items-center gap-2 text-xs text-white/70">
      <span className="hidden sm:inline">{t('header_language_label')}</span>
      <select
        value={lang}
        onChange={onChange}
        className="bg-white/10 hover:bg-white/20 text-white rounded-lg px-2 py-1 text-xs border-0 focus:outline-none focus:ring-2 focus:ring-white/30 [&>option]:text-gray-800"
      >
        {ADMIN_LANGUAGES.map(l => (
          <option key={l.code} value={l.code}>
            {l.nativeName}
          </option>
        ))}
      </select>
    </label>
  )
}
