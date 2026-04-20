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
  is_compare_all: boolean
  combine_frontend_rag: boolean
  combine_global_rag: boolean
  country_tags: string[]
  metadata: Record<string, unknown>
}

export async function listCompanies(frontendId: string): Promise<{ companies: Company[] }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/companies`)
}

export async function createCompany(frontendId: string, data: Partial<Company> & { display_name: string }): Promise<{ company: Company }> {
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
  indexed: boolean
  node_count: number
  note: string
}

export interface DocMetadata {
  country?: string
  language?: string
  document_type?: string
}

export type DocMetadataMap = Record<string, DocMetadata>

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

export async function getDocMetadata(frontendId?: string, companySlug?: string): Promise<{ scope_key: string; metadata: DocMetadataMap }> {
  return request(`/admin/api/v1/rag/metadata${ragQuery(frontendId, companySlug)}`)
}

export async function saveDocMetadata(filename: string, patch: DocMetadata, frontendId?: string, companySlug?: string): Promise<{ scope_key: string; filename: string; metadata: DocMetadata }> {
  return request(`/admin/api/v1/rag/metadata/${encodeURIComponent(filename)}${ragQuery(frontendId, companySlug)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
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

export async function registerFrontend(data: { url: string; name: string }): Promise<{ frontend: FrontendInfo }> {
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
  auth_required: boolean
  session_resume_hours: number
  auto_close_hours: number
  auto_destroy_hours: number
  disclaimer_enabled: boolean
  instructions_enabled: boolean
  compare_all_enabled: boolean
}

export const SESSION_DEFAULTS: FrontendSessionSettings = {
  auth_required: true,
  session_resume_hours: 48,
  auto_close_hours: 72,
  auto_destroy_hours: 0,
  disclaimer_enabled: true,
  instructions_enabled: true,
  compare_all_enabled: true,
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

// --- Per-frontend RAG settings ---

export interface FrontendRAGSettings {
  combine_global_rag: boolean
}

export async function getFrontendRAGSettings(frontendId: string): Promise<{ frontend_id: string; settings: FrontendRAGSettings }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/rag-settings`)
}

export async function saveFrontendRAGSettings(frontendId: string, settings: FrontendRAGSettings): Promise<{ frontend_id: string; settings: FrontendRAGSettings }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/rag-settings`, {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

export async function deleteFrontendRAGSettings(frontendId: string): Promise<{ frontend_id: string; removed: boolean; settings: FrontendRAGSettings }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/rag-settings`, { method: 'DELETE' })
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

// Per-slot opt-in: each slot is a SlotConfig override OR null (inherit global).
// compression and routing always inherit from global at the frontend tier.
export interface LLMOverride {
  inference: SlotConfig | null
  compressor: SlotConfig | null
  summariser: SlotConfig | null
}

export const EMPTY_LLM_OVERRIDE: LLMOverride = { inference: null, compressor: null, summariser: null }

export async function getFrontendLLMOverride(frontendId: string): Promise<{ frontend_id: string; override: LLMOverride }> {
  return request(`/admin/api/v1/frontends/${encodeURIComponent(frontendId)}/llm`)
}

export async function saveFrontendLLMOverride(frontendId: string, cfg: LLMOverride): Promise<{ frontend_id: string; override: LLMOverride }> {
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

// --- Admin sessions (Sprint 7) ---

export interface SessionSummary {
  token: string
  frontend_id: string
  frontend_name: string
  company_slug: string
  company_display_name: string
  is_compare_all: boolean
  country: string
  message_count: number
  status: string
  flagged: boolean
  guardrail_violations: number
  created_at: string | null
  last_activity: string | null
  completed_at: string | null
}

export interface SessionMessage {
  role: string
  content: string
  timestamp: string | null
  attachments: string[]
}

export interface SessionDetail extends SessionSummary {
  survey: Record<string, unknown>
  language: string
  messages: SessionMessage[]
  uploads: { name: string; size: number }[]
  summary: string | null
}

export async function listSessions(): Promise<{ sessions: SessionSummary[] }> {
  return request('/admin/api/v1/sessions')
}

export async function getAdminSession(token: string): Promise<SessionDetail> {
  return request(`/admin/api/v1/sessions/${encodeURIComponent(token)}`)
}

export async function toggleSessionFlag(token: string): Promise<{ token: string; flagged: boolean }> {
  return request(`/admin/api/v1/sessions/${encodeURIComponent(token)}/flag`, { method: 'POST' })
}

export async function destroySession(token: string): Promise<{ token: string; removed: boolean }> {
  return request(`/admin/api/v1/sessions/${encodeURIComponent(token)}`, { method: 'DELETE' })
}

export async function fetchSessionUploadBlob(token: string, filename: string): Promise<Blob> {
  const authToken = localStorage.getItem('cbc_admin_token')
  const res = await fetch(`/admin/api/v1/sessions/${encodeURIComponent(token)}/uploads/${encodeURIComponent(filename)}`, {
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Download failed' }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.blob()
}

export async function downloadSessionUpload(token: string, filename: string): Promise<void> {
  const blob = await fetchSessionUploadBlob(token, filename)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke after a beat so Chrome has time to start the download
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function copySessionUploadText(token: string, filename: string): Promise<void> {
  const blob = await fetchSessionUploadBlob(token, filename)
  const text = await blob.text()
  await navigator.clipboard.writeText(text)
}
