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
  disclaimer_what_heading: 'Collective Bargaining Copilot — Research tool for union negotiators',
  disclaimer_what_body:
    'The Collective Bargaining Copilot (CBC) supports trade union representatives in preparing for and conducting collective bargaining.\n\nIts primary function is to let you compare collective bargaining agreements across companies, countries, and sectors, cross-check what an employer has signed elsewhere against what they offer in your jurisdiction, and surface relevant clauses, benchmarks, and precedents to strengthen your bargaining position.\n\nThe tool draws on the collective bargaining agreements, company policies, and reference documents loaded into this deployment by your union. You can add your own CBA or company policy during a session to bring it into the conversation.\n\nCBC is an AI system. It can make mistakes — paraphrase clauses inaccurately, miss context, or miscite an article. It does not replace your union\'s legal counsel, your bargaining team\'s judgement, or the original text of an agreement. Always verify critical clauses against the source document before you take a position at the table.',
  disclaimer_data_heading: 'How your data is handled',
  disclaimer_data_body:
    'Your data is processed and stored exclusively by UNI Global Union on its own infrastructure. Conversations, uploaded documents, and survey responses are not sent to external cloud services or third-party AI providers, except where the deployment administrator has explicitly configured a remote LLM API — in which case the chat content is sent to that provider for inference only.\n\nThe purpose of collecting this information is to help you prepare for negotiations and to let UNI Global Union — together with the affiliated union you work with — build collective intelligence on bargaining outcomes across the sector.\n\nYour identity and your union\'s strategic information are kept confidential within UNI Global Union and will not be disclosed to employers or third parties without your prior explicit consent.\n\nYou may use this tool without providing personal details. Your name, position, and contact email are optional and used only to follow up with the conversation summary if you request it. Sessions can be set by the administrator to auto-destroy after a privacy period — when enabled, conversations, uploads, and any session-derived RAG content are deleted at expiry.',
  disclaimer_legal_heading: 'Disclaimer',
  disclaimer_legal_body:
    'By continuing, you acknowledge that:\n\n- This tool is provided by UNI Global Union for research and bargaining-preparation purposes only. It does not constitute legal advice and is not a substitute for your union\'s legal team.\n- The AI system may produce inaccurate, incomplete, or out-of-date information. UNI Global Union is not liable for decisions taken on the basis of AI-generated content. Always verify cited clauses against the original collective bargaining agreement.\n- Your data is processed in accordance with the EU General Data Protection Regulation (GDPR). You have the right to access, rectify, or request deletion of any personal data you provide by contacting UNI Global Union at [DATA_PROTECTION_EMAIL].\n- Session data is retained for the period configured by your deployment administrator and may be deleted earlier on request.\n- You may withdraw your consent to data processing at any time. Withdrawal does not affect the lawfulness of processing carried out before withdrawal.',
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
    'You are about to start a research session with the Collective Bargaining Copilot. The next steps are short and the chat does the rest.\n\nWhat happens next:\n- You will choose a company to focus on, or "Compare All" for a cross-company view across the sector.\n- You will answer a brief survey: country, region, and what you want to know going into the session. Name, organisation, position, and email are optional and used only to send you the conversation summary.\n- The chat will open. Ask in your own words: clauses to compare, benchmarks to surface, gaps between agreements, what an employer has signed elsewhere, how a proposal stacks up against the sector.\n\nWhat the tool can do:\n- Compare collective bargaining agreements across companies, countries, and sectors loaded into this deployment.\n- Cross-check company policies against signed CBAs and against the company\'s own public commitments.\n- Surface relevant clauses, precedents, and benchmarks to support your bargaining position.\n- Accept your own document during the conversation — upload a draft CBA, an employer proposal, or a company policy and it will be brought into the chat context for that session.\n\nWhat the tool cannot do:\n- It does not access external websites, live legal databases, or the internet during the conversation. It works from the documents loaded into this deployment plus anything you upload.\n- It is not a legal advisor and does not replace your union\'s legal team or your bargaining committee.\n- It does not negotiate on your behalf or send anything to the employer.\n\nWhen you are done:\n- Close the session from the chat. A summary of the conversation is generated and, if you provided your email in the survey, emailed to you.\n- If your deployment is configured for privacy auto-destruction, the conversation and any uploads are deleted at expiry.\n\nVerify any clause CBC quotes against the original agreement before you take a position at the table.',
  instructions_continue: 'Continue',
  instructions_no_reload: 'Important: do not reload the page during the session — you will lose the conversation.',

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
