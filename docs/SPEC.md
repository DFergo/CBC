# Collective Bargaining Copilot (CBC) — Product Specification

**Version:** 1.0
**Last updated:** 2026-04-18
**Owner:** Daniel Fernandez / UNI Global Union G&P

---

## §1 Overview

### §1.1 What It Does

CBC is an AI-assisted tool that helps trade union representatives compare collective bargaining agreements (CBAs) across companies, countries, and sectors. Users can query CBA conditions, cross-check with company policies, and get strategic guidance for negotiations — all grounded in actual uploaded documents via RAG.

### §1.2 Who Uses It

All users are **trade unionists** (shop stewards, negotiators, union officials, researchers). There is a single user profile — no role differentiation. Technical level: low to medium. Users interact via a chat interface after a brief intake survey.

### §1.3 What It Is NOT

- Not a legal advisor — does not provide legal advice
- Not a document generator — does not produce formal reports or violation documents (unlike HRDD Helper)
- Not a replacement for human negotiation strategy — it's a research and comparison tool

### §1.4 Relationship to HRDD Helper

CBC is a **spin-off** sharing the same core architecture (pull-inverse, FastAPI + React, Docker). Key code is reused from HRDDHelper/ with adaptations. The main structural differences are: three-tier config hierarchy (Global → Frontend → Company), company selection flow, CBA-focused RAG, and simplified outputs (no UNI report, no internal case file).

---

## §2 Architecture

### §2.1 Components

```
┌──────────────────┐      poll (2s)       ┌───────────────────┐
│   Backend        │◄────────────────────►│   Frontend        │
│   (FastAPI)      │                      │   (React + Nginx  │
│   Port 8000      │   SSE stream         │    + Sidecar)     │
│                  │─────────────────────►│   Port 8091+      │
│  ┌─────────────┐ │                      └───────────────────┘
│  │ Admin SPA   │ │
│  │ (embedded)  │ │      ┌───────────────────┐
│  └─────────────┘ │      │   LLM Provider    │
│                  │◄────►│   (LM Studio /    │
│  ┌─────────────┐ │      │    Ollama)        │
│  │ RAG Engine  │ │      └───────────────────┘
│  │ (LlamaIndex)│ │
│  └─────────────┘ │
│                  │
│  ┌─────────────┐ │
│  │ File Watcher│ │  ← watches /app/data/documents, /app/data/prompts
│  │ (watchdog)  │ │     and campaign subdirectories
│  └─────────────┘ │
└──────────────────┘
```

### §2.2 Pull-Inverse Pattern

Identical to HRDD Helper. Backend polls frontend sidecars every N seconds (configurable, default 2s). Frontend sidecar queues user messages in memory (TTL 300s). Backend dequeues, processes, streams response back via SSE. See `docs/knowledge/hrdd-helper-patterns.md` for full details.

### §2.3 Multi-Frontend Support

The system supports multiple frontend deployments. Each frontend is registered in the backend and can be independently configured with its own branding, prompts, RAG documents, and company list. Frontends are deployed as separate Docker containers with different config files.

### §2.4 Three-Tier Configuration Hierarchy

This is the key architectural difference from HRDD Helper.

**Level 1 — Global:** Default prompts, RAG documents, glossary, organizations list. Applied to all frontends and companies unless overridden.

**Level 2 — Frontend:** Each registered frontend can override or extend global config. Controls: branding, prompts, RAG documents, company list, organization list. Can choose to inherit global, ignore global, or combine.

**Level 3 — Company:** Within each frontend, each company button can have its own prompts and RAG documents. Can inherit from frontend level, ignore it, or combine.

**Resolution order (prompts)** — **winner-takes-all, NOT stacked**:
- **Normal role prompts** (core.md, guardrails.md, cba_advisor.md, context_template.md):
  1. Company-level prompt exists → use it
  2. Else frontend-level prompt exists → use it
  3. Else global prompt → use it
- **Compare All prompt** (compare_all.md): frontend → global. Company tier is skipped because Compare All is cross-company by definition.

The content of only one tier is sent to the model; tiers do not concatenate.

**Resolution order (RAG)** — **stackable**, controlled by `company.rag_mode` + `frontend.rag_standalone`:

Single-company chat:
- `rag_mode=own_only`: company docs only
- `rag_mode=inherit_frontend` or `combine_frontend`: company + frontend docs
- `rag_mode=inherit_all` or `combine_all` (default): company + frontend + global docs

