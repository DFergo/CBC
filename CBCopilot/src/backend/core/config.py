# Adapted from HRDDHelper/src/backend/core/config.py
# CBC-specific changes:
#   - removed letta_compression_threshold (handled by context_compressor later)
#   - added rag_watcher_enabled + rag_watcher_debounce_seconds (SPEC §4.3, §6.1)
#   - removed reporter LLM slot (ADR-004)
import json
import os
from pydantic import BaseModel


class BackendConfig(BaseModel):
    role: str = "backend"
    lm_studio_endpoint: str = "http://localhost:1234/v1"
    lm_studio_model: str = "qwen3-235b-a22b"
    ollama_endpoint: str = "http://localhost:11434"
    ollama_summariser_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 8192
    rag_documents_path: str = "./data/documents"
    rag_index_path: str = "./data/rag_index"
    rag_chunk_size: int = 1024
    rag_similarity_top_k: int = 8
    # Sprint 9 (RAG upgrade): swap MiniLM for BGE-M3 — 1024-dim multilingual
    # embeddings; covers all 31 of CBC's UI languages well, including
    # Spanish/Basque/French/Portuguese where MiniLM degrades. Reranker is a
    # cross-encoder applied to the hybrid (vector+BM25) candidates.
    rag_embedding_model: str = "BAAI/bge-m3"
    rag_reranker_enabled: bool = True
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_reranker_fetch_k: int = 30  # fetched from hybrid retrieval before rerank
    rag_reranker_top_n: int = 8     # surfaced to the prompt assembler after rerank
    # Sprint 9 (Anthropic Contextual Retrieval). When True, every chunk gets a
    # short LLM-generated context sentence prepended at index time so embeddings
    # carry document-level grounding ("This chunk is from Annex I salary tables
    # of the Amcor Lezo CBA").
    #
    # Off by default AND recommended off post-Sprint-16. Rationale: CR's most
    # painful use case (numeric / tabular retrieval) is now covered by the
    # Structured Table Pipeline (tables extracted as CSVs + injected verbatim).
    # CR's remaining value is for prose chunks whose markdown header context
    # is ambiguous — a narrow case. It costs one summariser-LLM call per chunk,
    # which means hours of indexing for 100+ CBAs and a slow curation cycle.
    # Toggle available from admin UI for users who want to experiment on
    # prose-only corpora; code kept intact.
    rag_contextual_enabled: bool = False
    rag_contextual_max_doc_chars: int = 12000  # truncate the doc passed to the contextualiser
    rag_watcher_enabled: bool = True
    rag_watcher_debounce_seconds: int = 5
    streaming_enabled: bool = True
    stream_chunk_size: int = 1
    poll_interval_seconds: int = 2
    sessions_path: str = "./data/sessions"
    prompts_path: str = "./data/prompts"
    campaigns_path: str = "./data/campaigns"
    guardrails_enabled: bool = True
    # Sprint 7.5 thresholds (global; per-frontend overrides deferred):
    #   `guardrail_warn_at`  — UI shows the amber banner once the session has
    #                          accumulated this many violations.
    #   `guardrail_max_triggers` — the session is ended backend-side once this
    #                          many violations are reached. The LLM stops
    #                          running on the session entirely.
    # Defaults tuned for the CBC audience (trade-union delegates). Lift them
    # via `deployment_backend.json` if real use needs more forgiveness.
    guardrail_warn_at: int = 2
    guardrail_max_triggers: int = 5
    file_max_size_mb: int = 25
    session_token_reuse_cooldown_days: int = 30
    # Sprint 7 (D2=A): when True, the backend auth flow only issues codes to
    # emails present in the Contacts directory (global + per-frontend). Set
    # to False during bootstrap / demos to let any email receive a code.
    auth_allowlist_enabled: bool = True
    # How long an issued auth code stays valid before the user has to
    # request a new one.
    auth_code_ttl_seconds: int = 900  # 15 minutes


def load_config() -> BackendConfig:
    config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "config/deployment_backend.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return BackendConfig(**data)
    return BackendConfig()


config = load_config()
