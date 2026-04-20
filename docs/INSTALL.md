# CBC — Deployment & Install Guide

This guide walks an operator through a first deployment of the Collective Bargaining Copilot.

CBC is a **pull-inverse** system (HRDD-parity design) made of two independent docker-compose stacks:

- **Backend** (`docker-compose.backend.yml`) — FastAPI + embedded admin SPA. One per deployment. Holds the RAG, polls frontends, runs the LLM traffic.
- **Frontend** (`docker-compose.frontend.yml`) — React + Nginx + Python sidecar. You can stand up one or many; each one is a separate stack, typically on its **own** Docker host.

**Backend and frontend live on different machines by design**. The backend *polls* the registered frontend URLs over the LAN / Tailscale / public-hostname — there is NO shared Docker network, NO service-name DNS between them. Each stack runs on Docker's default bridge network, which is why the compose files are intentionally minimal.

Single-host deployments also work: just treat them as two stacks on the same Docker daemon, each with its published port.

## 1. Prerequisites

- Docker Engine ≥ 24.0 (OrbStack on macOS works identically) on each host.
- ~4 GB free disk for the backend volume (RAG indexes + uploaded docs).
- **LLM provider** reachable from the backend container:
  - local: LM Studio or Ollama running on the backend host, reachable via `host.docker.internal`.
  - remote: an API key for Anthropic, OpenAI, or any OpenAI-compatible endpoint. Pass the key via an environment variable on the backend container.
- SMTP credentials if you want auth codes / summary emails to actually land. Without SMTP, CBC runs in dev mode and shows the auth code in the UI.
- Network reachability: each frontend host must be reachable by the backend host on `CBC_FRONTEND_PORT` (8190 by default). Tailscale is the easy path; LAN hostnames / mDNS also work.

## 2. Deploy the backend

From `CBCopilot/` on the backend host:

```bash
docker compose -f docker-compose.backend.yml build
docker compose -f docker-compose.backend.yml up -d
```

The backend listens on host port `8100` by default. Override via the `CBC_BACKEND_PORT` env var or Portainer stack variables:

```bash
CBC_BACKEND_PORT=9000 docker compose -f docker-compose.backend.yml up -d
```

The container always listens on `8000` internally. Write down the backend's **reachable URL** from the frontends' perspective (e.g. `http://100.78.12.109:8100` over Tailscale, or `http://backend.lan:8100` over LAN DNS) — you'll pass it to the frontend stacks as `CBC_BACKEND_URL`.

### First-run admin setup

Open `http://localhost:8100/admin/` in a browser. You'll be prompted to set an admin password on the first visit. The setup page only shows on first run; after that it's a login screen.

### LLM configuration

Open the **LLM** tab and configure the three slots (`inference`, `summariser`, `compressor`):

- **Provider**: `lm_studio` | `ollama` | `api`
- **Endpoint**: for `lm_studio` and `ollama` use `http://host.docker.internal:<port>` (1234 for LM Studio, 11434 for Ollama). For `api`, pick a flavour (anthropic / openai) and enter the endpoint.
- **API key env var** (remote providers only): the *name* of an environment variable that holds the key. Set that env var on the backend container so the key never lives in config files. Example: add `ANTHROPIC_API_KEY=...` to the backend compose or Portainer stack vars and set `api_key_env = "ANTHROPIC_API_KEY"` in the admin.
- **Model**: click the auto-detect dropdown — CBC pulls `/v1/models` (OpenAI-compatible) or `/api/tags` (Ollama) and lists what's loaded.

The top of the page shows a green/amber indicator — green means the endpoint is reachable.

### SMTP (optional)

Open the **SMTP** tab and fill in host, port, user, password, from-address. Without SMTP, auth codes and session summaries are logged but not emailed.

## 3. Deploy a frontend

Each frontend is a separate stack, typically on its **own** Docker host. From `CBCopilot/` on that host:

```bash
CBC_FRONTEND_PORT=8190 CBC_BACKEND_URL=http://<backend-host>:8100 \
  docker compose -p cbc-fe-graphical -f docker-compose.frontend.yml up -d
```

`<backend-host>` is whatever address the backend is reachable at from this frontend's host (Tailscale IP, LAN hostname, `.local` Bonjour name, etc.). The backend stack must publish its port on that host.

For additional frontend stacks on the same machine (different campaign / union), use a different `-p` project name + a different port:

```bash
CBC_FRONTEND_PORT=8191 CBC_BACKEND_URL=http://<backend-host>:8100 \
  docker compose -p cbc-fe-eu -f docker-compose.frontend.yml up -d
```

The `-p` project flag isolates container names and named volumes (`cbc-fe-graphical_cbc-frontend_1` vs `cbc-fe-eu_cbc-frontend_1`), each with its own `/app/data`. The compose file intentionally omits `container_name` so the prefix works.

### Register the frontend with the backend

Open the admin panel (`http://<backend-host>:8100/admin/`) → **Frontends** tab → **Add frontend**. Fill in:

