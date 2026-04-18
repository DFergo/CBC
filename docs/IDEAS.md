# CBC — Ideas Backlog

Feature ideas captured during development but not yet scoped into a sprint. Each entry shows when it was captured and, when known, a candidate sprint to land it in.

Statuses: `captured` → `triaged` → `planned` (→ Sprint N) → `shipped` / `rejected`.

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
