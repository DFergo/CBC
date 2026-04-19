// Admin API client. Sprint 3 expands with companies, prompts, rag, knowledge, llm, smtp.
const API_BASE = ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('cbc_admin_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// --- Auth ---

export async function getAdminStatus(): Promise<{ setup_complete: boolean }> {
  return request('/admin/status')
}

export async function setupAdmin(password: string, confirmPassword: string): Promise<{ message: string }> {
  return request('/admin/setup', {
    method: 'POST',
    body: JSON.stringify({ password, confirm_password: confirmPassword }),
  })
}

export async function loginAdmin(password: string, rememberMe: boolean): Promise<{ token: string; expires_in: number }> {
  return request('/admin/login', {
    method: 'POST',
    body: JSON.stringify({ password, remember_me: rememberMe }),
  })
}

export async function verifyToken(): Promise<{ valid: boolean }> {
  return request('/admin/verify')
}

// --- Companies ---

export interface Company {
  slug: string
  display_name: string
  enabled: boolean
  sort_order: number
  is_compare_all: boolean
  prompt_mode: string
  rag_mode: string
  country_tags: string[]
  metadata: Record<string, unknown>
}

export async function listCompanies(frontendId: string): Promise<{ companies: Company[] }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies`)
}

export async function createCompany(frontendId: string, data: Partial<Company> & { slug: string; display_name: string }): Promise<{ company: Company }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateCompany(frontendId: string, slug: string, patch: Partial<Company>): Promise<{ company: Company }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies/${encodeURIComponent(slug)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export async function deleteCompany(frontendId: string, slug: string): Promise<{ status: string }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  })
}

// --- Prompts (tier-aware: omit frontendId/companySlug for global) ---

export interface PromptFile {
  name: string
  size: number
  modified: number
}

function promptsPath(frontendId?: string, companySlug?: string, suffix = ''): string {
  if (frontendId && companySlug) {
    return `/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies/${encodeURIComponent(companySlug)}/prompts${suffix}`
  }
  if (frontendId) {
    return `/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/prompts${suffix}`
  }
  return `/admin/api/v1/prompts${suffix}`
}

export async function listPrompts(frontendId?: string, companySlug?: string): Promise<{ prompts: PromptFile[] }> {
  return request(promptsPath(frontendId, companySlug))
}

export async function readPrompt(name: string, frontendId?: string, companySlug?: string): Promise<{ name: string; content: string }> {
  return request(promptsPath(frontendId, companySlug, `/${encodeURIComponent(name)}`))
}

export async function savePrompt(name: string, content: string, frontendId?: string, companySlug?: string): Promise<PromptFile> {
  return request(promptsPath(frontendId, companySlug, `/${encodeURIComponent(name)}`), {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function deletePrompt(name: string, frontendId?: string, companySlug?: string): Promise<{ status: string }> {
  return request(promptsPath(frontendId, companySlug, `/${encodeURIComponent(name)}`), { method: 'DELETE' })
}

// --- RAG (tier-aware via query params) ---

export interface RAGDocument {
  name: string
  size: number
  modified: number
}

export interface RAGStats {
  document_count: number
  total_size_bytes: number
  note: string
}

function ragQuery(frontendId?: string, companySlug?: string): string {
  const params = new URLSearchParams()
  if (frontendId) params.set('frontend_id', frontendId)
  if (companySlug) params.set('company_slug', companySlug)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export async function listRAG(frontendId?: string, companySlug?: string): Promise<{ documents: RAGDocument[] }> {
  return request(`/admin/api/v1/rag/documents${ragQuery(frontendId, companySlug)}`)
}

export async function uploadRAG(file: File, frontendId?: string, companySlug?: string): Promise<{ document: RAGDocument }> {
  const token = localStorage.getItem('cbc_admin_token')
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`/admin/api/v1/rag/upload${ragQuery(frontendId, companySlug)}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function deleteRAG(name: string, frontendId?: string, companySlug?: string): Promise<{ status: string }> {
  return request(`/admin/api/v1/rag/documents/${encodeURIComponent(name)}${ragQuery(frontendId, companySlug)}`, { method: 'DELETE' })
}

export async function getRAGStats(frontendId?: string, companySlug?: string): Promise<RAGStats> {
  return request(`/admin/api/v1/rag/stats${ragQuery(frontendId, companySlug)}`)
}

export async function reindexRAG(frontendId?: string, companySlug?: string): Promise<RAGStats> {
  return request(`/admin/api/v1/rag/reindex${ragQuery(frontendId, companySlug)}`, { method: 'POST' })
}

// --- Knowledge ---

export interface GlossaryTerm {
  term: string
  definition: string
  translations: Record<string, string>
}

export interface Organization {
  name: string
  type: string
  country: string
  description: string
}

export async function getGlossary(): Promise<{ terms: GlossaryTerm[] }> {
  return request('/admin/api/v1/knowledge/glossary')
}

export async function saveGlossary(terms: GlossaryTerm[]): Promise<{ terms: GlossaryTerm[] }> {
  return request('/admin/api/v1/knowledge/glossary', { method: 'PUT', body: JSON.stringify({ terms }) })
}

export async function getOrganizations(): Promise<{ organizations: Organization[] }> {
  return request('/admin/api/v1/knowledge/organizations')
}

export async function saveOrganizations(organizations: Organization[]): Promise<{ organizations: Organization[] }> {
  return request('/admin/api/v1/knowledge/organizations', { method: 'PUT', body: JSON.stringify({ organizations }) })
}

// --- LLM ---

export type ProviderType = 'lm_studio' | 'ollama' | 'api'
export type ApiFlavor = 'anthropic' | 'openai' | 'openai_compatible'
export type SlotName = 'inference' | 'compressor' | 'summariser'

export interface SlotConfig {
  provider: ProviderType
  model: string
  temperature: number
  max_tokens: number
  num_ctx: number
  endpoint: string
  api_flavor?: ApiFlavor | null
  api_endpoint?: string | null
  api_key_env?: string | null
}

export interface CompressionSettings {
  enabled: boolean
  first_threshold: number
  step_size: number
}

export interface RoutingToggles {
  document_summary_slot: SlotName
  user_summary_slot: SlotName
}

export interface LLMConfig {
  inference: SlotConfig
  compressor: SlotConfig
  summariser: SlotConfig
  compression: CompressionSettings
  routing: RoutingToggles
}

export interface SlotHealth {
  provider: ProviderType
  ok: boolean
  status_code: number
  error: string | null
  models: string[]
}

export interface LLMHealth {
  inference: SlotHealth
  compressor: SlotHealth
  summariser: SlotHealth
}

export interface ProviderInfo {
  endpoint: string
  status: 'online' | 'offline'
  models: string[]
  error: string | null
}

export interface ProvidersStatus {
  lm_studio: ProviderInfo
  ollama: ProviderInfo
}

export async function getLLMConfig(): Promise<LLMConfig> {
  return request('/admin/api/v1/llm')
}

export async function saveLLMConfig(cfg: LLMConfig): Promise<LLMConfig> {
  return request('/admin/api/v1/llm', { method: 'PUT', body: JSON.stringify(cfg) })
}

export async function getLLMDefaults(): Promise<{ lm_studio: string; ollama: string }> {
  return request('/admin/api/v1/llm/defaults')
}

export async function getProvidersStatus(): Promise<ProvidersStatus> {
  return request('/admin/api/v1/llm/providers')
}

export async function checkLLMHealth(): Promise<LLMHealth> {
  return request('/admin/api/v1/llm/health', { method: 'POST' })
}

// --- SMTP ---

export interface SMTPConfig {
  host: string
  port: number
  username: string
  password: string  // '***' placeholder from GET; send '***' back unchanged to keep existing
  use_tls: boolean
  from_address: string
  admin_notification_emails: string[]
  send_summary_to_user: boolean
  send_summary_to_admin: boolean
  send_new_document_to_admin: boolean
}

export async function getSMTPConfig(): Promise<SMTPConfig> {
  return request('/admin/api/v1/smtp')
}

export async function saveSMTPConfig(cfg: SMTPConfig): Promise<SMTPConfig> {
  return request('/admin/api/v1/smtp', { method: 'PUT', body: JSON.stringify(cfg) })
}

export async function testSMTP(): Promise<{ ok: boolean; error?: string }> {
  return request('/admin/api/v1/smtp/test', { method: 'POST' })
}

// --- Per-frontend notification override ---

export interface NotificationOverride {
  admin_emails_mode: 'replace' | 'append'
  admin_notification_emails: string[]
}

export interface NotificationOverrideResponse {
  frontend_id: string
  override: NotificationOverride | null
  resolved_admin_emails: string[]
}

export async function getFrontendNotificationOverride(frontendId: string): Promise<NotificationOverrideResponse> {
  return request(`/admin/api/v1/smtp/frontend/${encodeURIComponent(frontendId)}`)
}

export async function saveFrontendNotificationOverride(frontendId: string, override: NotificationOverride): Promise<NotificationOverrideResponse> {
  return request(`/admin/api/v1/smtp/frontend/${encodeURIComponent(frontendId)}`, {
    method: 'PUT',
    body: JSON.stringify(override),
  })
}

export async function deleteFrontendNotificationOverride(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/smtp/frontend/${encodeURIComponent(frontendId)}`, { method: 'DELETE' })
}

// --- Frontends registry (Sprint 4A) ---

export interface FrontendInfo {
  frontend_id: string
  url: string
  name: string
  enabled: boolean
  status: 'online' | 'offline' | 'unknown'
  last_seen: string | null
  created_at: string | null
  metadata: Record<string, unknown>
}

export async function listFrontends(): Promise<{ frontends: FrontendInfo[] }> {
  return request('/admin/api/v1/frontends')
}

export async function registerFrontend(data: { frontend_id: string; url: string; name?: string }): Promise<{ frontend: FrontendInfo }> {
  return request('/admin/api/v1/frontends', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateFrontend(frontendId: string, patch: { url?: string; name?: string; enabled?: boolean; metadata?: Record<string, unknown> }): Promise<{ frontend: FrontendInfo }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export async function deleteFrontend(frontendId: string): Promise<{ status: string }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}`, { method: 'DELETE' })
}