- **URL**: the frontend's reachable address from the backend's host. Same pattern as `CBC_BACKEND_URL` above but in the opposite direction — e.g. `http://frontend-m4.local:8190`, `http://100.78.12.115:8190`.
- **Name**: human-readable label (Graphical & Packaging EU, etc.). The backend derives an internal `frontend_id` slug from this.

The backend's polling loop kicks in within 2 s and the frontend flips to status `online` once it's reachable.

### Portainer deployment

Both stacks deploy cleanly from Portainer in two flavours:

1. **Repository mode** (recommended). Add Stack → Repository:
   - Repository URL: the Git URL of this repo.
   - Compose path: `CBCopilot/docker-compose.backend.yml` (or `.../docker-compose.frontend.yml`).
   - Environment variables: set `CBC_BACKEND_PORT` / `CBC_FRONTEND_PORT` / `CBC_BACKEND_URL` without editing the YAML.
   - Stack name: whatever you like — it becomes the prefix for container names + named volumes. For multiple frontend stacks on one host, give each a distinct stack name (e.g. `cbc-fe-graphical`, `cbc-fe-eu`).
   - On git push, redeploy from the stack's **Pull and redeploy** button.

2. **Web editor mode**. Add Stack → Web editor, paste the contents of the compose file, tweak inline (ports, build args, extra env vars), and deploy. You lose the Git auto-pull, but you can edit directly from Portainer's UI.

No Docker network needs to exist beforehand. Each stack runs on Docker's default bridge network and talks to the other machine over published TCP ports, exactly like HRDD Helper.

## 5. Per-frontend configuration

In the admin **Frontends** tab, click a registered frontend to open its config panel:

- **Branding** (logo, colors, app title, org name, free-text disclaimer/instructions)
- **Sessions** (auth required, session resume window, auto-close, privacy auto-destroy)
- **LLM override** (optional — pick a different LLM slot config than global)
- **RAG settings** (combine_global_rag on/off)
- **Companies** (add company slugs; each slug gets its own documents/prompts sub-tree)
- **Organizations override** (inherit / own / combine)

For any free-text disclaimer/instructions you set, the admin panel also provides a **Translations** block with:
- **Source language** picker (the language you wrote the text in)
- **Download JSON** — export the source + translations to edit externally
- **Upload JSON** — import a filled-in bundle
- **Auto-translate missing** — kick a backend LLM job that fills empty target languages using the summariser slot

## 6. Adding content

Three disk tiers (from `CBCopilot/config/` reference schema):

```
/app/data/
├── documents/                      ← Global RAG (all frontends)
├── prompts/                        ← Global prompts
└── campaigns/
    └── {frontend_id}/
        ├── documents/              ← Frontend RAG
        ├── prompts/                ← Frontend prompt overrides
        └── companies/
            └── {company_slug}/
                ├── documents/      ← Company RAG (CBAs here)
                └── prompts/        ← Company prompt overrides
```

Drop PDFs / TXT / MD / DOCX into a `documents/` folder and the file watcher reindexes automatically (5 s debounce). Same for prompts — edit a `.md` file and the next session picks it up.

## 7. Verifying the install

Quick smoke test:

1. Admin panel loads at `http://localhost:8100/admin/`, LLM tab shows green indicator.
2. Frontend at `http://localhost:8190/` renders the language picker.
3. Pick a language → disclaimer → session token → (auth) → instructions → company select → survey → chat.
4. Send a test message. The backend logs show `polling` pulling the message and `llm_provider` streaming a response.
5. End session — if email configured, the summary arrives.

## 8. Upgrading

For every sprint release:

```bash
git pull
docker compose -f docker-compose.backend.yml build
docker compose -f docker-compose.backend.yml up -d

# Repeat for each running frontend stack
docker compose -f docker-compose.frontend.yml build
docker compose -f docker-compose.frontend.yml up -d
```

Volumes persist data across rebuilds. Admin passwords, session store, RAG indexes, and branding overrides survive.

## 9. Troubleshooting

**Frontend doesn't appear in admin Frontends tab**
- Both stacks are on `cbc-net`? `docker network inspect cbc-net` should list both containers.
- Frontend sidecar logs should show `registered with backend` within 30 s of boot.

**LLM indicator is red**
- `host.docker.internal` resolves inside the backend container? `docker exec cbc-backend getent hosts host.docker.internal` should return an IP.
- On Linux (not OrbStack / Docker Desktop) you may need `extra_hosts: ["host.docker.internal:host-gateway"]` in the compose file.

**`.icloud` placeholder files in documents/**
- Daniel's dev host syncs via iCloud. The file watcher already filters `*.icloud`, `.DS_Store`, `._*`. Production hosts should use local volumes, not iCloud mounts.

**Sessions not persisting across a rebuild**
- Confirm the named volume is `cbc-data` and not a bind mount to an ephemeral dir. `docker volume inspect cbc-data` should show it under `/var/lib/docker/volumes/`.

**Auto-translate takes forever / fails**
- It's synchronous and can take ~30–60 s on a local model for 30 targets × 2 text blocks. Smaller summariser models fail more often — check `llm_provider` logs and either enlarge the summariser model or rely on the Download/Upload JSON workflow.