**Frontend autonomy:** if `frontend.rag_standalone = true`, the global tier is EXCLUDED from the stack even when a company sets `inherit_all`. This lets a sector-specific frontend be completely self-contained. Default is `false` (frontend supplements global).

Compare All:
- Union of company docs from all enabled companies of the frontend (filtered by the user's `comparison_scope`: national → only companies matching the user's country tag; global → all; regional → Sprint 5 wires region groupings)
- + frontend docs
- + global docs, unless `frontend.rag_standalone`

**Resolution order (organizations list)** — `orgs_mode` per frontend:
- `inherit` (default when no override): use the global list only
- `own`: per-frontend list replaces the global list
- `combine`: global + per-frontend, deduplicated by `name` (per-frontend wins on collision)

**Resolution order (LLM config)** — per-frontend override is all-or-nothing:
- No per-frontend override file: frontend uses the global LLM config (3 slots + compression + routing)
- Override file present: that config is used in full for this frontend's chat sessions. The admin UI creates an override by snapshotting the current global config, then lets the admin edit it as a JSON file.

---

## §3 User Flow

### §3.1 Page Flow

```
[1] Language Selection
         │
         ▼
[2] Presentation & Disclaimer
         │
         ▼
[3] Session Token (automatic)
         │
         ▼
[4] Authentication (email verification)
    ├── Always present in flow
    └── Can be disabled per frontend via backend config
         │
         ▼
[5] Instructions Page
         │
         ▼
[6] Company Selection Page
    ├── "Compare All" button (first, always visible)
    └── Company buttons (alphabetical, configurable from backend)
         │
         ▼
[7] Survey Page (country, region, user data, initial query, document upload)
         │
         ▼
[8] Chat Interface
    ├── Initial query appears as first message
    ├── AI responds to initial query
    ├── User can continue conversation
    ├── User can upload documents during session
    └── User can request session summary (emailed to self)
```

### §3.2 Company Selection Page

Displays a vertical column of wide buttons:

1. **"Compare All"** — Always first. Loads all company RAGs for the current frontend. Enables sector-wide comparison.
2. **Company buttons** — Alphabetical order. Each loads company-specific prompts + RAG.

Button appearance: Full-width, stacked vertically, clear labels. Styled via frontend branding.

Backend controls: Companies can be added, removed, renamed, reordered. Each company has a `slug` (URL-safe identifier), `display_name`, and `enabled` flag.

### §3.3 "Compare All" Mode

When selected:
- Loads ALL company RAGs for the current frontend (combined)
- Uses the `compare_all.md` prompt (global or frontend-level)
- Survey includes additional field: **Comparison scope**
  - `national` — Only load CBAs from the user's selected country
  - `regional` — Load CBAs from the user's region (configurable region groupings)
  - `global` — Load all CBAs regardless of geography
- The comparison scope filters which company RAGs are loaded into context

### §3.4 Survey Page

Fixed fields (not configurable, injected as prompt context):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Country | Dropdown | Yes | ISO country list |
| Region | Text / Dropdown | Yes | Free text or admin-defined regions |
| Name | Text | No | User's name |
| Organization | Text | No | Union/federation name |
| Position | Text | No | Role in union |
| Email | Email | No | For receiving session summary |
| Initial query | Textarea | Yes | What does the user want to know? |
| Document upload | File | No | User can upload their CBA or other docs |
| Comparison scope | Radio | Only in "Compare All" | national / regional / global |

Uploaded documents go to the **session RAG** — indexed for this session only, not persisted to the global/frontend/company RAG.

### §3.5 Document Upload During Session

Users can upload documents at any point during chat. These are:
1. Indexed into session RAG (available for the rest of the conversation)
2. NOT automatically added to the permanent RAG
3. An admin alert is triggered (email notification) so the admin can review and optionally incorporate the document into the permanent RAG

---

## §4 Backend Services

### §4.1 Prompt Assembler

Assembles the system prompt from multiple layers:

```
[core.md]                          ← Always loaded (global only, never overridden)
[guardrails.md]                    ← Always loaded (global only, never overridden)
[role_prompt]                      ← Resolved: company → frontend → global
  ├── cba_advisor.md               ← Default for company selection
  └── compare_all.md               ← For "Compare All" mode
[context_template.md]              ← Rendered with survey data
[knowledge: glossary]              ← Language-specific terms
[knowledge: organizations]         ← Resolved: frontend → global
[RAG chunks]                       ← Retrieved from appropriate RAG tier(s)
```

Context template variables:
- `{company}`, `{country}`, `{region}`, `{name}`, `{organization}`, `{position}`, `{language}`, `{query}`, `{comparison_scope}`

