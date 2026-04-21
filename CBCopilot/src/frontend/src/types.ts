export type Phase =
  | 'loading'
  | 'language'
  | 'disclaimer'
  | 'session'
  | 'auth'
  | 'instructions'
  | 'company_select'
  | 'survey'
  | 'chat'

// Sprint 8: full 31-language bundle matching HRDD (Croatian `hr` included).
export type LangCode =
  | 'en' | 'zh' | 'hi' | 'es' | 'ar' | 'fr' | 'bn' | 'pt' | 'ru' | 'id'
  | 'de' | 'mr' | 'ja' | 'te' | 'tr' | 'ta' | 'vi' | 'ko' | 'ur' | 'th'
  | 'it' | 'pl' | 'nl' | 'el' | 'uk' | 'ro' | 'hr' | 'xh' | 'sw' | 'hu' | 'sv'

export type ComparisonScope = 'national' | 'regional' | 'global'

export interface BrandingConfig {
  app_title?: string
  org_name?: string
  logo_url?: string
  primary_color?: string
  secondary_color?: string
  // Free-text overrides — when non-empty, replace the i18n disclaimer/instructions text.
  disclaimer_text?: string
  instructions_text?: string
  // Sprint 8: source language the admin wrote the text above in, and
  // per-language translations. Used by DisclaimerPage / InstructionsPage to
  // pick translations[user_lang] → source → i18n default.
  source_language?: string
  disclaimer_text_translations?: Record<string, string>
  instructions_text_translations?: Record<string, string>
}

export interface DeploymentConfig {
  role: string
  frontend_id: string
  auth_required: boolean
  disclaimer_enabled: boolean
  instructions_enabled: boolean
  compare_all_enabled: boolean
  cba_sidepanel_enabled?: boolean
  session_resume_hours: number
  branding?: BrandingConfig
}

// Sprint 11 — one document that contributed chunks to an assistant response.
// Aggregated by the CBA sidepanel so the user sees what CBAs the model
// drew from and can download them.
export interface CitationSource {
  scope_key: string
  filename: string
  tier: 'global' | 'frontend' | 'company' | string
}

export interface Company {
  slug: string
  display_name: string
  enabled: boolean
  is_compare_all?: boolean
  country_tags?: string[]
}

export interface SurveyData {
  company_slug: string
  company_display_name: string
  is_compare_all: boolean
  comparison_scope?: ComparisonScope
  country: string
  region: string
  name?: string
  organization?: string
  position?: string
  email?: string
  initial_query: string
  uploaded_filename?: string
}

export interface RecoveryMessage {
  role: 'user' | 'assistant' | 'assistant_summary' | string
  content: string
  attachments?: string[]
}

export interface RecoveryData {
  token: string
  status: 'active' | 'completed' | 'destroyed' | string
  survey: SurveyData
  language: LangCode
  messages: RecoveryMessage[]
  guardrail_violations: number
}
