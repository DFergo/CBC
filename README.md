# Collective Bargaining Copilot

A self-hosted AI assistant for trade union representatives: it compares collective bargaining agreements across companies, countries and sectors, cross-checks them with company policies, and gives strategic guidance for negotiations.

It runs as two kinds of Docker containers:

- **Backend** — admin panel, language-model connections, knowledge base (agreements organised by frontend and company), sessions and all stored data.
- **Frontend** — the web page users see, one per campaign or sector. The backend polls the frontends; a frontend never connects to the backend.

Language models can run on your own hardware (Ollama, LM Studio or any OpenAI-compatible server) or at a cloud provider.

## Documentation

- **[Installation guide](docs/INSTALL.md)** — requirements, backend and frontend setup, the three deployment topologies, access modes, operation and troubleshooting.
- [Deployment examples](deploy/) — compose files for a frontend on the local network, on a remote server, or on the same machine as the backend.
- [Changelog](CHANGELOG.md)

## Images

- `ghcr.io/dfergo/cbc-backend` (`arm64`) — without local embedding/reranker models; build from source with `INSTALL_LOCAL_MODELS=true` to include them.
- `ghcr.io/dfergo/cbc-frontend` (`amd64`, `arm64`)

Tags: `latest` (the `main` branch) and `sha-<commit>`.