### §4.2 RAG Service

**Storage layout:**
```
/app/data/
├── documents/                           ← Global
├── rag_index/                           ← Global index
├── campaigns/
│   └── {frontend_id}/
│       ├── documents/                   ← Frontend-level
│       ├── rag_index/
│       └── companies/
│           └── {company_slug}/
│               ├── documents/           ← Company-level (CBAs)
│               ├── rag_index/
│               └── metadata.json        ← Country tags per document
```

**Document metadata:** Each document in company RAG should have metadata including `country`, `language`, `document_type` (cba, policy, code_of_conduct, other). This enables filtering for Compare All national/regional modes.

**Supported formats:** .pdf, .docx, .txt, .md

**Indexing:** LlamaIndex with sentence-transformers embeddings (BAAI/bge-m3, 1024-dim, multilingüe). Chunk size 1024, overlap 100, top-k configurable. Hybrid BM25 + vector retrieval con cross-encoder reranker (bge-reranker-v2-m3).

**Session RAG:** Temporary index created per session for user-uploaded documents. Destroyed with session.

### §4.3 RAG File Watcher

New service using Python `watchdog` library:

- Watches `/app/data/documents/`, `/app/data/prompts/`, and all subdirectories under `/app/data/campaigns/`
- Detects: file creation, modification, deletion
- Filters: ignores `*.icloud`, `.DS_Store`, `._*`, `*.tmp`, `*.swp`
- **Debouncing:** After detecting a change, waits 5 seconds for additional changes before triggering reindex. Resets timer on each new change.
- **Scope-aware reindex:** Only rebuilds the affected index (global, frontend, or company level)
- **Prompt sync:** When a prompt file changes on disk, reloads it into the active prompt cache
- **Logging:** Logs all detected changes and reindex operations

### §4.4 Company Registry

New service managing company configurations per frontend:

```python
# Company config structure
{
    "slug": "amcor",
    "display_name": "Amcor",
    "enabled": true,
    "sort_order": 0,  # 0 = alphabetical (default)
    "prompt_mode": "inherit",  # "inherit" | "own" | "combine"
    "rag_mode": "combine_all",  # "own_only" | "inherit_frontend" | "inherit_all" | "combine_frontend" | "combine_all"
    "country_tags": ["AU", "US", "DE", "BR"],  # Countries with CBAs loaded
    "metadata": {}  # Extensible
}
```

Stored at: `/app/data/campaigns/{frontend_id}/companies.json`

Admin API endpoints:
- `GET /admin/api/v1/frontends/{fid}/companies` — List companies
- `POST /admin/api/v1/frontends/{fid}/companies` — Add company
- `PATCH /admin/api/v1/frontends/{fid}/companies/{slug}` — Update company
- `DELETE /admin/api/v1/frontends/{fid}/companies/{slug}` — Remove company
- `POST /admin/api/v1/frontends/{fid}/companies/{slug}/prompts` — Upload company prompt
- `POST /admin/api/v1/frontends/{fid}/companies/{slug}/documents` — Upload company RAG doc
- `POST /admin/api/v1/frontends/{fid}/companies/{slug}/reindex` — Rebuild company RAG index

### §4.5 Session Store

Adapted from HRDD Helper. Key differences:
- **Auto-destruction mode:** Configurable per frontend. Sessions can be set to auto-delete after N hours (0 = keep forever, default).
- **Session data includes:** company_slug, comparison_scope (for Compare All), uploaded_documents list
- **No internal case file:** Sessions don't generate a case file for UNI
- **User summary only:** At session end, generate a user-facing summary and email it to the user (if email provided)

Session storage:
```
/app/data/sessions/{token}/
├── session.json           ← Metadata
├── conversation.jsonl     ← Message log
├── uploads/               ← User-uploaded documents
└── session_rag_index/     ← Session-specific RAG index
```

### §4.6 Session Lifecycle

- `active` → `completed` → `archived` (or `destroyed`)
- Background scanner interval: 5 minutes
- Per-frontend configurable: `auto_close_hours`, `auto_cleanup_days`, `auto_destroy_hours` (NEW)
- `auto_destroy_hours: 0` = never destroy (default). When > 0, session files are completely deleted (not just archived) after N hours.
- On session close: generate user summary, email to user if email provided
- No UNI summary, no officer summary, no internal case file

### §4.7 LLM Provider

Adapted from HRDD Helper's LLM provider:
- **Three slots** — each picks a provider/model independently:
  - `inference` — main chat
  - `compressor` — periodic context-window compression (progressive, see below). Lightweight by default
  - `summariser` — heavier work: document summaries during injection, final conversation summary emailed to the user
