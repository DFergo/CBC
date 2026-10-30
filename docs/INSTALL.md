# Collective Bargaining Copilot — Installation Guide

## 1. What you are installing

The Collective Bargaining Copilot (CBC) has two kinds of containers:

- **Backend**: the admin panel, the logic, the calls to the language models, the knowledge base (collective agreements and other documents) and all stored data (sessions, configuration).
- **Frontend**: the web page users see. You deploy **one frontend per campaign or sector**, each with its own address, companies and branding.

```
 Users' browsers                      Your infrastructure
 ───────────────                      ───────────────────────────────────────────
                    public port (80)           backend port (8080)
   browser  ─────────────►  FRONTEND  ◄───────────────────────────  BACKEND  ──► language models
                         (web + queue)        backend polls          (admin, data)   (local or remote)
```

Three rules shape every deployment:

1. **The backend always initiates the connection** (it polls the frontends). A frontend never contacts the backend and does not know where it is. The backend therefore does not need to be reachable from the Internet.
2. **Each frontend has two ports.** The **public port** (container port `80`) serves the web page and the routes the users' browsers use. The **backend port** (container port `8080`) is used only by the backend. **Never expose the backend port to the open Internet.**
3. **Requests on the backend port are signed by default** with a secret shared between the backend and the frontend; a request without a valid signature is rejected (`401`). An unsigned "trusted network" mode exists for networks where nothing but the backend can reach that port (section 5.1). The signature proves *who* is calling; it does not encrypt. On an untrusted network, use an encrypted path (HTTPS through a tunnel, a VPN or an SSH tunnel).

## 2. Choose a deployment

| | Where the frontend runs | How the backend reaches the frontend's backend port | Example |
|---|---|---|---|
| **T1 — Local network** | Another machine on the backend's network | `http://<LAN IP>:<port>` | [`deploy/t1-lan/`](../deploy/t1-lan/) |
| **T2 — Remote server (VPS)** | A server with no VPN to the backend | `https://<private hostname>` through a Cloudflare Tunnel protected by Cloudflare Access | [`deploy/t2-vps/`](../deploy/t2-vps/) |
| **T3 — Same machine** | The same machine as the backend, in separate isolated containers | `http://cbc-frontend:8080` over an internal Docker network | [`deploy/t3-same-host/`](../deploy/t3-same-host/) |

One backend can serve frontends in all three topologies at once.

How to choose:

- **Trying it out or a small installation:** T3. One machine, one `docker compose up`.
- **A frontend on a different machine in the same office:** T1.
- **A public frontend you want away from your internal network:** T2. A compromised public frontend then sits outside your network, not inside it.
- **Highly sensitive deployments:** prefer a separate machine for the frontends (T1 on an isolated network segment, or T2) over T3.

The models can run on the backend machine, on another machine you control, or at a cloud provider. See section 4.4.

## 3. Requirements

- A recent Docker Engine with the Docker Compose v2 plugin (`docker compose`).
- A Linux, macOS or Windows host. The **frontend** image is published for `amd64` and `arm64`; the **backend** image for `arm64` only (section 4.1).
- **Clocks in sync (NTP) on every machine** when frontends use signed mode: signatures more than 2 minutes off are rejected.
- Memory and disk (measured on a fresh installation; plan for your load):
  - Backend, published image (embeddings and reranking through an API): image about 1.2 GB; the process uses about 0.25 GB of RAM after indexing and answering a query, more with many users and large document sets.
  - Backend built with local models (section 4.1): image about 9 GB; about 5 GB of RAM once the local embedding model and reranker are loaded.
  - Frontend: about 55 MB of RAM idle each; the image is about 250 MB.
  - The language models need their own resources on whatever machine runs them.
- Open only what you need: the public port of the frontends (or a tunnel), nothing else.

## 4. Install the backend

### 4.1 With the published image (recommended)

Create a folder, for example `cbc-backend/`, with a `compose.yaml`:

