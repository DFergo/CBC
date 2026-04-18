# CBC — Architecture Overview

## System Architecture

```
                                    ┌─────────────────────────────────┐
                                    │         LLM Provider            │
                                    │  (LM Studio / Ollama)           │
                                    │  host.docker.internal:1234      │
                                    └───────────────┬─────────────────┘
                                                    │
                                                    │ OpenAI-compatible API
                                                    │
┌───────────────────────────────────────────────────┼─────────────────────────┐
│ Docker Network                                    │                         │
│                                                   │                         │
│  ┌────────────────────────────────────────────────┼──────────────────────┐  │
│  │ Backend Container (port 8000)                  │                      │  │
│  │                                                │                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────┴───────┐              │  │
│  │  │ Admin SPA    │  │ RAG Engine   │  │ LLM Provider   │              │  │
│  │  │ (React,      │  │ (LlamaIndex) │  │ (2 slots:      │              │  │
│  │  │  embedded)   │  │              │  │  inference +   │              │  │
│  │  └──────────────┘  └──────────────┘  │  summariser)   │              │  │
│  │                                      └────────────────┘              │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐              │  │
│  │  │ File Watcher │  │ Prompt       │  │ Session        │              │  │
│  │  │ (watchdog)   │  │ Assembler    │  │ Lifecycle      │              │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘              │  │
│  │                                                                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐              │  │
│  │  │ Company      │  │ Frontend     │  │ SMTP           │              │  │
│  │  │ Registry     │  │ Registry     │  │ Service         │              │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘              │  │
│  │                                                                      │  │
│  │  Data Volume: /app/data/                                             │  │
│  │  ├── sessions/  prompts/  documents/  rag_index/  campaigns/         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│           │ poll (2s)         │ SSE stream                                 │
│           ▼                  ▼                                             │
│  ┌──────────────────────────────────────┐                                  │
│  │ Frontend Container (port 8091+)      │                                  │
│  │                                      │                                  │
│  │  ┌──────────┐    ┌────────────────┐  │                                  │
│  │  │ Nginx    │    │ Sidecar        │  │                                  │
│  │  │ (port 80)│    │ (FastAPI 9000) │  │                                  │
│  │  │ serves   │    │ message queue  │  │                                  │
│  │  │ React SPA│    │ SSE relay      │  │                                  │
│  │  └──────────┘    │ auth verify    │  │                                  │
│  │                  │ file uploads   │  │                                  │
│  │                  └────────────────┘  │                                  │
│  └──────────────────────────────────────┘                                  │
│                     ▲                                                      │
└─────────────────────┼──────────────────────────────────────────────────────┘
                      │
                 ┌────┴─────┐
                 │  User    │
                 │ (Browser)│
                 └──────────┘
```

## Three-Tier Configuration

```
┌─────────────────────────────────────────────────────────┐
│ GLOBAL (Level 1)                                        │
│ /app/data/prompts/         ← Default prompts            │
│ /app/data/documents/       ← Global RAG docs            │
│ /app/data/knowledge/       ← Glossary + Organizations   │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ FRONTEND (Level 2) — e.g. "packaging-eu"          │  │
│  │ /app/data/campaigns/{frontend_id}/                │  │
│  │ ├── prompts/          ← Override or inherit       │  │
│  │ ├── documents/        ← Frontend RAG docs         │  │
│  │ ├── branding.json     ← UI customization          │  │
│  │ ├── companies.json    ← Company list              │  │
│  │ ├── orgs.json         ← Override or inherit       │  │
│  │ │                                                 │  │
│  │ │  ┌──────────────────────────────────────────┐   │  │
│  │ │  │ COMPANY (Level 3) — e.g. "amcor"         │   │  │
│  │ │  │ /companies/{slug}/                       │   │  │
│  │ │  │ ├── prompts/    ← Override or inherit    │   │  │
│  │ │  │ ├── documents/  ← Company CBAs           │   │  │
│  │ │  │ └── metadata.json                        │   │  │
│  │ │  └──────────────────────────────────────────┘   │  │
│  │ └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Data Flow: Chat Message

```
1. User types message in React ChatShell
2. React POSTs to Sidecar /internal/queue
3. Sidecar queues message (in-memory, TTL 300s)
4. Backend polls Sidecar /internal/queue (every 2s)
5. Backend dequeues message
6. Backend resolves config:
   a. Load company config (or Compare All config)
   b. Resolve prompt: company → frontend → global
   c. Resolve RAG: query appropriate tier(s)
   d. Retrieve relevant chunks (top-k)
7. Backend assembles system prompt:
   core + guardrails + role_prompt + context + knowledge + RAG_chunks
8. Backend calls LLM (streaming)
9. Backend streams tokens to Sidecar /internal/stream (SSE)
10. Sidecar relays SSE to React app
11. React renders tokens incrementally
```

## Data Flow: Compare All

```
1. User selects "Compare All" on CompanySelectPage
2. Survey includes comparison_scope (national/regional/global)
3. On chat message:
   a. Backend loads compare_all.md prompt
   b. Backend identifies all companies for this frontend
   c. Filter by comparison_scope:
      - national: only companies with country_tags matching user's country
      - regional: companies with country_tags in user's region group
      - global: all companies
   d. Query RAG from all matching companies (combined)
   e. Include global + frontend RAG if rag_mode allows
4. Response synthesizes across multiple CBAs
```

## Data Flow: File Watcher

```
1. watchdog observes /app/data/ tree
2. File created/modified/deleted
3. Watcher checks: is it in documents/ or prompts/?
4. If documents/:
   a. Determine scope (global / frontend / company)
   b. Start debounce timer (5s)
   c. On timer expiry: rebuild affected index only
5. If prompts/:
   a. Reload prompt into memory cache
   b. No debounce needed (instant)
6. Ignore: *.icloud, .DS_Store, ._*, *.tmp, *.swp
```