- Circuit breaker, health checks, per-frontend overrides — carried over from HRDD
- Fallback cascade on failure: `compressor → summariser → inference` (preserves robustness from HRDD Sprint 17)

**Supported provider types (same for every slot):**

| Type | Location | Auth | Default endpoint |
|------|----------|------|------------------|
| `lm_studio` | local | none | `http://localhost:1234/v1` |
| `ollama` | local | none | `http://localhost:11434` |
| `api` | remote cloud | API key | depends on flavor (see below) |

For `api` provider, the admin picks a flavor:
- `anthropic` — Anthropic Claude (`https://api.anthropic.com/v1`)
- `openai` — OpenAI (`https://api.openai.com/v1`)
- `openai_compatible` — any OpenAI-compatible endpoint (Groq, Together, Mistral, etc.); admin provides the full base URL

In Docker deployments where the LLM runtime is on the Docker host, `localhost` inside the backend container does not reach the host — admins typically override the endpoint to `http://host.docker.internal:<port>` (OrbStack / Docker Desktop) or to a sibling-container hostname. The admin UI auto-fills the field with the backend's configured default, which the deployment's `deployment_backend.json` controls.

**API key handling:** API keys are never stored in plaintext in config files or committed to git. The admin config stores the *name* of an environment variable (e.g. `ANTHROPIC_API_KEY`), which the container reads at startup. Portainer stack environment variables are the intended mechanism. Keys are redacted from logs and admin API responses.

**Context compression settings** (top-level, independent of the slot configs):
- `enabled` — master toggle; when `false`, conversations are passed to `inference` unchanged
- `first_threshold` — token count (estimated) at which the first compression fires (default `20000`)
- `step_size` — subsequent compressions fire every N tokens after the first (default `15000`). So if `first=20000`, `step=15000`, compressions happen at 20k, 35k, 50k, 65k, ...

The compression prompt lives at `prompts/context_compression.md` and is admin-editable like any other prompt (3-tier resolution applies).

**Summary routing toggles** (choose which slot handles summarisation tasks):
- `document_summary_slot` — who summarises an uploaded document before injection into chat context. Options: `inference` | `compressor` | `summariser`. Default: `summariser`.
- `user_summary_slot` — who generates the final conversation summary emailed to the user at session close. Options: `inference` | `compressor` | `summariser`. Default: `summariser`.

Both toggles support all three slots so admins can combine a heavy model for chat with a lighter one for document/summary work, or vice versa.

**Mixing providers:** Every slot can use any provider type independently (e.g. cloud `api` for `inference`, local `ollama` for `compressor`, `api` again for `summariser`). Per-frontend overrides can swap providers per slot without affecting the global default.

**Not supported in v1.0:** multimodal / image inputs.

### §4.8 SMTP Service

Outgoing email for:
- Auth verification codes (Sprint 7)
- User session summaries (to the email the user provided in the survey)
- Admin notifications (session summary + new document uploaded by user)

**Global config:** `host`, `port`, `username`, `password`, `use_tls`, `from_address`, `admin_notification_emails: list[str]`, plus three toggles (`send_summary_to_user`, `send_summary_to_admin`, `send_new_document_to_admin`).

**Per-frontend notification override:** lives at `/app/data/campaigns/{frontend_id}/notifications.json` and only overrides the **admin recipient list**, not the toggles. Admins can configure a sector-specific responsible person to receive notifications for a specific frontend. Two modes:
- `replace` — per-frontend list replaces the global admin list for this frontend's notifications
- `append` — per-frontend emails are added to the global list (deduplicated)

Admin auth flow (Sprint 7) reads the Contacts store (§4.11) as the allowlist — NOT the SMTP notification emails.

### §4.9 Frontend Registry

Admin registers each frontend with just two fields:
- `url` — where the sidecar is reachable from the backend container (e.g. `http://cbc-frontend`, `http://100.64.0.5:8190`).
- `name` — human-readable label shown throughout the admin UI (e.g. `Packaging — Europe`).

The backend auto-generates `frontend_id` (the internal slug used as the storage key for `/app/data/campaigns/{frontend_id}/`) by slugifying the name and appending `-2`, `-3`, … if it collides with an existing one. Admins do not see or manage `frontend_id` in normal operation — the UI shows the display name everywhere.

Frontend containers themselves are anonymous: they don't need to know their backend-side ID. The backend already knows which frontend it's polling because it's hitting that frontend's registered URL. One Docker image deploys to N frontends without rebuilds.

