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

**Resolution order (prompts):**
1. Company-level prompt exists → use it
2. Else frontend-level prompt exists → use it
3. Else global prompt → use it

**Resolution order (RAG):**
- Configurable per company: `rag_mode: "own_only" | "inherit_frontend" | "inherit_all" | "combine_frontend" | "combine_all"`
- `own_only`: Only company RAG
- `inherit_frontend`: Company + Frontend RAG
- `inherit_all`: Company + Frontend + Global RAG
- `combine_frontend`: Same as inherit_frontend (alias)
- `combine_all`: Same as inherit_all (alias, default)

**Resolution order (organizations list):**
- Frontend can choose: `orgs_mode: "global" | "own" | "combine"`

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

**Indexing:** LlamaIndex with sentence-transformers embeddings (all-MiniLM-L6-v2). Chunk size 512, overlap 50, top-k 5 (all configurable).

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

Reuse HRDD Helper's LLM provider with simplification:
- Two slots only: `inference` (main chat) and `summariser` (session summary)
- No `reporter` slot (no formal reports)
- Circuit breaker, health checks, per-frontend overrides — all carried over
- Per-slot provider selection — each slot picks independently from the three provider types below

**Supported provider types:**

| Type | Location | Auth | Default endpoint |
|------|----------|------|------------------|
| `lm_studio` | local | none | `http://host.docker.internal:1234/v1` |
| `ollama` | local | none | `http://host.docker.internal:11434` |
| `api` | remote cloud | API key | depends on flavor (see below) |

For `api` provider, the admin picks a flavor:
- `anthropic` — Anthropic Claude (`https://api.anthropic.com/v1`)
- `openai` — OpenAI (`https://api.openai.com/v1`)
- `openai_compatible` — any OpenAI-compatible endpoint (Groq, Together, Mistral, etc.); admin provides the full base URL

**API key handling:** API keys are never stored in plaintext in config files or committed to git. The admin config stores the *name* of an environment variable (e.g. `ANTHROPIC_API_KEY`), which the container reads at startup. Portainer stack environment variables are the intended mechanism. Keys are redacted from logs and admin API responses.

**Mixing providers:** The two slots can use different provider types independently (e.g. cloud `api` for `inference`, local `ollama` for `summariser`). Per-frontend overrides can swap providers per slot without affecting the global default.

### §4.8 SMTP Service

Reuse from HRDD Helper. Used for:
- Auth verification codes
- User session summaries (emailed at session close)
- Admin alerts (new document uploaded by user)

### §4.9 Frontend Registry

Reuse from HRDD Helper. Tracks registered frontends, health status, enabled flag.

### §4.10 Guardrails

Reuse from HRDD Helper with adapted rules:
- No legal advice
- No fabrication of CBA terms — only what's in the RAG
- Redirect to union if query is outside scope
- Flag sensitive topics (strikes, industrial action)
- Max trigger count before session warning

---

## §5 Admin Panel

### §5.1 Layout

Single-page app with **two main tabs**:

**Tab 1 — General Configuration:**
- Branding defaults (logo, colors, app title)
- Global prompts (list, edit, save)
- Global RAG (upload documents, reindex, view stats)
- Glossary management (terms + translations)
- Organizations list (add, edit, remove)
- LLM configuration per slot (`inference`, `summariser`) — provider type (`lm_studio` | `ollama` | `api`), model, temperature, max tokens, context window; API flavor + endpoint + key-env-var name when provider is `api`
- SMTP configuration
- Registered users

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
    "rag_embedding_model": "all-MiniLM-L6-v2",
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

Reuse HRDD Helper's i18n system (i18next). The frontend detects language from user selection and sends it to backend. All UI strings are translatable. The LLM responds in the user's language.

Supported languages: Any (no restrictions). UI translations provided for: EN, ES, FR, DE, PT (expandable via JSON files).

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

Three compose files:
1. `docker-compose.backend.yml` — Backend + Admin SPA
2. `docker-compose.frontend.yml` — Frontend (one instance per deployment)

Frontend instances are deployed by copying the compose file with different env vars (frontend_id, ports).

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
