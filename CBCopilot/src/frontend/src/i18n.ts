import type { LangCode } from './types'

interface LangInfo {
  code: LangCode
  name: string
  nativeName: string
}

// Sprint 2: EN only. Sprint 8 adds ES, FR, DE, PT (MILESTONES §Sprint 8).
export const LANGUAGES: LangInfo[] = [
  { code: 'en', name: 'English', nativeName: 'English' },
]

type TranslationKeys =
  | 'footer_disclaimer' | 'nav_back' | 'loading'
  | 'language_select_title' | 'language_select_subtitle'
  | 'disclaimer_title' | 'disclaimer_what_heading' | 'disclaimer_what_body'
  | 'disclaimer_data_heading' | 'disclaimer_data_body'
  | 'disclaimer_legal_heading' | 'disclaimer_legal_body'
  | 'disclaimer_accept'
  | 'session_title' | 'session_new' | 'session_token_label' | 'session_token_save' | 'session_continue'
  | 'auth_title' | 'auth_email_label' | 'auth_send_code'
  | 'auth_code_label' | 'auth_code_sent_to' | 'auth_placeholder'
  | 'auth_verify' | 'auth_invalid_code' | 'auth_max_retries' | 'auth_contact_admin'
  | 'auth_dev_banner' | 'auth_dev_banner_note'
  | 'instructions_title' | 'instructions_body' | 'instructions_continue' | 'instructions_no_reload'
  | 'company_select_title' | 'company_select_subtitle' | 'company_compare_all_label'
  | 'survey_title' | 'survey_company_label'
  | 'survey_country' | 'survey_region' | 'survey_name' | 'survey_organization'
  | 'survey_position' | 'survey_email' | 'survey_initial_query'
  | 'survey_upload_label' | 'survey_upload_hint'
  | 'survey_comparison_scope' | 'scope_national' | 'scope_regional' | 'scope_global'
  | 'survey_submit'
  | 'placeholder_title' | 'placeholder_body'

type Translations = Partial<Record<TranslationKeys, string>>

const EN: Translations = {
  loading: 'Loading…',
  nav_back: 'Back',
  footer_disclaimer: 'CBC is a research assistant, not a legal advisor. Answers are grounded in uploaded documents but may be incomplete.',

  language_select_title: 'Select your language',
  language_select_subtitle: 'Choose your preferred language to continue',

  disclaimer_title: 'Before you start',
  disclaimer_what_heading: 'What is this tool?',
  disclaimer_what_body:
    'The Collective Bargaining Copilot (CBC) helps trade union representatives compare collective bargaining agreements across companies, countries, and sectors. It is a research tool, not a legal advisor.',
  disclaimer_data_heading: 'How your data is handled',
  disclaimer_data_body:
    'Your session data is stored on the backend for the duration configured by your deployment administrator. Sessions can be set to auto-destroy after a privacy period. No data is shared with third parties.',
  disclaimer_legal_heading: 'Disclaimer',
  disclaimer_legal_body:
    'CBC does not provide legal advice. Answers are grounded in the collective bargaining agreements and company policies uploaded to this deployment. Verify critical information against original sources before negotiation.',
  disclaimer_accept: 'I understand — continue',

  session_title: 'Your session',
  session_new: 'Start a new session',
  session_token_label: 'Your session token',
  session_token_save: 'Save this token if you want to resume this session later.',
  session_continue: 'Continue',

  auth_title: 'Verify your email',
  auth_email_label: 'Email address',
  auth_send_code: 'Send verification code',
  auth_code_label: 'Verification code',
  auth_code_sent_to: 'We sent a 6-digit code to',
  auth_placeholder: '000000',
  auth_verify: 'Verify',
  auth_invalid_code: 'Invalid code. Please try again.',
  auth_max_retries: 'Too many attempts. Please contact your administrator.',
  auth_contact_admin: 'Need help? Contact your deployment administrator.',
  auth_dev_banner: 'Dev mode — real SMTP arrives in Sprint 7',
  auth_dev_banner_note: 'Your code is shown here for testing. In production it is emailed to you.',

  instructions_title: 'How to use CBC',
  instructions_body:
    'On the next page you will choose a company (or "Compare All" for a cross-company view) and fill a short survey about your negotiation context. Then you will chat with the assistant, which answers using the collective bargaining agreements loaded for this deployment. You can upload your own CBA or company policy during the chat.',
  instructions_continue: 'Continue',
  instructions_no_reload: 'Please do not reload this page — doing so will reset your session.',

  company_select_title: 'Choose a company',
  company_select_subtitle: 'Select a company to focus on, or "Compare All" for a cross-company view.',
  company_compare_all_label: 'Compare All',

  survey_title: 'Survey',
  survey_company_label: 'Selected',
  survey_country: 'Country',
  survey_region: 'Region',
  survey_name: 'Name',
  survey_organization: 'Organization / union',
  survey_position: 'Position',
  survey_email: 'Email',
  survey_initial_query: 'What do you want to know?',
  survey_upload_label: 'Upload a document (optional)',
  survey_upload_hint: 'CBA, company policy, or other relevant document. Upload wiring lands in Sprint 5 — the field is visible but submit does not send the file yet.',
  survey_comparison_scope: 'Comparison scope',
  scope_national: 'National (my country only)',
  scope_regional: 'Regional (my region)',
  scope_global: 'Global (all countries)',
  survey_submit: 'Start chat',

  placeholder_title: 'Survey submitted',
  placeholder_body: 'Chat interface arrives in Sprint 6. Your survey data is queued in the sidecar and visible in the logs.',
}

// Sprint 2: non-EN languages silently fall back to EN.
// Sprint 8 will replace these with real translations.
const DICTIONARIES: Record<LangCode, Translations> = {
  en: EN,
  es: {},
  fr: {},
  de: {},
  pt: {},
}

export function t(key: TranslationKeys, lang: LangCode): string {
  return DICTIONARIES[lang]?.[key] ?? EN[key] ?? key
}