CBC does **not** auto-register: the sidecar never initiates contact with the backend, preserving the HRDD "frontend doesn't know the backend" rule (portability across NAT/firewall/Tailscale). Registration is a one-time admin action on the Frontends tab.

**Runtime state:** `status` (online | offline | unknown) and `last_seen` are updated by the polling loop every 5 seconds via `GET {url}/internal/health`. Only `online` writes `last_seen`. Runtime state is NOT persisted — recomputed on every poll.

**Persistent storage:** `/app/data/frontends.json`, atomic writes.

**Per-frontend config resolution** (push pattern from HRDD):
- Admin edits branding or session-settings override in the admin UI
- Backend `PUT` endpoint saves to `/app/data/campaigns/{frontend_id}/{branding,session_settings}.json`
- Backend `POST /internal/branding` or `/internal/session-settings` on the frontend's URL
- Sidecar caches the pushed payload and merges it into its `/internal/config` response
- If the sidecar is offline at push time, the admin UI still saves successfully — the sidecar will re-read the pushed cache from its own local cache on next boot (pushed caches live in the frontend container's `/app/data/`)

**Session settings fields (all optional — None means inherit from `deployment_frontend.json`):**
`auth_required`, `session_resume_hours`, `auto_close_hours`, `auto_destroy_hours`, `disclaimer_enabled`, `instructions_enabled`, `compare_all_enabled`, `rag_standalone` (when `true`, global RAG docs are excluded from this frontend's resolution even when a company sets `rag_mode=inherit_all`; backend-only, not pushed to the sidecar).

**Branding fields:** `app_title`, `logo_url`, `primary_color`, `secondary_color`.

**Branding precedence (HRDD-style — baseline lives in code, not in JSON):**
1. Per-frontend override (admin saves on Frontends tab → Branding)
2. Global default (admin saves on General tab → Branding defaults; backend fans out to every frontend without its own override)
3. Hardcoded constant in `sidecar/main.py` (`_HARDCODED_BRANDING`) — UNI Global logo + title + UNI palette

`deployment_frontend.json` does NOT carry branding fields. Per-deployment customisation happens through the admin UI.

### §4.10 Guardrails

Two independent layers:

**1. Prompt layer** — `guardrails.md` is injected into every system prompt.
Instructs the LLM: no legal advice (redirect to the union's legal team), no
fabrication of CBA clauses (must be grounded in the RAG), stay in scope,
flag sensitive topics (strikes, industrial action), use the union's own
escalation path.

**2. Runtime layer** — `services/guardrails.py` inspects every user message
before it reaches the LLM. Two pattern categories:
- `hate_speech` — slurs, dehumanising language, explicit calls for
  violence against groups, racial/ethnic supremacy framing, "workers
  from {group} should be {deported|removed|eliminated}" (the `fired`
  verb was dropped from that last pattern because legitimate CBA
  discussions use it routinely).
- `prompt_injection` — "ignore your instructions", identity-override
  attempts, system-prompt extraction, DAN-style jailbreaks, debug-mode
  traps.

No separate `fabrication` category in v1 (Sprint 7.5 D1): CBC's authenticated
trade-unionist population is low-risk, and the prompt layer already
instructs the LLM to refuse fabrication.

**Enforcement (Sprint 7.5 D3, HRDD Sprint 16 pattern)**: on any triggered
message, the polling loop **skips the LLM call**, persists a fixed response
as the assistant turn, and increments `session.guardrail_violations`. Once
the count reaches `guardrail_max_triggers`, the session is flagged + marked
`completed`; the user receives the localised "session ended" message.

**Thresholds** live in `deployment_backend.json` / `core/config.BackendConfig`:
- `guardrail_warn_at` — default 2. ChatShell shows the amber banner from
  this count onwards.
- `guardrail_max_triggers` — default 5. Hard stop threshold.

Per-frontend overrides are deferred until tuning demand justifies the
plumbing (Sprint 7.5 D2 = global only).

**Admin visibility** — General tab hosts a read-only Guardrails section
(`/admin/api/v1/guardrails`) showing current thresholds, every active
pattern per category, and the localised response text the user sees.

**Sidecar → ChatShell** — `/internal/guardrails/thresholds` proxies the
public `/api/v1/guardrails/thresholds` backend endpoint so the UI reads
live values (falls back to 2/5 when the proxy can't reach the backend).

### §4.11 Contacts (Authorized Users Directory)

Adapted from HRDD Helper. Directory of authorized end-user emails with profile metadata. Drives the email-code auth flow (Sprint 7) as the allowlist.

**Fields per contact** (identical to HRDD for xlsx portability):
- `email` (required, lowercase-normalised)
- `first_name`, `last_name`, `organization`, `country`, `sector`, `registered_by`

**Storage:** `/app/data/contacts.json`
```
{
  "global": [Contact, ...],
  "per_frontend": {
    "{frontend_id}": {"mode": "replace" | "append", "contacts": [Contact, ...]}
  }
}
```

**Resolution for a given frontend:**
- No per-frontend entry → use global
- `mode: replace` → per-frontend list only
- `mode: append` → global + per-frontend, deduped by email

**Admin operations** (all require admin JWT):
- CRUD at global and per-frontend scopes
- Copy contacts from one frontend's override to another
- Export to `.xlsx` (single scope or `all` for multi-sheet workbook)
- Import from `.xlsx` or `.csv` — **additive merge only**: existing emails get non-empty fields updated; new emails are added; emails in the store but not in the file are preserved

**Admin UI:** dedicated "Registered Users" tab (§5.1 layout) with sortable/filterable inline-editable table, scope selector, mode + copy-from, export/import buttons.

---

## §5 Admin Panel

### §5.1 Layout

Single-page app with **three tabs**: **General Configuration**, **Frontend Configuration**, **Registered Users**.

**Tab 1 — General Configuration:**
- Branding defaults (logo, colors, app title)
- Global prompts (list, edit, save)
- Global RAG (upload documents, reindex, view stats)
- Glossary management (terms + translations, download/upload JSON)
- Organizations list (download/upload JSON)
- LLM configuration per slot (`inference`, `compressor`, `summariser`) — provider type (`lm_studio` | `ollama` | `api`), model, temperature, max tokens, context window; API flavor + endpoint + key-env-var name when provider is `api`. Top indicator polls the auto-detected local endpoints every 15s. Model field is a `<select>` populated from `/v1/models` (LM Studio / OpenAI-compat / Anthropic) or `/api/tags` (Ollama)
- Context compression settings — `enabled` toggle + `first_threshold` + `step_size` (progressive thresholds)
- Summary routing toggles — `document_summary_slot` and `user_summary_slot`, each picking one of `inference` / `compressor` / `summariser`
- Endpoint auto-detect: probes `deployment_backend.json` override → `host.docker.internal:<port>` → `localhost:<port>` and picks whichever responds. Admins can override per slot for Tailscale / remote boxes.
- SMTP configuration with three notification toggles (`send_summary_to_user`, `send_summary_to_admin`, `send_new_document_to_admin`) and a global admin-notification-emails list
- Per-frontend notification override: replace or append the global admin-emails list for a specific frontend

**Tab 3 — Registered Users** (see §4.11): directory of authorized end-user emails with xlsx/csv import/export + per-frontend replace/append overrides.

**Tab 2 — Frontend Configuration:**
- Dropdown to select frontend (from registered list)
- Once selected, shows for that frontend:
  - **Branding** override (logo, colors, title — or inherit global)
  - **Prompts** (list, edit — or inherit global)
  - **RAG documents** (upload, reindex — or inherit global, or combine)
  - **Organizations list** (inherit global, own, or combine)
  - **Company management:**
    - Add/remove/rename/reorder companies
    - Per company expandable section:
      - Prompts (inherit frontend, own, combine)
      - RAG documents (upload, view, modes: own_only / inherit_frontend / inherit_all / combine_*)
      - Country tags
  - **Session settings:** auth_required, auto_close_hours, auto_destroy_hours, session_resume_hours
  - **Feature toggles:** disclaimer_enabled, instructions_enabled, compare_all_enabled
  - **LLM override** — single "Override global config" toggle. When enabled, snapshots the current global LLM config (all three slots + compression + routing) into `/app/data/campaigns/{frontend_id}/llm.json`; from then on this frontend uses the override and is unaffected by global LLM edits. Each slot supports the same three provider types as the global tab (`lm_studio` | `ollama` | `api`, with API flavor + endpoint + key-env-var name). When the toggle is off, no override file exists and the frontend inherits the global config (D2=B in the architecture decisions: full-override or full-inherit, no partial merge).

### §5.2 Admin Auth

Identical to HRDD Helper: password setup on first access, bcrypt hash, JWT tokens.

---

## §6 Configuration Schema

### §6.1 Backend Config (deployment_backend.json)

```json
{
    "role": "backend",
    "lm_studio_endpoint": "http://host.docker.internal:1234/v1",
    "lm_studio_model": "qwen3-235b-a22b",
    "ollama_endpoint": "http://host.docker.internal:11434",
    "ollama_summariser_model": "qwen2.5:7b",
    "ollama_num_ctx": 8192,
    "rag_documents_path": "./data/documents",
    "rag_index_path": "./data/rag_index",
    "rag_chunk_size": 512,
    "rag_similarity_top_k": 5,
    "rag_embedding_model": "BAAI/bge-m3",
    "rag_watcher_enabled": true,
    "rag_watcher_debounce_seconds": 5,
    "streaming_enabled": true,
    "stream_chunk_size": 1,
    "poll_interval_seconds": 2,
    "sessions_path": "./data/sessions",
    "prompts_path": "./data/prompts",
    "guardrails_enabled": true,
    "guardrail_max_triggers": 3,
    "file_max_size_mb": 25,
    "session_token_reuse_cooldown_days": 30
}
```

### §6.2 Frontend Config (deployment_frontend.json)

```json
{
    "role": "frontend",
    "frontend_id": "packaging-eu",
    "backend_url": "http://cbc-backend:8000",
    "auth_required": true,
    "disclaimer_enabled": true,
    "instructions_enabled": true,
    "compare_all_enabled": true,
    "session_resume_hours": 48,
    "auto_close_hours": 72,
    "auto_destroy_hours": 0,
    "output_user_summary": true,
    "branding": {
        "app_title": "CBC — Packaging EU",
        "logo_url": "/assets/logo.png",
        "primary_color": "#1e40af",
        "secondary_color": "#f59e0b"
    }
}
```

### §6.3 Company Config (companies.json per frontend)

```json
[
    {
        "slug": "compare-all",
        "display_name": "Compare All",
        "enabled": true,
        "sort_order": -1,
        "is_compare_all": true
    },
    {
        "slug": "amcor",
        "display_name": "Amcor",
        "enabled": true,
        "sort_order": 0,
        "prompt_mode": "inherit",
        "rag_mode": "combine_all",
        "country_tags": ["AU", "US", "DE", "BR"]
    },
    {
        "slug": "ds-smith",
        "display_name": "DS Smith",
        "enabled": true,
        "sort_order": 0,
        "prompt_mode": "inherit",
        "rag_mode": "combine_all",
        "country_tags": ["UK", "DE", "FR", "IT", "PL"]
    }
]
```

---

## §7 Internationalization

Frontend UI uses a single-file i18n bundle (`src/frontend/src/i18n.ts`) with the same 31-language set as HRDD Helper. The language is picked on the opening LanguageSelector screen and carried as `LangCode` through the rest of the flow; the LLM is asked to respond in that language via the system prompt.

### §7.1 Supported languages (Sprint 8)

Full UI translation for all 31 HRDD-parity languages:

EN, ES, FR, DE, PT, IT, NL, PL, SV, HU, EL, RO, HR, UK, RU, TR, AR, UR, ZH, JA, KO, VI, TH, ID, HI, BN, MR, TE, TA, XH, SW.

Arabic and Urdu render right-to-left; `App.tsx` sets `document.documentElement.dir="rtl"` whenever the active lang is in `RTL_LANGS = ['ar', 'ur']`.

`t(key, lang)` falls back through: `DICTIONARIES[lang][key] → EN[key] → key-name` so a missing translation never crashes the page — it just shows the English copy for that one string.

Translations were generated by Claude in the Sprint 8 sweep and are flagged in the i18n file header as MVP-quality, pending a native-speaker QA pass per language.

### §7.2 Translatable admin-editable text (Sprint 8)

`disclaimer_text` and `instructions_text` on the `Branding` model carry admin-written overrides that replace the i18n defaults. Each tier (global / per-frontend) that sets one of these also carries:

- `source_language: str` — the language the admin wrote the text in (defaults to `"en"`).
- `disclaimer_text_translations: dict[str, str]` — `{lang_code: translated_text}`.
- `instructions_text_translations: dict[str, str]` — same shape for instructions.

Tier-ownership rule (resolvers.py): whichever tier owns the source text also owns the translations dict. A tier cannot override translations without also setting the source text. This keeps translations tied to the exact source string they were produced from.

Frontend resolution (`pickBrandingText` in i18n.ts):
1. `translations[user_lang]` if present and non-empty
2. source text (when `user_lang === source_language`, or as a best-effort fallback so the user sees something consistent with the admin's intent)
3. otherwise — admin didn't set a custom text at any tier — fall back to the i18n default for that page section.

### §7.3 Translation workflow (Sprint 8)

Admin UI (BrandingSection for globals, BrandingPanel for per-frontend) offers three controls on the same card as the free-text textareas:

- **Download JSON** — `GET /admin/api/v1/.../translations` returns a portable bundle:
  ```
  {
    "source_language": "en",
    "disclaimer_text": "...",
    "instructions_text": "...",
    "disclaimer_text_translations": {"es": "...", "fr": "..."},
    "instructions_text_translations": {"es": "...", "fr": "..."}
  }
  ```
  Admin edits it in any text editor (or ships it to a translation service) and uploads it back.
- **Upload JSON** — `PUT /admin/api/v1/.../translations` applies the bundle onto the existing record, preserving non-text fields (logo, colors, app_title, org_name).
- **Auto-translate missing** — `POST /admin/api/v1/.../auto-translate` runs `branding_translator.auto_translate_branding()` which walks every language ≠ source and, for each empty slot, asks the LLM (summariser slot → normal fallback chain) to translate using the `translate.md` system prompt. Existing non-empty translations are preserved.

The `translate.md` prompt is admin-editable via the file watcher (lives at `/app/data/prompts/translate.md`). If no disk copy exists, the backend falls back to the image-shipped copy.

Auto-translate is synchronous and blocks the admin request for ~30–60 s on a local summariser (30 targets × 2 text blocks). The response returns stats: `{disclaimer_filled, disclaimer_failed, instructions_filled, instructions_failed}`.

---

## §8 Security & Privacy

### §8.1 Auth
- Email verification with 6-digit code (reuse HRDD Helper flow)
- Configurable per frontend (can be disabled)
- Admin panel: bcrypt password + JWT

### §8.2 Session Privacy
- Auto-destruction mode: sessions completely deleted after configurable hours
- Session data never shared between frontends
- User-uploaded documents stay in session scope only (unless admin promotes to permanent RAG)

### §8.3 Data Handling
- All data on local Docker volumes — no cloud storage
- No analytics, no tracking, no third-party services
- SMTP only for auth codes, summaries, and admin alerts
- When the LLM `api` provider is configured, chat content leaves the deployment to the chosen cloud endpoint. This is the one intentional exception to "no third-party services"; admins who require full on-premises operation must use `lm_studio` or `ollama` for both slots.
- API keys for `api` providers are referenced by env var name only; never stored in plaintext in config files or logs, never committed to git.

---

## §9 Deployment

### §9.1 Docker Compose

Two compose files:
1. `docker-compose.backend.yml` — Backend + Admin SPA
2. `docker-compose.frontend.yml` — Frontend (one instance per deployment)

**Multiple frontends from the same image.** Frontend containers are anonymous — they don't carry an identity that the backend cares about. To deploy a second frontend without rebuilding the image:

```bash
docker run -d \
  --name cbc-frontend-<short-name> \
  -p <host-port>:80 \
  -v cbc-frontend-<short-name>-data:/app/data \
  --network cbc-net \
  cbcopilot-cbc-frontend
```

In Portainer, the same pattern: paste `docker-compose.frontend.yml` into a new stack, set `CBC_FRONTEND_PORT`, and override `container_name` + the volume name so the new instance doesn't collide with the existing one. The image is reusable.

After the container is running, register it from the admin (Frontends tab → Register) with the URL (`http://cbc-frontend-<short-name>` over `cbc-net`) and a display name. The backend assigns the internal storage ID automatically; the polling loop picks it up within 5s.

### §9.2 Volumes

```yaml
volumes:
  cbc-data:        # Backend persistent data (sessions, prompts, RAG, configs)
```

### §9.3 RAG Volume Mount

For file watcher to work with host filesystem (OrbStack):
```yaml
volumes:
  - ./data/documents:/app/data/documents
  - ./data/campaigns:/app/data/campaigns
  - ./data/prompts:/app/data/prompts
```

This allows editing RAG documents and prompts directly on disk — the file watcher picks up changes and reindexes automatically.

---

## §10 Known Limitations (v1.0)

- **No real-time collaboration** — each session is single-user
- **No version control for CBAs** — documents are replaced, not versioned
- **Regional comparison is approximate** — region groupings are admin-defined, not geographic
- **No automatic CBA parsing** — documents are chunked as-is, not structured into clause/article format
- **LLM quality depends on context window** — loading many company RAGs in Compare All mode may exceed context limits. Mitigation: context compression from HRDD Helper.
- **No offline mode** — requires network access to backend and LLM provider