```yaml
services:
  cbc-backend:
    image: ghcr.io/dfergo/cbc-backend:latest
    pull_policy: always
    restart: unless-stopped
    ports:
      - "127.0.0.1:8100:8000"
    volumes:
      - cbc-data:/app/data
    environment:
      - DEPLOYMENT_JSON_PATH=/app/config/deployment_backend.json
      - CBC_DATA_DIR=/app/data
      # Installation secret for signed frontends (section 5.1). Optional.
      - CBC_FRONTEND_SECRET=${CBC_FRONTEND_SECRET:-}

volumes:
  cbc-data:
```

If you use the installation secret, put it in a private `.env` file next to `compose.yaml` (`CBC_FRONTEND_SECRET=<value>`, `chmod 600 .env`). Start the backend:

```bash
docker compose up -d
docker compose logs --tail 20
```

Notes:

- The admin panel listens on container port `8000`; the example publishes it as `8100` **only on `127.0.0.1`**: reach it from the same machine, or through a VPN, an SSH tunnel or a private network address. If you need a LAN address, bind to that specific address (for example `"192.168.1.10:8100:8000"`), never to every interface on an exposed host.
- Image tags: `latest` follows the `main` branch; `sha-<commit>` pins an exact version.
- The published backend image is built for **`arm64`** only. On an `amd64` host, build from source instead (below).
- **The published image does not include local embedding or reranking models.** Configure an embeddings and a reranker API before loading documents (section 4.4). The startup log states the active mode (`RAG model mode: …`), and the admin panel shows an explicit warning while no usable model is configured.

**Build from source (local models included).** Clone the repository and run:

```bash
docker compose -f docker-compose.backend.yml up -d --build
```

The repository's compose builds with `INSTALL_LOCAL_MODELS=true` by default: PyTorch (CPU) and the BGE-M3 embedding model, MiniLM and the bge-reranker-v2-m3 reranker are baked into the image, so the knowledge base works without any extra configuration and without Internet access. Set `INSTALL_LOCAL_MODELS=false` to build the smaller image instead. The host port is `BACKEND_PORT` (default `8100`).

**With Portainer.** *Stacks → Add stack → Repository*, URL `https://github.com/DFergo/CBC`, branch `main`, compose path `docker-compose.backend.yml` (it builds from source). Add the environment variables (`BACKEND_PORT`, `CBC_FRONTEND_SECRET`, optionally `INSTALL_LOCAL_MODELS`) in the stack form. To update: *Pull and redeploy*.

### 4.2 First run

1. Open `http://127.0.0.1:8100` (or the address you published). You will see the admin account setup.
2. Choose a strong password. It is stored hashed in the data volume.
3. Log in.

### 4.3 Where the data lives

Everything the backend stores is under `/app/data` in the `cbc-data` volume: global configuration (connections, LLM settings, SMTP, registered frontends), prompts, glossary and organisations, sessions, the knowledge-base documents and their indexes, and the admin password hash. **Back this volume up** (section 7.2).

The knowledge base and prompts follow three tiers — global, frontend and company — and can be managed from the admin panel **or** directly on disk; a file watcher reindexes after changes:

```
/app/data/
├── documents/                      ← Global documents (all frontends)
├── prompts/                        ← Global prompts
└── campaigns/
    └── {frontend_id}/
        ├── documents/              ← Frontend documents
        ├── prompts/                ← Frontend prompt overrides
        └── companies/
            └── {company_slug}/
                ├── documents/      ← Company documents (collective agreements go here)
                └── prompts/        ← Company prompt overrides
```

### 4.4 Connect the language models

Open **Admin → General**.

**LLM.** A *connection* is an address plus credentials; a *slot* is a job the system needs a model for. You create connections once and assign them to slots.

- **Connection types:** LM Studio, Ollama, or an API (Anthropic, OpenAI, or any OpenAI-compatible server such as vLLM or OpenRouter).
- **Slots:** **Inference** (the chat), **Compressor** (folds long conversations into a running summary), **Summariser** (document summaries and the end-of-session summary emailed to the user) and **Translation** (translates branding texts). Each slot picks its own connection and model and has its own **Save** button. A frontend can override the global choice in its **LLM** panel.

