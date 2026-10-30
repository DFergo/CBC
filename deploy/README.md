# Deployment topologies

Reference for the example compose files in this folder. Step-by-step installation: [`docs/INSTALL.md`](../docs/INSTALL.md).

The frontend container exposes two surfaces on two ports:

| Container port | Surface | Who uses it | Expose it to |
|---|---|---|---|
| `80` | Public: SPA + browser routes (`/internal/*`) | Users' browsers | Users / a cloudflared public hostname |
| `8080` | Backend: `/backend/v1/*` (queue, uploads, config, responses) | The CBC backend only | Only a private path to the backend — never the open Internet |

The backend always initiates the connection (pull-inverse): the frontend never needs to know where the backend is. The backend registers the URL of the frontend's **backend port**, not the public URL.

## Registering a frontend: just the address

Set one **installation secret** on the backend and give the same value to every frontend:

```bash
openssl rand -hex 32        # ≥ 32 characters
```

- Backend: `CBC_FRONTEND_SECRET=<value>`
- Each frontend: `CBC_BACKEND_SECRET=<value>`

Then **Admin → Frontends → Add Frontend** needs only the backend-port URL (access mode **Signed**, the default). A frontend can still get its **own secret** (Security panel), which overrides the installation secret for that frontend only.

## Access modes

| Mode (admin) | Frontend env | What the backend sends | Use it when |
|---|---|---|---|
| **Signed** — installation secret | `CBC_BACKEND_SECRET` = backend's `CBC_FRONTEND_SECRET` | HMAC-signed requests to `/backend/v1/*` | Default, any topology |
| **Signed** — own secret | `CBC_BACKEND_SECRET` = that frontend's secret | Same | You want to isolate one frontend (e.g. on a third-party VPS) |
| **Trusted network — unsigned** | `BACKEND_SURFACE_AUTH=trusted-network` (no secret) | Unsigned requests to `/backend/v1/*` | Only nothing but the backend can reach port 8080 (same-host internal Docker network, closed LAN segment) |
| **Legacy** | — (frontend on the image from before the two-port split) | Old unsigned `/internal/*` routes | Transition only, until that frontend is updated |

### What each mode gives up

| | Installation secret | Own secret | Trusted network | Legacy |
|---|---|---|---|---|
| Someone who can reach port 8080 but has no secret | Rejected (401) | Rejected (401) | **Full access**: reads/consumes queued user messages and uploads, pushes config, branding and chat responses | Not signed — migrate to a current mode |
| Captured request replayed | Rejected (nonce + ±120 s window) | Rejected | **Accepted** | Not signed |
| Request modified in transit (no TLS) | Rejected (body is signed) | Rejected | **Accepted** | Not signed |
| One frontend's secret leaks | **All** frontends sharing the installation secret are exposed until it is rotated everywhere | Only that frontend | n/a | n/a |
| Rotation | Change `CBC_FRONTEND_SECRET` on the backend and `CBC_BACKEND_SECRET` on every frontend (use `CBC_BACKEND_SECRET_PREVIOUS` on the frontends for a no-downtime switch) | One frontend + its Security panel | n/a | n/a |
| Clock sync needed | Yes (NTP, ±120 s) | Yes | No | No |
| Protection then rests on | The secret | The secret | **The network alone** (`BACKEND_BIND`, internal Docker network, firewall, Cloudflare Access) | Transition only |

The admin shows the mode as a badge on each frontend (**signed**, **trusted network · unsigned**, **legacy**). Frontends report their own mode on every poll: if a frontend registered as signed is running with `BACKEND_SURFACE_AUTH=trusted-network`, the admin shows **frontend accepts unsigned**, because signing then protects nothing. A trusted-network frontend logs a warning at startup and hourly.

## Topologies

| | Where the frontend runs | How the backend reaches port 8080 | Recommended mode | Example |
|---|---|---|---|---|
| **T1** | Another machine on the backend's LAN | `http://<LAN IP>:<FRONTEND_BACKEND_PORT>` (`BACKEND_BIND` = that LAN IP) | Signed (other LAN devices can reach the port) | [`t1-lan/`](t1-lan/) |
| **T2** | A VPS (no VPN) | `https://<backend hostname>` on a cloudflared tunnel, Cloudflare Access with a service token (sent as extra headers) | Signed (own or installation secret) | [`t2-vps/`](t2-vps/) |
| **T3** | Same machine as the backend, separate containers | `http://cbc-frontend:8080` over an internal Docker network shared only by the two | Signed; trusted network is acceptable here | [`t3-same-host/`](t3-same-host/) |

One backend can serve frontends in all three topologies and modes at once.

## Upgrading an existing frontend

Frontends registered before the two-port split keep working with an upgraded backend: they show as **legacy** and use the old protocol, even after `CBC_FRONTEND_SECRET` is set. To move one:

1. Upgrade the backend (and set `CBC_FRONTEND_SECRET` if you use the installation secret).
2. Redeploy the frontend with the new image, `CBC_BACKEND_SECRET` set (or `BACKEND_SURFACE_AUTH=trusted-network`) and the backend port published (`FRONTEND_BACKEND_PORT`, `BACKEND_BIND`).
3. In Admin → Frontends → **Security**, set the backend-port URL and the mode in **one save**. The save is verified against the frontend before it is stored.

Do steps 2 and 3 back to back: the new frontend image no longer serves the old routes, so between them the backend can't poll it (users' messages wait in the frontend queue for up to 5 minutes).

## Checks (read-only)

- Public port: `GET /` → 200, `GET /internal/config` → 200, `GET /backend/v1/health` → 404.
- Backend port without a signature: `GET /backend/v1/health` → 401 (signed mode).
- Admin → Frontends shows the frontend **online** with the expected badge.
- Never call `GET /backend/v1/queue` by hand on a live frontend: it consumes queued messages.