// --- Global branding defaults ---

export async function getBrandingDefaults(): Promise<{ defaults: FrontendBranding | null }> {
  return request('/admin/api/v1/branding/defaults')
}

export async function saveBrandingDefaults(branding: FrontendBranding): Promise<{ defaults: FrontendBranding; pushed_to_frontends: number }> {
  return request('/admin/api/v1/branding/defaults', { method: 'PUT', body: JSON.stringify(branding) })
}

export async function deleteBrandingDefaults(): Promise<{ removed: boolean; pushed_to_frontends: number }> {
  return request('/admin/api/v1/branding/defaults', { method: 'DELETE' })
}

// --- Per-frontend branding ---

export interface FrontendBranding {
  app_title: string
  org_name: string
  logo_url: string
  primary_color: string
  secondary_color: string
  disclaimer_text: string
  instructions_text: string
}

export async function getFrontendBranding(frontendId: string): Promise<{ frontend_id: string; branding: FrontendBranding | null }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/branding`)
}

export async function saveFrontendBranding(frontendId: string, branding: FrontendBranding): Promise<{ frontend_id: string; branding: FrontendBranding }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/branding`, {
    method: 'PUT',
    body: JSON.stringify(branding),
  })
}

export async function deleteFrontendBranding(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/branding`, { method: 'DELETE' })
}

// --- Per-frontend session settings ---

export interface FrontendSessionSettings {
  auth_required: boolean | null
  session_resume_hours: number | null
  auto_close_hours: number | null
  auto_destroy_hours: number | null
  disclaimer_enabled: boolean | null
  instructions_enabled: boolean | null
  compare_all_enabled: boolean | null
  rag_standalone: boolean | null
}

export async function getFrontendSessionSettings(frontendId: string): Promise<{ frontend_id: string; settings: FrontendSessionSettings | null }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/session-settings`)
}

