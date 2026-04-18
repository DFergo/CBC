# CBC — Project Status

**Current Sprint:** 2 — Frontend Page Flow (No Chat Yet)
**Last Updated:** 2026-04-18

---

## Sprint 1 — COMPLETE

### Deliverables
- [x] `CBCopilot/src/backend/main.py`
- [x] `CBCopilot/src/backend/core/config.py`
- [x] `CBCopilot/src/backend/api/v1/admin/auth.py`
- [x] `CBCopilot/src/frontend/sidecar/main.py` (minimal: /internal/health + /internal/config)
- [x] `CBCopilot/Dockerfile.backend`
- [x] `CBCopilot/Dockerfile.frontend`
- [x] `CBCopilot/docker-compose.backend.yml`
- [x] `CBCopilot/docker-compose.frontend.yml`
- [x] `CBCopilot/config/deployment_backend.json`
- [x] `CBCopilot/config/deployment_frontend.json`
- [x] `CBCopilot/config/nginx/frontend.conf`
- [x] `CBCopilot/config/supervisord.conf`
- [x] Admin SPA shell (Setup/Login/Dashboard-placeholder) + Vite/Tailwind config
- [x] Frontend React stub so Nginx has something to serve before Sprint 2
- [x] ADR-007 logged: online-detection criterion moved from Sprint 1 to Sprint 4

### Acceptance Criteria (to verify manually after docker build)
- [ ] `docker compose -f CBCopilot/docker-compose.backend.yml up` starts without errors
- [ ] `GET http://localhost:8100/health` returns `{"status": "ok"}` (host port — `CBC_BACKEND_PORT`)
- [ ] `GET http://localhost:8100/admin/` serves the admin SPA (login page)
- [ ] Admin setup flow works: set password → login → JWT returned
- [ ] `docker compose -f CBCopilot/docker-compose.frontend.yml up` starts without errors
- [ ] `GET http://localhost:8190/internal/health` returns `{"status": "ok"}` (host port — `CBC_FRONTEND_PORT`)
- [ ] Sidecar reachable from backend container (smoke test via `docker exec`)

### Deviations
- Moved "backend polls sidecar and detects online" to Sprint 4 (ADR-007). `polling.py` is a Sprint 6 deliverable; `frontend_registry.py` is Sprint 4.
- Added `campaigns_path` to backend config for later sprints (Sprint 3+ uses it).

---

## Sprint 2 — PLANNED

Next sprint scaffolds the full frontend page flow: LanguageSelector → Disclaimer → Session → Auth → Instructions → CompanySelectPage → SurveyPage, plus the sidecar endpoints each page needs.

---

## Blocked / Questions
(none)
