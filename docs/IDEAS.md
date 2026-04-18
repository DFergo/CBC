# CBC — Ideas Backlog

Feature ideas captured during development but not yet scoped into a sprint. Each entry shows when it was captured and, when known, a candidate sprint to land it in.

Statuses: `captured` → `triaged` → `planned` (→ Sprint N) → `shipped` / `rejected`.

---

## LLM provider options: Ollama, LM Studio, API

**Captured:** 2026-04-18 (Sprint 3)
**Status:** planned → Sprint 3 (admin UI + config schema) and Sprint 6 (chat engine exercises all three); promoted via `/spec` on 2026-04-18. Spec landed in §4.7 + §5.1 + §8.3.
**Candidate sprint:** 3 (LLM admin config UI) + 6 (chat engine actually uses it)
**Context:** SPEC §4.7 currently lists "LM Studio, Ollama (OpenAI-compatible API)". Both are local providers on `host.docker.internal`. The admin LLM tab should offer three distinct provider types: Ollama, LM Studio, and "API" (remote cloud providers — Anthropic, OpenAI, etc.) as separate, first-class options.

**Idea:** "la selección de llm incluir opciones ollama, lm studio y api." — admin's LLM configuration dropdown lets the user pick per slot (inference / summariser) between the two local runtimes and a remote cloud API, with whatever credentials / endpoint fields each option needs.

**Open questions:**
- Which cloud providers under "API"? Anthropic only, OpenAI only, both, or a generic "OpenAI-compatible endpoint" that also fits Groq / Together / Mistral?
- Where do API keys live? Env var at container start, admin-panel input (stored encrypted in config), or both?
- Can different slots use different providers (e.g. API for inference, local Ollama for summariser)? HRDD's LLM provider supports per-slot config, so yes in principle.
- Per-frontend LLM override (HRDD pattern) should still work for cloud API slots — confirm.
- Streaming: all three options must keep SSE streaming working end-to-end with the pull-inverse pattern.
- Cost tracking / rate limiting for remote API — in scope for v1.0 or defer?

**Prerequisite work:**
- Sprint 1 backend config already allows LM Studio / Ollama endpoints — schema will need an `api` provider block with `endpoint`, `api_key`, `model` fields
- Sprint 3 is building the LLM admin tab — easiest place to land this
- `llm_provider.py` (adapted from HRDD in Sprint 6) needs a third branch for remote API (auth headers, different error shapes)
- Security: API keys must not be committed or logged — extend secret-redaction pattern

---

## CBA sidepanel in chat — browse & download loaded agreements

**Captured:** 2026-04-18 (Sprint 2)
**Status:** captured
**Candidate sprint:** 6 (Chat Engine) or a new sprint between 6 and 8
**Context:** Company buttons on CompanySelectPage originally showed inline country tags (e.g. `AU · US · DE · BR`). Daniel removed them: cluttered, and the information belongs somewhere more useful.

**Idea:** During chat, a side panel lists the CBAs loaded for the current company (for "Compare All" mode, all loaded CBAs filtered by comparison scope). Each entry shows country, language, document type, and a download button.

**Open questions:**
- Only company-scoped documents, or include frontend + global RAG too (subject to `rag_mode`)?
- Download the original file or a normalized text excerpt?
- Permission model — all users can download, or admin-only?
- Does download count as data egress we need to audit (logging + rate limit)?
- Does this replace, supplement, or sit alongside inline citations in chat responses?

**Prerequisite work already in place:**
- `country_tags` is still in the `Company` type + `companies.json` — Sprint 2 only removed the button display, not the data
- Sprint 5's RAG metadata (country, language, document_type) fits what the panel needs

---

<!-- Append new ideas above this line. Never delete; mark rejected instead. -->