export async function saveFrontendSessionSettings(frontendId: string, settings: FrontendSessionSettings): Promise<{ frontend_id: string; settings: FrontendSessionSettings }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/session-settings`, {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

export async function deleteFrontendSessionSettings(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/session-settings`, { method: 'DELETE' })
}

// --- Per-frontend organizations override ---

export interface FrontendOrgsOverride {
  mode: 'inherit' | 'own' | 'combine'
  organizations: Organization[]
}

export async function getFrontendOrgsOverride(frontendId: string): Promise<{ frontend_id: string; override: FrontendOrgsOverride | null }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/orgs`)
}

export async function saveFrontendOrgsOverride(frontendId: string, override: FrontendOrgsOverride): Promise<{ frontend_id: string; override: FrontendOrgsOverride }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/orgs`, {
    method: 'PUT',
    body: JSON.stringify(override),
  })
}

export async function deleteFrontendOrgsOverride(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/orgs`, { method: 'DELETE' })
}

// --- Per-frontend LLM override (D2=B: single file = full override; no file = inherit global) ---

export async function getFrontendLLMOverride(frontendId: string): Promise<{ frontend_id: string; override: LLMConfig | null }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/llm`)
}

export async function saveFrontendLLMOverride(frontendId: string, cfg: LLMConfig): Promise<{ frontend_id: string; override: LLMConfig }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/llm`, {
    method: 'PUT',
    body: JSON.stringify(cfg),
  })
}

export async function deleteFrontendLLMOverride(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/llm`, { method: 'DELETE' })
}