**What each provider supports.** Each slot shows, under every control, whether it is sent, adjusted or ignored for the chosen connection and model, so no setting is a silent no-op. Leave a number blank to not send it (the provider's default applies). In short:

| | Temp, Max tokens | Context (`num_ctx`) | Reasoning | Prompt cache |
|---|---|---|---|---|
| **Mistral API** | sent | not sent | `mistral-large-4`: low/medium/high, cannot be switched off; `mistral-small`/`-medium`: off/high | automatic; best effort for short prompts |
| **OpenRouter** | sent (some models ignore them: the panel says which, from OpenRouter's model list) | not sent | off/low/medium/high where the model supports it | depends on the provider OpenRouter routes to |
| **OpenAI** | sent; reasoning models (o-series, gpt-5) take no temperature | not sent | low/medium/high on reasoning models | automatic |
| **Anthropic** | sent; Max tokens required (4096 if blank); no temperature while thinking | not sent | low/medium/high = thinking budget | breakpoints set automatically |
| **LM Studio, vLLM** | sent | not sent | on/off (`enable_thinking`, plus a fixed instruction in the system prompt when off) | server-side, if enabled |
| **Ollama** | sent | sent | on/off (`think`) | not reported |

- **Reasoning tokens are billed and count against Max tokens.** With reasoning on and a small Max tokens a model can spend the whole budget thinking and return an empty answer. Upgraded installations keep their old behaviour: the former global "Thinking / Reasoning: OFF" setting became **Reasoning: off** on every slot.
- **Usage and prompt cache.** The **Usage and prompt cache** card shows prompt, cached, completion and reasoning tokens per slot and model, with the cache hit rate; the session detail shows the same per session. The system prompt stays identical from turn to turn and the retrieved agreement excerpts are sent last, with the current message, so everything before them can be cached; those excerpts are new on every turn and are never cached.
- **Provider options per connection** (optional, *Provider options* in an OpenAI-compatible API connection): *Provider profile* forces the profile when it cannot be inferred from the endpoint; *Send a per-session prompt cache key* sends a hash of the session (never the session token) to providers that use it; *OpenRouter routing* is OpenRouter's `provider` object, e.g. `{"order": ["alibaba"], "allow_fallbacks": false}`, to keep a session on one endpoint.
- If a provider rejects an optional field (reasoning setting, cache key, usage request), the request is retried once without it and the backend logs which field was dropped.

**RAG pipeline — embeddings and reranker.** The knowledge base needs an embedding model (turns documents and questions into vectors) and, optionally, a reranker (reorders the retrieved passages).

- **API** (required with the published image): an OpenAI-compatible server exposing `/embeddings`, and for the reranker the `/rerank` endpoint offered by servers such as Hugging Face TEI, vLLM or Infinity. Use **Test connection** before saving.
- **Local** (images built with `INSTALL_LOCAL_MODELS=true`): BGE-M3 and bge-reranker-v2-m3 inside the container, on the CPU.
- If a configured API connection fails, the backend reports the error; it never falls back silently to a local model. With no configuration at all, an image with local models uses them and logs it.
- **Changing the embedding model requires re-indexing**, because vectors from different models are not compatible. After saving, click **Reindex**: the new index is built in the background while queries keep using the previous one, and switching happens only when it completes. Previous indexes are kept per provider and model until you delete them.

**Where the model can run.** Anywhere the backend container can reach: the same machine, another machine on your network or VPN, or a cloud provider. Inside the container:

- On Docker Desktop (macOS, Windows) and OrbStack, the host machine is `host.docker.internal`.
- On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service, or use the host's IP address.

**Privacy.** When a slot uses a cloud provider, the text it processes (user messages, uploaded documents, agreements) is sent to that provider. Choose providers and regions that satisfy your data-protection obligations. If everything must stay on your infrastructure, use local or private models for all slots, including embeddings and reranking.

### 4.5 Email (optional)

**Admin → General → SMTP** configures outgoing email: verification codes when a frontend requires authentication, the session summary sent to the user, and administrator notifications. Without SMTP, codes and summaries are only logged.

## 5. Install a frontend

Do these steps once per frontend. The example files are in the [`deploy/`](../deploy/) folder of this repository: clone it, or download the folder you need.

### 5.1 Access modes and secrets

The backend talks to each frontend's backend port in one of these modes, chosen per frontend when you register it (section 5.5):

| Mode | On the frontend | On the backend | When to use it |
|---|---|---|---|
| **Signed — installation secret** (default) | `CBC_BACKEND_SECRET=<installation secret>` | `CBC_FRONTEND_SECRET=<same value>`; register with **the address only** | Most installations |
| **Signed — own secret** | `CBC_BACKEND_SECRET=<this frontend's secret>` | The same secret in that frontend's registration | To isolate one frontend, e.g. on a server run by a third party |
| **Trusted network — unsigned** | `BACKEND_SURFACE_AUTH=trusted-network` (no secret) | Mode *Trusted network* | Only when nothing but the backend can reach the frontend's backend port: the internal Docker network of T3, or a closed network segment |

Generate a secret (at least 32 characters):

```bash
openssl rand -hex 32
```

Keep secrets in private `.env` files (`chmod 600 .env`), never in the repository or in images.

**What each mode gives up:**

| | Installation secret | Own secret | Trusted network |
|---|---|---|---|
| Someone who can reach the backend port without the secret | Rejected (`401`) | Rejected (`401`) | **Full access**: reads and consumes queued user messages and uploads, changes the frontend's configuration, companies and branding, sends responses to users |
| A captured request replayed, or modified in transit | Rejected | Rejected | **Accepted** |
| One secret leaks | **Every** frontend that shares the installation secret is exposed until it is rotated everywhere | Only that frontend | — |
| Rotation | Backend and every frontend | One frontend | — |
| Clocks in sync | Needed | Needed | Not needed |
| Protection rests on | The secret | The secret | **The network alone** |

The admin panel shows each frontend's mode as a badge (**signed**, **trusted network · unsigned**, **legacy**). Each frontend also reports its own mode: if a frontend registered as signed is running with `BACKEND_SURFACE_AUTH=trusted-network`, the panel shows **frontend accepts unsigned**, because the signature then protects nothing. A trusted-network frontend logs a warning at startup and every hour.

*If you lose a secret:* nothing is lost. A secret only proves who is calling; it protects no stored data. Generate a new one and put it in both places (section 7.4).

### 5.2 T3 — same machine as the backend

The T3 example runs **both** the backend and one frontend.

```bash
cd deploy/t3-same-host
cp .env.example .env
```

Edit `.env`: set `FRONTEND_PORT` and `CBC_BACKEND_SECRET` (and the image tags if you want to pin them). The example passes that same value to the backend as its installation secret. Then:

```bash
docker compose up -d
```

The backend and the frontend run in separate containers. The frontend's backend port is **not published** on the host; the backend reaches it over an internal network that only the two share, and the frontend has no route to the backend. Register it with the URL `http://cbc-frontend:8080` and nothing else.

Here the trusted-network mode is acceptable (`BACKEND_SURFACE_AUTH=trusted-network` in `.env`, then register in mode *Trusted network*), since only the backend shares that network; signed mode remains the default.

Residual risk: on that internal network the frontend container can open a connection to the backend's admin port, which is protected only by the admin login. Keep the admin password strong, or place the frontends on another machine for sensitive deployments.

### 5.3 T1 — another machine on the same network

```bash
cd deploy/t1-lan
cp .env.example .env
```

Edit `.env`:

- `FRONTEND_PORT`: the public port on this machine.
- `PUBLIC_BIND`: `127.0.0.1` if users arrive through a tunnel on this machine; the machine's LAN address if office users connect directly.
- `BACKEND_BIND`: **this machine's LAN address**, the one the backend can reach. Do not use `0.0.0.0` on a machine with other interfaces.
- `FRONTEND_BACKEND_PORT`: the backend port on this machine.
- `CBC_BACKEND_SECRET`: the installation secret or this frontend's own secret.

```bash
docker compose up -d
```

Register it with the URL `http://<BACKEND_BIND>:<FRONTEND_BACKEND_PORT>`. Allow that port in the machine's firewall **only from the backend's address**. Use signed mode: other devices on the LAN can usually reach that port.

### 5.4 T2 — a remote server (VPS)

On the server (Docker installed, only SSH open to the Internet):

```bash
cd deploy/t2-vps
cp .env.example .env
```

Edit `.env`: `CBC_BACKEND_SECRET` and `TUNNEL_TOKEN` (from the Cloudflare tunnel you create in section 6), and `FRONTEND_TAG`. Then:

```bash
docker compose up -d
```

The server opens no incoming ports: a Cloudflare Tunnel makes an outgoing connection and publishes two hostnames, one for users and one private hostname for the backend. Section 6 explains how to create them. Register the frontend with the URL `https://<private hostname>` and the two Access headers. Use signed mode; an own secret is a good choice for a server run by someone else.

The example also runs Watchtower to update the frontend nightly (section 7.1).

### 5.5 Register the frontend in the backend

In **Admin → Frontends → Register frontend**:

- **URL:** the address of the frontend's **backend port** (not the public address). It depends on the topology, see above.
- **Name:** a recognisable name. The internal identifier used for the frontend's configuration folder is derived from it.
- **Backend access:** *Signed (recommended)*, *Trusted network — unsigned*, or *Legacy* (only for frontends deployed before the two-port layout; migrate them when you update them).
- **Own secret** (signed mode, optional): leave it blank to use the installation secret. The form tells you when the backend has none; then an own secret is required.
- **Extra headers** (optional; T2): `CF-Access-Client-Id` and `CF-Access-Client-Secret`, from the Cloudflare Access service token.

When you register, the backend **checks that the frontend answers in the chosen mode** before storing it. If it fails, the message tells you why: unreachable, signature rejected (check the secret and the clocks), the frontend requires signing, or the URL is not a backend port.

A healthy frontend shows as **online** with its mode badge. To change the URL, mode, secret or headers later, use the frontend's **Security** button: URL, mode and credentials are saved together and checked against the frontend before they are stored. Secrets are write-only: the panel only shows whether one is set.

Then select the frontend to configure it: **Companies** (each company gets its own documents and prompts), **Branding**, **Session settings** (authentication, resume window, automatic deletion), **Prompts**, **RAG**, **Organisations** and **LLM** overrides.

### 5.6 Check it (read-only)

- Public port: `GET /` returns `200`; `GET /internal/config` returns `200`; `GET /backend/v1/health` returns `404` (the public port does not serve the backend routes).
- Backend port, **without** a signature (signed mode): `GET /backend/v1/health` returns `401`.
- **Admin → Frontends:** the frontend appears **online** with the expected badge.
- Do not call `GET /backend/v1/queue` by hand on a frontend in use: it hands the queued user messages to whoever calls it, and the backend then never sees them.

### 5.7 More frontends

Repeat section 5 with a different public port (and a different backend port if the machine is shared) and a different project name (`docker compose -p <name>`). With the installation secret every frontend uses the same `CBC_BACKEND_SECRET`; with own secrets, a different one each. Each frontend has its own data volume.

**With Portainer:** a stack from the repository with compose path `docker-compose.frontend.yml` and, as environment variables, `FRONTEND_PORT` (default `8190`), `FRONTEND_BACKEND_PORT` (default `8191`), `BACKEND_BIND` (default `127.0.0.1`) and either `CBC_BACKEND_SECRET` or `BACKEND_SURFACE_AUTH=trusted-network`. Give each stack a distinct name: it prefixes the container and volume names.

## 6. Public access with a Cloudflare Tunnel

A tunnel lets users reach a frontend without opening any incoming port. In the Cloudflare Zero Trust dashboard:

1. **Create a tunnel** (remotely managed, *Cloudflared*) and copy its token into the frontend's `TUNNEL_TOKEN`.
2. **Public hostname for users:** point `https://<users hostname>` to `http://cbc-frontend:80` (the service name in the compose network), or to `http://localhost:<FRONTEND_PORT>` if `cloudflared` runs on the host. **Map only the public port here.**
3. **Private hostname for the backend (T2):** point `https://<private hostname>` to `http://cbc-frontend:8080`.
4. **Protect the private hostname with Cloudflare Access:** create a *service token*, then a self-hosted Access application for the private hostname with a single policy whose action is **Service Auth** and which includes only that token. Enable **Protect with Access** on that hostname in the tunnel so that `cloudflared` validates the Access credential. Copy the token's client ID and secret (the secret is shown once) into the frontend's extra headers in the backend.

When the domain is managed by Cloudflare, adding a hostname to the tunnel creates its DNS record.

If you do not use Cloudflare, any reverse proxy that terminates HTTPS in front of the **public port** works. Whatever you use, **never publish the backend port to the open Internet.**

## 7. Operate it

### 7.1 Updates

```bash
docker compose pull
docker compose up -d
```

For stacks built from source: `git pull`, then `docker compose -f <compose file> up -d --build` (or *Pull and redeploy* in Portainer).

To update automatically, add the label `com.centurylinklabs.watchtower.enable=true` to the service and run Watchtower with `--label-enable` on a nightly schedule, so only labelled containers are touched. With recent Docker Engines the `containrrr/watchtower` image needs `DOCKER_API_VERSION` set to a supported API version such as `1.44`; otherwise it stops with "client version 1.25 is too old". The T2 example already does this.

Use `latest`, or pin `sha-<commit>` and update on purpose. To roll back, set the previous `sha-<commit>` tag in the compose file and run `docker compose up -d`.

If a script re-points registered frontends to new addresses (for example after a DHCP change), it must keep the **backend port** in the URL.

### 7.2 Back up

- **The data volume** (everything). Compose prefixes volume names with the project name, so copy it through the running container:

  ```bash
  docker run --rm --volumes-from "$(docker compose ps -q cbc-backend)" -v "$PWD":/backup alpine \
    tar czf /backup/cbc-data.tgz -C /app/data .
  ```

  Stop the backend first if you need a perfectly consistent copy. The volume contains the SMTP password, provider API keys and frontend secrets: store the copy like a password.
- **Frontends** hold only transient queues and a copy of what the backend pushed to them. If a frontend's volume is lost, recreate it, then restart the backend (or save that frontend's branding, companies and session settings again in the admin) so the backend pushes them again.

### 7.3 Logs and health

```bash
docker compose logs --tail 100
docker compose ps
```

- Backend: `GET /health` returns `{"status":"ok"}`. The startup log shows the RAG model mode.
- Frontend: `GET /nginx-health` on the public port returns `ok`.

### 7.4 Rotate a secret without downtime

**One frontend's own secret:**

1. On the frontend, put the new value in `CBC_BACKEND_SECRET` and the old value in `CBC_BACKEND_SECRET_PREVIOUS`, then `docker compose up -d`.
2. In **Admin → Frontends → Security**, enter the new secret and save.
3. Empty `CBC_BACKEND_SECRET_PREVIOUS` and run `docker compose up -d` again.

**The installation secret:**

1. On every frontend that uses it, set the new value in `CBC_BACKEND_SECRET` and the old one in `CBC_BACKEND_SECRET_PREVIOUS`, then `docker compose up -d`.
2. On the backend, set the new `CBC_FRONTEND_SECRET` and restart it.
3. On every frontend, empty `CBC_BACKEND_SECRET_PREVIOUS` and run `docker compose up -d`.

### 7.5 Reset the admin password

```bash
docker compose exec cbc-backend rm /app/data/.admin_hash
docker compose restart cbc-backend
```

Then open the admin panel and create a new account.

### 7.6 Moving a frontend to the two-port layout

Frontends registered before the two-port layout keep working with an updated backend: they show as **legacy** and use the old protocol, even after `CBC_FRONTEND_SECRET` is set. To move one:

1. Update the backend (and set `CBC_FRONTEND_SECRET` if you use the installation secret).
2. Redeploy the frontend with the current image, `CBC_BACKEND_SECRET` set (or `BACKEND_SURFACE_AUTH=trusted-network`) and the backend port published (`FRONTEND_BACKEND_PORT`, `BACKEND_BIND`).
3. In **Admin → Frontends → Security**, set the backend-port URL and the mode in **one save**.

Do steps 2 and 3 back to back: the current frontend image no longer serves the old routes, so between them the backend cannot poll it (users' messages wait in the frontend queue for up to 5 minutes). A legacy frontend that updates its image automatically goes offline until step 3.

## 8. Security checklist

- [ ] The backend's admin port is not published on an untrusted network.
- [ ] No frontend publishes its backend port to the open Internet.
- [ ] Frontends use signed mode unless only the backend can reach their backend port; secrets have at least 32 random characters, live in private `.env` files and are never committed.
- [ ] Users reach the frontends only through HTTPS.
- [ ] Clocks are synchronised on all machines.
- [ ] The admin password is long and unique.
- [ ] The data volume is backed up, and the copies are stored like passwords.
- [ ] You know which model providers are local and which are cloud, and your data-protection obligations are met for each.
- [ ] On a remote server, only the administration port (SSH) is open, restricted to key-based login.
- [ ] Updates are applied regularly (or automated for labelled containers).

## 9. Troubleshooting

**The frontend is registered but shows offline, or the backend says "URL not reachable".**
Check that the URL is the frontend's **backend port** address and that the backend machine can reach it (`curl` from the backend host). In T2, check the tunnel is running and the Access headers are correct.

**"Rejected the signature" (HTTP 401).**
The secret differs between the frontend and the backend (installation secret or own secret), or the clocks are more than about 2 minutes apart. Check both, and synchronise time (NTP).

**"Requires signed requests" when registering in trusted-network mode.**
The frontend runs in signed mode. Either register it as *Signed*, or start it with `BACKEND_SURFACE_AUTH=trusted-network`.

**"No backend surface at …".**
The URL points to the public port, or the frontend runs an image from before the two-port layout. Use the backend port; for an old frontend, choose mode *Legacy* or update it.

**"Embedding / reranker models unavailable" in the admin panel.**
The backend image has no local models and the RAG pipeline is set to *local*. Configure an embeddings and a reranker API in **Admin → General → RAG pipeline**, or run an image built with `INSTALL_LOCAL_MODELS=true`.

**The chat does not answer.**
Check the frontend is **enabled** and **online** in the admin, that the Inference slot is healthy, and read the backend logs. If the knowledge base fails (embeddings API down or misconfigured), the backend logs the error explicitly.

**A language model does not answer.**
Check the connection status in **Admin → General → LLM**. From inside the container, `host.docker.internal` only works on Docker Desktop and OrbStack, or on Linux with the `extra_hosts` entry.

**Poor retrieval after changing the embedding model.**
The new model is saved but not applied until the index is rebuilt: click **Reindex** in the RAG pipeline section.

**Documents dropped on disk are not picked up.**
The file watcher waits 30 seconds after the last change before reindexing. Temporary sync files (`*.icloud`, `.DS_Store`, `._*`) are ignored; prefer local volumes over cloud-synced folders.

## 10. Stop and remove

```bash
docker compose down
```

This keeps the data. To delete the data as well (irreversible), remove the volumes: `docker compose down -v`.

## Appendix: ports and variables

| Item | Container port | Default | Who uses it |
|---|---|---|---|
| Backend admin panel and API | `8000` | `BACKEND_PORT` = `8100` | Administrator |
| Frontend public surface | `80` | `FRONTEND_PORT` = `8190` / `PUBLIC_BIND` | Users' browsers |
| Frontend backend surface | `8080` | `FRONTEND_BACKEND_PORT` = `8191` / `BACKEND_BIND` = `127.0.0.1` | The backend only |

| Variable | Where | Meaning |
|---|---|---|
| `CBC_FRONTEND_SECRET` | backend | Installation secret: signs requests to every signed frontend without its own secret (at least 32 characters) |
| `CBC_BACKEND_SECRET` | frontend | Signing secret: the installation secret or this frontend's own secret (at least 32 characters) |
| `CBC_BACKEND_SECRET_PREVIOUS` | frontend | Old secret, accepted while rotating |
| `BACKEND_SURFACE_AUTH` | frontend | `signed` (default) or `trusted-network` (no signature check; see section 5.1) |
| `FRONTEND_PORT`, `PUBLIC_BIND` | frontend | Public port and the address it listens on |
| `FRONTEND_BACKEND_PORT`, `BACKEND_BIND` | frontend | Backend port and the address it listens on (default `127.0.0.1`) |
| `BACKEND_PORT` | backend (repository compose) | Host port of the admin panel and API |
| `INSTALL_LOCAL_MODELS` | backend build | `true` (repository default): local embedding and reranker models in the image; `false` (published image): API only |
| `TUNNEL_TOKEN` | frontend (T2) | Cloudflare Tunnel token |
| `FRONTEND_TAG`, `BACKEND_TAG` | compose | Image tag to run |
| `CBC_DATA_DIR`, `DEPLOYMENT_JSON_PATH` | backend | Data directory and deployment configuration file inside the container |
