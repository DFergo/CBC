# Lessons Learned from HRDD Helper Development

These pitfalls were encountered during HRDD Helper development. Apply them to CBC.

## 1. Atomic Writes for All JSON State

**Problem:** JSON files can be corrupted if the process crashes during a write (e.g., sessions.json half-written).

**Solution:** Always write to a `.tmp` file, then `os.rename()` to the final path. `os.rename()` is atomic on POSIX systems.

**Applies to:** session.json, companies.json, frontends.json, branding.json, all config files.

## 2. Sidecar Message TTL

**Problem:** If the backend is slow to poll (startup, LLM overloaded), sidecar messages expire after 300 seconds and the user sees no response.

**Solution:** TTL of 300s is the default. Monitor and adjust. Consider a "still processing" heartbeat from backend to sidecar.

**Applies to:** Frontend sidecar message queue.

## 3. Admin SPA Build Must Be Embedded

**Problem:** Early attempts served admin from a separate container. This created CORS issues and deployment complexity.

**Solution:** Build admin React app in Docker Stage 1, copy to backend image, serve as SPA fallback. Single endpoint, no CORS needed.

**Applies to:** Dockerfile.backend multi-stage build.

## 4. LLM Circuit Breaker

**Problem:** When LLM provider goes down, requests pile up and the backend becomes unresponsive.

**Solution:** Track failures per slot. If 3+ failures in 60s window, disable slot for 300s cooldown. Health endpoint reports slot status.

**Applies to:** LLM provider service.

## 5. Prompt Assembly Order Matters

**Problem:** Guardrails were sometimes overridden by role-specific prompts that came after them.

**Solution:** Guardrails are injected as a non-negotiable layer. They're part of the "core" block, not a role-specific overlay. Core + guardrails ALWAYS come first, regardless of inheritance.

**Applies to:** Prompt assembler — critical for CBC's 3-tier system.

## 6. Frontend Registry Persistence

**Problem:** Frontend list was initially in-memory only. Backend restart lost all registered frontends.

**Solution:** Persist to `/app/data/frontends.json`. Load on startup. Atomic writes.

**Applies to:** Frontend and company registries.

## 7. RAG Index Rebuilds Are Expensive

**Problem:** Full RAG reindex on every document upload slowed down the admin panel.

**Solution:** Incremental updates where possible. Scope rebuilds (only rebuild affected index). Debounce rapid changes.

**Applies to:** RAG service, especially with file watcher triggering potentially frequent rebuilds.

## 8. iCloud Sync Artifacts

**Problem:** Daniel's development folder is iCloud-synced. Files like `.filename.icloud` (placeholder) and `._filename` (extended attributes) appear and trigger file watchers.

**Solution:** Filter: `*.icloud`, `._*`, `.DS_Store`, `*.tmp`, `*.swp`, `~$*` (Office temp files).

**Applies to:** File watcher service — critical for CBC.

## 9. Docker Volume Permissions

**Problem:** Files created inside Docker container have root ownership. OrbStack handles this differently than Docker Desktop.

**Solution:** Use consistent UID/GID in Dockerfiles. Test with OrbStack specifically (Daniel's runtime).

**Applies to:** All Docker containers, especially with host-mounted volumes for file watcher.

## 10. Context Window Limits

**Problem:** Long conversations + large RAG context can exceed LLM context window.

**Solution:** Context compression service (from HRDD Helper) summarizes older messages. RAG chunk count configurable. Monitor actual token usage.

**Applies to:** Especially Compare All mode where multiple company RAGs are loaded simultaneously.
