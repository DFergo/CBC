# CBC — Changelog

## Sprint 1 — Scaffolding & Core Backend (2026-04-18)

- FastAPI backend: `main.py`, `core/config.py` (CBC-tuned: `rag_watcher_enabled`, `rag_watcher_debounce_seconds`, `campaigns_path`; no `letta_compression_threshold`, no reporter slot)
- Admin auth adapted from HRDD (`/admin/status`, `/admin/setup`, `/admin/login`, `/admin/verify`). Env var renamed to `CBC_DATA_DIR`; admin localStorage key to `cbc_admin_token`
- Admin SPA shell: App/SetupPage/LoginPage/Dashboard-placeholder, Vite + Tailwind. Dashboard is a placeholder until Sprint 3
- Frontend sidecar: minimal `/internal/health` + `/internal/config` (full message queue / SSE / auth / uploads land alongside the pages that use them)
- Frontend React stub so Nginx has something to serve pre-Sprint-2
- Docker: `Dockerfile.backend` (multi-stage admin+python), `Dockerfile.frontend` (multi-stage react+nginx+sidecar), compose files, nginx config, supervisord config — shared `cbc-net` network so backend can reach frontend sidecars
- ADR-007: moved "backend polls sidecar and detects online" from Sprint 1 to Sprint 4 (polling loop lands in Sprint 6)

## Sprint 0 — Project Setup (2026-04-18)

- SpecForge output generated: CLAUDE.md, SPEC.md, MILESTONES.md, architecture docs, knowledge docs
- HRDDHelper/ reference code available in project root
- Claude Code environment (.claude/) configured with commands and settings