// --- Resolver preview ---

export interface PromptResolution {
  name: string
  tier: 'global' | 'frontend' | 'company' | 'none'
  path: string | null
  content: string | null
  found: boolean
}

export interface RAGResolutionEntry {
  tier: 'global' | 'frontend' | 'company'
  scope_key: string
  path: string
  doc_count: number
}

export interface RAGResolutionResponse {
  paths: RAGResolutionEntry[]
  frontend_standalone: boolean
  total_docs: number
}

export interface OrgsResolutionResponse {
  mode: 'inherit' | 'own' | 'combine'
  organizations: Organization[]
  count: number
}

export async function previewPromptResolution(name: string, frontendId?: string, companySlug?: string, compareAll = false): Promise<PromptResolution> {
  const params = new URLSearchParams()
  if (frontendId) params.set('frontend_id', frontendId)
  if (companySlug) params.set('company_slug', companySlug)
  if (compareAll) params.set('compare_all', 'true')
  const qs = params.toString()
  return request(`/admin/api/v1/resolvers/prompt/${encodeURIComponent(name)}${qs ? '?' + qs : ''}`)
}

export async function previewRAGResolution(frontendId: string, companySlug?: string, opts: { compareAll?: boolean; comparisonScope?: string; userCountry?: string } = {}): Promise<RAGResolutionResponse> {
  const params = new URLSearchParams()
  params.set('frontend_id', frontendId)
  if (companySlug) params.set('company_slug', companySlug)
  if (opts.compareAll) params.set('compare_all', 'true')
  if (opts.comparisonScope) params.set('comparison_scope', opts.comparisonScope)
  if (opts.userCountry) params.set('user_country', opts.userCountry)
  return request(`/admin/api/v1/resolvers/rag?${params.toString()}`)
}

export async function previewOrgsResolution(frontendId?: string): Promise<OrgsResolutionResponse> {
  const qs = frontendId ? `?frontend_id=${encodeURIComponent(frontendId)}` : ''
  return request(`/admin/api/v1/resolvers/orgs${qs}`)
}

// --- Contacts (authorized users directory) ---

export interface Contact {
  email: string
  first_name: string
  last_name: string
  organization: string
  country: string
  sector: string
  registered_by: string
}

export interface FrontendContactsOverride {
  mode: 'replace' | 'append'
  contacts: Contact[]
}

export interface ContactsStore {
  global: Contact[]
  per_frontend: Record<string, FrontendContactsOverride>
}

export async function getContacts(): Promise<ContactsStore> {
  return request('/admin/api/v1/contacts')
}

export async function updateGlobalContacts(contacts: Contact[]): Promise<{ global: Contact[] }> {
  return request('/admin/api/v1/contacts/global', {
    method: 'PUT',
    body: JSON.stringify({ contacts }),
  })
}

export async function updateFrontendContacts(frontendId: string, mode: 'replace' | 'append', contacts: Contact[]): Promise<{ frontend_id: string; override: FrontendContactsOverride }> {
  return request(`/admin/api/v1/contacts/frontend/${encodeURIComponent(frontendId)}`, {
    method: 'PUT',
    body: JSON.stringify({ mode, contacts }),
  })
}

export async function deleteFrontendContacts(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/api/v1/contacts/frontend/${encodeURIComponent(frontendId)}`, { method: 'DELETE' })
}

export async function copyContactsFromFrontend(frontendId: string, srcFrontendId: string, mode: 'replace' | 'append' = 'replace'): Promise<{ frontend_id: string; override: FrontendContactsOverride }> {
  return request(`/admin/api/v1/contacts/frontend/${encodeURIComponent(frontendId)}/copy-from/${encodeURIComponent(srcFrontendId)}?mode=${mode}`, {
    method: 'POST',
  })
}

export function exportContactsURL(scope: string): string {
  return `/admin/api/v1/contacts/export?scope=${encodeURIComponent(scope)}`
}

export async function importContacts(file: File, scope: string): Promise<{ added: number; updated: number; ignored_malformed: number; scope: string }> {
  const token = localStorage.getItem('cbc_admin_token')
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`/admin/api/v1/contacts/import?scope=${encodeURIComponent(scope)}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Import failed' }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}
