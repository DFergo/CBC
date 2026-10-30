# Changelog

## 2026-10-30

- Published images: `ghcr.io/dfergo/cbc-backend` (`arm64`) and `ghcr.io/dfergo/cbc-frontend` (`amd64`, `arm64`); tags `latest` (`main`) and `sha-<commit>`.
- Backend build arg `INSTALL_LOCAL_MODELS`: the published image ships without local embedding/reranker models (embeddings and reranking through an API); building from source keeps them by default. Clear errors in the log and the admin panel when no usable model is configured; the active mode is logged at startup.
- Frontend serves two surfaces on two ports: public (`80`) and backend-only (`8080`, `/backend/v1/*`). Backend requests are HMAC-signed (`CBC_BACKEND_SECRET` on the frontend, `CBC_FRONTEND_SECRET` installation secret on the backend).
- Frontend registration by address only, with per-frontend access modes (signed, trusted network, legacy), optional own secret and extra headers; **Security** panel and mode badges in Admin → Frontends. Existing registrations keep working unchanged (legacy).
- Deployment examples for LAN, VPS and same-host topologies (`deploy/`) and a new installation guide (`docs/INSTALL.md`).
- Searchable model field in the LLM and embedding slot editors (accepts an exact model ID).
