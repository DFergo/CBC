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

// --- Prompts (global only for Sprint 3 UI) ---

export interface PromptFile {
  name: string
  size: number
  modified: number
}

export async function listGlobalPrompts(): Promise<{ prompts: PromptFile[] }> {
  return request('/admin/api/v1/prompts')
}

export async function readGlobalPrompt(name: string): Promise<{ name: string; content: string }> {
  return request(`/admin/api/v1/prompts/${encodeURIComponent(name)}`)
}

export async function saveGlobalPrompt(name: string, content: string): Promise<PromptFile> {
  return request(`/admin/api/v1/prompts/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

// --- RAG (global for Sprint 3 UI) ---

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

export async function listGlobalRAG(): Promise<{ documents: RAGDocument[] }> {
  return request('/admin/api/v1/rag/documents')
}

export async function uploadGlobalRAG(file: File): Promise<{ document: RAGDocument }> {
  const token = localStorage.getItem('cbc_admin_token')
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/admin/api/v1/rag/upload', {
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

export async function deleteGlobalRAG(name: string): Promise<{ status: string }> {
  return request(`/admin/api/v1/rag/documents/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export async function getGlobalRAGStats(): Promise<RAGStats> {
  return request('/admin/api/v1/rag/stats')
}

export async function reindexGlobalRAG(): Promise<RAGStats> {
  return request('/admin/api/v1/rag/reindex', { method: 'POST' })
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

// --- Frontends listing (Sprint 3.5 placeholder — Sprint 4 replaces with real registry) ---

export interface FrontendInfo {
  id: string
  name: string
}

export async function listFrontends(): Promise<{ frontends: FrontendInfo[] }> {
  return request('/admin/api/v1/smtp/frontends')
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
