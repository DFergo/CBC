export type Phase =
  | 'loading'
  | 'language'
  | 'disclaimer'
  | 'session'
  | 'auth'
  | 'instructions'
  | 'company_select'
  | 'survey'
  | 'placeholder'

export type LangCode = 'en' | 'es' | 'fr' | 'de' | 'pt'

export type ComparisonScope = 'national' | 'regional' | 'global'

export interface BrandingConfig {
  app_title?: string
  logo_url?: string
  primary_color?: string
  secondary_color?: string
}

export interface DeploymentConfig {
  role: string
  frontend_id: string
  auth_required: boolean
  disclaimer_enabled: boolean
  instructions_enabled: boolean
  compare_all_enabled: boolean
  session_resume_hours: number
  branding?: BrandingConfig
}

export interface Company {
  slug: string
  display_name: string
  enabled: boolean
  sort_order: number
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
